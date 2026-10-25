// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// Package jobs implements the end-to-end music sheet processing pipeline and persistent batch job queue.
package jobs

import (
	"archive/zip"
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/alexismp/akkord/internal/config"
	"github.com/alexismp/akkord/internal/drive"
	"github.com/alexismp/akkord/internal/harmony"
	"github.com/alexismp/akkord/internal/oauth"
	"github.com/alexismp/akkord/internal/rustbridge"
	"github.com/alexismp/akkord/internal/store"
)

// SheetProcessReport summarizes the processing result for a single PDF music sheet.
type SheetProcessReport struct {
	InputName          string                        `json:"input_name"`
	OutputPath         string                        `json:"output_path,omitempty"`
	Mode               string                        `json:"mode"`
	DetectedKey        string                        `json:"detected_key"`
	AccuracyScore      int                           `json:"accuracy_score"`
	AnnotationsCount   int                           `json:"annotations_count"`
	Summary            string                        `json:"summary"`
	DriveUploadedID    string                        `json:"drive_uploaded_id,omitempty"`
	DriveWebViewLink   string                        `json:"drive_web_view_link,omitempty"`
	TokenUsage         *rustbridge.TokenUsageStats   `json:"token_usage,omitempty"`
	AnalysisResult     *rustbridge.HarmonyAnalysisResult `json:"-"`
}

// Pipeline orchestrates the Rust PDF engine (`akkord-pdf-engine`), Gemini Harmony Engine, and Google Drive.
type Pipeline struct {
	Config    config.AkkordConfig
	Drive     *drive.DriveConnector
	Rust      *rustbridge.Engine
	Harmony   *harmony.Engine
}

// NewPipeline creates a new Pipeline for the given configuration and optional OAuth token.
func NewPipeline(cfg config.AkkordConfig, oauthAccessToken string) *Pipeline {
	return &Pipeline{
		Config:  cfg,
		Drive:   drive.NewDriveConnector(cfg.GoogleCredentialsPath, oauthAccessToken),
		Rust:    rustbridge.NewEngine(cfg.RustEngineBin),
		Harmony: harmony.NewEngine(cfg),
	}
}

// ProcessSingleSheet processes a single SheetFile through Rust layout detection, Gemini analysis, and Rust vector annotation.
func (p *Pipeline) ProcessSingleSheet(sheet drive.SheetFile, tmpDir string) (*SheetProcessReport, error) {
	localPDF, err := p.Drive.DownloadPDF(sheet, tmpDir)
	if err != nil {
		return nil, err
	}

	workDir := filepath.Join(tmpDir, "work_"+strings.TrimSuffix(filepath.Base(sheet.Name), filepath.Ext(sheet.Name)))
	_ = os.MkdirAll(workDir, 0o755)

	layoutRes, err := p.Rust.AnalyzeLayout(localPDF, workDir)
	if err != nil {
		return nil, err
	}

	analysis, err := p.Harmony.AnalyzeSheet(sheet.Name, layoutRes)
	if err != nil {
		return nil, err
	}

	if !analysis.IsMusicSheet {
		return &SheetProcessReport{
			InputName:        sheet.Name,
			Mode:             "skipped",
			DetectedKey:      "-",
			AccuracyScore:    0,
			AnnotationsCount: 0,
			Summary:          analysis.OverallSummary,
			TokenUsage:       analysis.TokenUsage,
			AnalysisResult:   analysis,
		}, nil
	}

	suffix := config.FileSuffix(p.Config.Language, analysis.HasExistingChords)
	mode := "add_chords"
	if analysis.HasExistingChords {
		mode = "analyze"
	}

	stem := strings.TrimSuffix(filepath.Base(sheet.Name), filepath.Ext(sheet.Name))
	outputFilename := stem + suffix

	var outputPath string
	if sheet.LocalPath != "" && p.Config.OutputDir == "" {
		outputPath = filepath.Join(filepath.Dir(sheet.LocalPath), outputFilename)
	} else {
		_ = os.MkdirAll(p.Config.OutputDir, 0o755)
		outputPath = filepath.Join(p.Config.OutputDir, outputFilename)
	}

	err = p.Rust.AnnotatePDF(rustbridge.AnnotateRequest{
		InputPDFPath:  localPDF,
		OutputPDFPath: outputPath,
		Language:      p.Config.Language,
		Layouts:       layoutRes.Pages,
		Result:        *analysis,
	})
	if err != nil {
		return nil, err
	}

	var uploadedID, uploadedLink string
	if p.Config.UploadToDrive && sheet.DriveParentID != "" {
		if upRes, err := p.Drive.UploadPDF(outputPath, sheet.DriveParentID, outputFilename); err == nil && upRes != nil {
			uploadedID = upRes["id"]
			uploadedLink = upRes["webViewLink"]
		}
	}

	return &SheetProcessReport{
		InputName:        sheet.Name,
		OutputPath:       outputPath,
		Mode:             mode,
		DetectedKey:      analysis.DetectedKey,
		AccuracyScore:    analysis.AccuracyScore,
		AnnotationsCount: len(analysis.Annotations),
		Summary:          analysis.OverallSummary,
		DriveUploadedID:  uploadedID,
		DriveWebViewLink: uploadedLink,
		TokenUsage:       analysis.TokenUsage,
		AnalysisResult:   analysis,
	}, nil
}

// JobQueueManager manages persistent asynchronous batch jobs across Firestore, GCS, Cloud Tasks, and background goroutines.
type JobQueueManager struct {
	OutputDir       string
	Firestore       *store.FirestoreBackend
	GCS             *store.GCSBackend
	Activity        *store.ActivityManager
	OAuth           *oauth.OAuthManager
	ProjectID       string
	Location        string
	QueueName       string
	ServiceURL      string
	UseCloudTasks   bool
	cancelledJobs   map[string]bool
	mu              sync.Mutex
}

// NewJobQueueManager creates a JobQueueManager.
func NewJobQueueManager(
	outputDir string,
	fs *store.FirestoreBackend,
	gcs *store.GCSBackend,
	activity *store.ActivityManager,
	oauthMgr *oauth.OAuthManager,
) *JobQueueManager {
	if outputDir == "" {
		outputDir = config.DefaultOutputDir()
	}
	_ = os.MkdirAll(outputDir, 0o755)
	if fs == nil {
		fs = store.NewFirestoreBackend("", filepath.Join(outputDir, "_firestore_mirror"))
	}
	if gcs == nil {
		gcs = store.NewGCSBackend("", filepath.Join(outputDir, "_gcs_mirror"))
	}
	if activity == nil {
		activity = store.NewActivityManager(outputDir, fs)
	}

	serviceURL := strings.TrimRight(config.EnvOr("AKKORD_SERVICE_URL", config.DefaultServiceURL), "/")
	useTasksRaw := strings.ToLower(config.EnvOr("AKKORD_USE_CLOUD_TASKS", "false"))
	useCloudTasks := (useTasksRaw == "1" || useTasksRaw == "true" || useTasksRaw == "yes") &&
		os.Getenv("K_SERVICE") != "" && serviceURL != ""

	return &JobQueueManager{
		OutputDir:     outputDir,
		Firestore:     fs,
		GCS:           gcs,
		Activity:      activity,
		OAuth:         oauthMgr,
		ProjectID:     config.EnvOr("AKKORD_GCP_PROJECT", config.EnvOr("GOOGLE_CLOUD_PROJECT", config.DefaultGCPProject)),
		Location:      config.EnvOr("GOOGLE_CLOUD_LOCATION", config.DefaultGCPLocation),
		QueueName:     config.EnvOr("AKKORD_TASKS_QUEUE", config.DefaultTasksQueue),
		ServiceURL:    serviceURL,
		UseCloudTasks: useCloudTasks,
		cancelledJobs: make(map[string]bool),
	}
}

func newUUIDHex(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func nowISO() string {
	loc, err := time.LoadLocation("Europe/Paris")
	if err != nil {
		return time.Now().Format(time.RFC3339)
	}
	return time.Now().In(loc).Format(time.RFC3339)
}

func copyFile(src, dst string) error {
	data, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	_ = os.MkdirAll(filepath.Dir(dst), 0o755)
	return os.WriteFile(dst, data, 0o644)
}

// CreateBatchJob creates a persistent job in `akkord_jobs`, splits items into immediate vs `deferred_next_day` based on the 25/day quota, and dispatches workers.
func (jq *JobQueueManager) CreateBatchJob(
	sourceType string,
	itemsInput []map[string]any,
	model, language string,
	uploadToDrive bool,
	userEmail, oauthSessionID, driveFolderInput string,
) map[string]any {
	jobID := fmt.Sprintf("job_%s_%s", time.Now().Format("20060102_150405"), newUUIDHex(4))
	lang := config.NormalizeLanguage(language)
	if model == "" {
		model = config.DefaultModel
	}

	quota := jq.Activity.GetTodayQuotaStatus()
	remainingToday := 0
	if r, ok := quota["remaining"].(int); ok {
		remainingToday = r
	}
	nextDay := store.NextDayKey("")

	items := make([]map[string]any, 0, len(itemsInput))
	queuedNow := 0
	deferredNextDay := 0

	originalsDir := filepath.Join(jq.OutputDir, "originals")
	_ = os.MkdirAll(originalsDir, 0o755)

	for idx, raw := range itemsInput {
		itemID := fmt.Sprintf("item_%03d_%s", idx+1, newUUIDHex(3))
		name, _ := raw["name"].(string)
		if name == "" {
			name = fmt.Sprintf("sheet_%d.pdf", idx+1)
		}
		driveFileID, _ := raw["drive_file_id"].(string)
		driveParentID, _ := raw["drive_parent_id"].(string)
		webViewLink, _ := raw["web_view_link"].(string)
		localPath, _ := raw["local_path"].(string)
		gcsInputObj, _ := raw["gcs_input_object"].(string)

		if localPath != "" && gcsInputObj == "" {
			if _, err := os.Stat(localPath); err == nil {
				objName := fmt.Sprintf("jobs/%s/inputs/%s", jobID, filepath.Base(name))
				jq.GCS.UploadFile(objName, localPath, "application/pdf")
				gcsInputObj = objName
				_ = copyFile(localPath, filepath.Join(originalsDir, filepath.Base(name)))
			}
		}

		canRunToday := queuedNow < remainingToday
		status := "queued"
		scheduledDate := store.TodayKey()
		if !canRunToday {
			status = "deferred_next_day"
			scheduledDate = nextDay
			deferredNextDay++
		} else {
			queuedNow++
		}

		items = append(items, map[string]any{
			"item_id":            itemID,
			"index":              idx + 1,
			"name":               name,
			"source_type":        sourceType,
			"drive_file_id":      driveFileID,
			"drive_parent_id":    driveParentID,
			"web_view_link":      webViewLink,
			"gcs_input_object":   gcsInputObj,
			"local_path":         localPath,
			"status":             status,
			"scheduled_date":     scheduledDate,
			"mode":               nil,
			"detected_key":       nil,
			"accuracy_score":     nil,
			"annotations_count":  0,
			"summary":            "",
			"output_filename":    nil,
			"output_url":         nil,
			"original_url":       fmt.Sprintf("/api/originals/%s", filepath.Base(name)),
			"gcs_output_object":  nil,
			"drive_uploaded_id":  nil,
			"drive_web_view_link": nil,
			"token_usage":        nil,
			"error":              nil,
			"started_at":         nil,
			"completed_at":       nil,
		})
	}

	jobStatus := "running"
	if queuedNow == 0 && deferredNextDay > 0 {
		jobStatus = "deferred_next_day"
	} else if len(items) == 0 {
		jobStatus = "completed"
	}

	jobDoc := map[string]any{
		"job_id":               jobID,
		"created_at":           nowISO(),
		"updated_at":           nowISO(),
		"source_type":          sourceType,
		"drive_folder":         driveFolderInput,
		"model":                model,
		"language":             lang,
		"upload_to_drive":      uploadToDrive,
		"user_email":           userEmail,
		"oauth_session_id":     oauthSessionID,
		"status":               jobStatus,
		"total_files":          len(items),
		"completed_files":      0,
		"failed_files":         0,
		"skipped_files":        0,
		"deferred_files":       deferredNextDay,
		"current_file":         nil,
		"next_resume_date":     map[bool]any{true: nextDay, false: nil}[deferredNextDay > 0],
		"quota_limit":          jq.Activity.DailyLimit,
		"items":                items,
	}

	jq.Firestore.SetDoc("akkord_jobs", jobID, jobDoc)

	var runnableIDs []string
	for _, it := range items {
		if it["status"] == "queued" {
			if id, ok := it["item_id"].(string); ok {
				runnableIDs = append(runnableIDs, id)
			}
		}
	}
	if len(runnableIDs) > 0 {
		jq.dispatchItems(jobID, runnableIDs)
	}

	return jobDoc
}

func (jq *JobQueueManager) dispatchItems(jobID string, itemIDs []string) {
	if jq.UseCloudTasks {
		allEnqueued := true
		for idx, itemID := range itemIDs {
			if !jq.enqueueCloudTask(jobID, itemID, idx*2) {
				allEnqueued = false
				break
			}
		}
		if allEnqueued {
			return
		}
	}
	go jq.runItemsBackground(jobID, itemIDs)
}

func (jq *JobQueueManager) enqueueCloudTask(jobID, itemID string, delaySeconds int) bool {
	token := store.GlobalADC.GetAccessToken()
	if token == "" || jq.ServiceURL == "" {
		return false
	}
	parent := fmt.Sprintf("projects/%s/locations/%s/queues/%s", jq.ProjectID, jq.Location, jq.QueueName)
	apiURL := fmt.Sprintf("https://cloudtasks.googleapis.com/v2/%s/tasks", parent)
	bodyBytes, _ := json.Marshal(map[string]string{
		"job_id":  jobID,
		"item_id": itemID,
	})
	taskObj := map[string]any{
		"httpRequest": map[string]any{
			"httpMethod": "POST",
			"url":        jq.ServiceURL + "/api/internal/tasks/process-file",
			"headers":    map[string]string{"Content-Type": "application/json"},
			"body":       bodyBytes,
		},
	}
	if delaySeconds > 0 {
		taskObj["scheduleTime"] = time.Now().UTC().Add(time.Duration(delaySeconds) * time.Second).Format(time.RFC3339)
	}
	reqBytes, _ := json.Marshal(map[string]any{"task": taskObj})
	req, err := http.NewRequest("POST", apiURL, bytes.NewReader(reqBytes))
	if err != nil {
		return false
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode >= 200 && resp.StatusCode < 300
}

func (jq *JobQueueManager) runItemsBackground(jobID string, itemIDs []string) {
	for _, itemID := range itemIDs {
		jq.mu.Lock()
		cancelled := jq.cancelledJobs[jobID]
		jq.mu.Unlock()
		if cancelled {
			break
		}
		jq.ProcessJobItem(jobID, itemID)
	}
}

func getItemsSlice(jobDoc map[string]any) []map[string]any {
	raw, ok := jobDoc["items"]
	if !ok {
		return nil
	}
	switch v := raw.(type) {
	case []map[string]any:
		return v
	case []any:
		out := make([]map[string]any, 0, len(v))
		for _, elem := range v {
			if m, ok := elem.(map[string]any); ok {
				out = append(out, m)
			}
		}
		jobDoc["items"] = out
		return out
	default:
		return nil
	}
}

// ProcessJobItem processes a single PDF item within a persistent batch job.
func (jq *JobQueueManager) ProcessJobItem(jobID, itemID string) map[string]any {
	jobDoc := jq.Firestore.GetDoc("akkord_jobs", jobID)
	if jobDoc == nil {
		return map[string]any{"error": fmt.Sprintf("Job '%s' not found", jobID)}
	}
	if jobDoc["status"] == "cancelled" {
		return jobDoc
	}

	items := getItemsSlice(jobDoc)
	var targetItem map[string]any
	for _, it := range items {
		if it["item_id"] == itemID {
			targetItem = it
			break
		}
	}
	if targetItem == nil {
		return map[string]any{"error": fmt.Sprintf("Item '%s' not found in job '%s'", itemID, jobID)}
	}
	if st, _ := targetItem["status"].(string); st == "completed" || st == "skipped" || st == "cancelled" {
		return jobDoc
	}

	allowed, _ := jq.Activity.CheckAndConsumeQuota()
	if !allowed {
		nextDay := store.NextDayKey("")
		targetItem["status"] = "deferred_next_day"
		targetItem["scheduled_date"] = nextDay
		jq.recomputeJobSummary(jobDoc)
		jq.Firestore.SetDoc("akkord_jobs", jobID, jobDoc)
		return jobDoc
	}

	targetItem["status"] = "processing"
	targetItem["started_at"] = nowISO()
	jobDoc["current_file"] = targetItem["name"]
	jobDoc["status"] = "running"
	jobDoc["updated_at"] = nowISO()
	jq.Firestore.SetDoc("akkord_jobs", jobID, jobDoc)

	oauthToken := ""
	if jq.OAuth != nil {
		if sid, _ := jobDoc["oauth_session_id"].(string); sid != "" {
			if sess := jq.OAuth.GetSession(sid); sess != nil {
				oauthToken = sess.AccessToken
			}
		}
		if oauthToken == "" {
			oauthToken = jq.OAuth.GetAdminAccessToken()
		}
	}

	cfg := config.NewDefaultConfig()
	if m, _ := jobDoc["model"].(string); m != "" {
		cfg.Model = m
	}
	if l, _ := jobDoc["language"].(string); l != "" {
		cfg.Language = config.NormalizeLanguage(l)
	}
	cfg.OutputDir = jq.OutputDir
	if up, ok := jobDoc["upload_to_drive"].(bool); ok {
		cfg.UploadToDrive = up
	}

	pipe := NewPipeline(cfg, oauthToken)
	originalsDir := filepath.Join(jq.OutputDir, "originals")
	_ = os.MkdirAll(originalsDir, 0o755)

	tmpDir, err := os.MkdirTemp("", "akkord_job_"+jobID+"_")
	if err != nil {
		targetItem["status"] = "error"
		targetItem["error"] = err.Error()
		targetItem["completed_at"] = nowISO()
		jq.recomputeJobSummary(jobDoc)
		jq.Firestore.SetDoc("akkord_jobs", jobID, jobDoc)
		return jobDoc
	}
	defer os.RemoveAll(tmpDir)

	itemName, _ := targetItem["name"].(string)
	var sheet drive.SheetFile
	if fid, _ := targetItem["drive_file_id"].(string); fid != "" {
		parentID, _ := targetItem["drive_parent_id"].(string)
		webLink, _ := targetItem["web_view_link"].(string)
		sheet = drive.SheetFile{
			ID:            fid,
			Name:          itemName,
			DriveParentID: parentID,
			WebViewLink:   webLink,
		}
		if dlPath, err := pipe.Drive.DownloadPDF(sheet, tmpDir); err == nil {
			sheet.LocalPath = dlPath
			_ = copyFile(dlPath, filepath.Join(originalsDir, filepath.Base(itemName)))
			objName := fmt.Sprintf("jobs/%s/inputs/%s", jobID, filepath.Base(itemName))
			jq.GCS.UploadFile(objName, dlPath, "application/pdf")
			targetItem["gcs_input_object"] = objName
		} else {
			targetItem["status"] = "error"
			targetItem["error"] = err.Error()
			targetItem["completed_at"] = nowISO()
			jq.recomputeJobSummary(jobDoc)
			jq.Firestore.SetDoc("akkord_jobs", jobID, jobDoc)
			return jobDoc
		}
	} else {
		localCandidate, _ := targetItem["local_path"].(string)
		if localCandidate == "" || !fileExists(localCandidate) {
			gcsIn, _ := targetItem["gcs_input_object"].(string)
			dlTarget := filepath.Join(tmpDir, filepath.Base(itemName))
			if gcsIn != "" && jq.GCS.DownloadToFile(gcsIn, dlTarget) {
				localCandidate = dlTarget
			} else {
				origCandidate := filepath.Join(originalsDir, filepath.Base(itemName))
				if fileExists(origCandidate) {
					localCandidate = origCandidate
				}
			}
		}
		if localCandidate == "" || !fileExists(localCandidate) {
			targetItem["status"] = "error"
			targetItem["error"] = fmt.Sprintf("Input PDF '%s' could not be found in GCS or local disk", itemName)
			targetItem["completed_at"] = nowISO()
			jq.recomputeJobSummary(jobDoc)
			jq.Firestore.SetDoc("akkord_jobs", jobID, jobDoc)
			return jobDoc
		}
		sheet = drive.SheetFile{
			ID:        itemName,
			Name:      itemName,
			LocalPath: localCandidate,
		}
	}

	report, err := pipe.ProcessSingleSheet(sheet, tmpDir)
	if err != nil {
		targetItem["status"] = "error"
		targetItem["error"] = err.Error()
		targetItem["completed_at"] = nowISO()
		jq.recomputeJobSummary(jobDoc)
		jq.Firestore.SetDoc("akkord_jobs", jobID, jobDoc)
		return jobDoc
	}

	if report.Mode == "skipped" {
		targetItem["status"] = "skipped"
		targetItem["mode"] = "skipped"
		targetItem["summary"] = report.Summary
		targetItem["completed_at"] = nowISO()
	} else {
		outFilename := filepath.Base(report.OutputPath)
		gcsOutObj := fmt.Sprintf("jobs/%s/outputs/%s", jobID, outFilename)
		if report.OutputPath != "" && fileExists(report.OutputPath) {
			jq.GCS.UploadFile(gcsOutObj, report.OutputPath, "application/pdf")
		}
		var tokMap map[string]any
		if report.TokenUsage != nil {
			raw, _ := json.Marshal(report.TokenUsage)
			_ = json.Unmarshal(raw, &tokMap)
		}

		targetItem["status"] = "completed"
		targetItem["mode"] = report.Mode
		targetItem["detected_key"] = report.DetectedKey
		targetItem["accuracy_score"] = report.AccuracyScore
		targetItem["annotations_count"] = report.AnnotationsCount
		targetItem["summary"] = report.Summary
		targetItem["output_filename"] = outFilename
		targetItem["output_url"] = fmt.Sprintf("/api/outputs/%s?job_id=%s", outFilename, jobID)
		targetItem["gcs_output_object"] = gcsOutObj
		targetItem["drive_uploaded_id"] = report.DriveUploadedID
		targetItem["drive_web_view_link"] = report.DriveWebViewLink
		targetItem["token_usage"] = tokMap
		targetItem["completed_at"] = nowISO()

		userEmail, _ := jobDoc["user_email"].(string)
		jq.Activity.RecordFileProcessed(
			report.InputName,
			report.Mode,
			cfg.Model,
			cfg.Language,
			report.DetectedKey,
			report.AccuracyScore,
			tokMap,
			userEmail,
			jobID,
		)
	}

	jq.recomputeJobSummary(jobDoc)
	jq.Firestore.SetDoc("akkord_jobs", jobID, jobDoc)
	return jobDoc
}

func fileExists(p string) bool {
	if p == "" {
		return false
	}
	st, err := os.Stat(p)
	return err == nil && !st.IsDir()
}

func (jq *JobQueueManager) recomputeJobSummary(jobDoc map[string]any) {
	items := getItemsSlice(jobDoc)
	completed := 0
	failed := 0
	skipped := 0
	deferred := 0
	runningOrQueued := 0
	var currentFile any
	var nextDates []string

	for _, it := range items {
		st, _ := it["status"].(string)
		switch st {
		case "completed":
			completed++
		case "error":
			failed++
		case "skipped":
			skipped++
		case "deferred_next_day":
			deferred++
			if sd, _ := it["scheduled_date"].(string); sd != "" {
				nextDates = append(nextDates, sd)
			}
		case "processing":
			runningOrQueued++
			currentFile = it["name"]
		case "queued":
			runningOrQueued++
		}
	}

	jobDoc["completed_files"] = completed
	jobDoc["failed_files"] = failed
	jobDoc["skipped_files"] = skipped
	jobDoc["deferred_files"] = deferred
	jobDoc["current_file"] = currentFile
	if len(nextDates) > 0 {
		sort.Strings(nextDates)
		jobDoc["next_resume_date"] = nextDates[0]
	} else {
		jobDoc["next_resume_date"] = nil
	}
	jobDoc["updated_at"] = nowISO()

	if jobDoc["status"] == "cancelled" {
		return
	}
	if runningOrQueued > 0 {
		jobDoc["status"] = "running"
	} else if deferred > 0 {
		jobDoc["status"] = "deferred_next_day"
	} else if failed > 0 && completed == 0 {
		jobDoc["status"] = "error"
	} else {
		jobDoc["status"] = "completed"
	}
}

// GetJob returns a job document by ID.
func (jq *JobQueueManager) GetJob(jobID string) map[string]any {
	return jq.Firestore.GetDoc("akkord_jobs", jobID)
}

// ListJobs lists recent batch jobs, optionally filtered by user email.
func (jq *JobQueueManager) ListJobs(limit int, userEmail string) []map[string]any {
	if limit <= 0 {
		limit = 20
	}
	docs := jq.Firestore.ListDocs("akkord_jobs", limit*2)
	if userEmail != "" {
		var filtered []map[string]any
		for _, d := range docs {
			em, _ := d["user_email"].(string)
			if em == "" || strings.EqualFold(em, userEmail) {
				filtered = append(filtered, d)
			}
		}
		docs = filtered
	}
	sort.Slice(docs, func(i, j int) bool {
		ci, _ := docs[i]["created_at"].(string)
		cj, _ := docs[j]["created_at"].(string)
		return ci > cj
	})
	if len(docs) > limit {
		docs = docs[:limit]
	}
	return docs
}

// GetRecentHistory returns a flat list of recently processed sheet items across all jobs.
func (jq *JobQueueManager) GetRecentHistory(limit int) []map[string]any {
	if limit <= 0 {
		limit = 30
	}
	jobsList := jq.ListJobs(25, "")
	var history []map[string]any
	for _, job := range jobsList {
		jobID, _ := job["job_id"].(string)
		lang, _ := job["language"].(string)
		model, _ := job["model"].(string)
		createdAt, _ := job["created_at"].(string)
		for _, it := range getItemsSlice(job) {
			st, _ := it["status"].(string)
			if st == "completed" || st == "deferred_next_day" || st == "error" || st == "processing" {
				ts, _ := it["completed_at"].(string)
				if ts == "" {
					ts, _ = it["started_at"].(string)
				}
				if ts == "" {
					ts = createdAt
				}
				history = append(history, map[string]any{
					"job_id":             jobID,
					"item_id":            it["item_id"],
					"input_name":         it["name"],
					"status":             st,
					"scheduled_date":     it["scheduled_date"],
					"mode":               it["mode"],
					"detected_key":       it["detected_key"],
					"accuracy_score":     it["accuracy_score"],
					"annotations_count":  it["annotations_count"],
					"summary":            it["summary"],
					"output_filename":    it["output_filename"],
					"output_url":         it["output_url"],
					"original_url":       it["original_url"],
					"drive_web_view_link": it["drive_web_view_link"],
					"token_usage":        it["token_usage"],
					"error":              it["error"],
					"timestamp":          ts,
					"language":           lang,
					"model":              model,
				})
			}
		}
	}
	sort.Slice(history, func(i, j int) bool {
		ti, _ := history[i]["timestamp"].(string)
		tj, _ := history[j]["timestamp"].(string)
		return ti > tj
	})
	if len(history) > limit {
		history = history[:limit]
	}
	return history
}

// CancelJob cancels all queued or deferred items in a job.
func (jq *JobQueueManager) CancelJob(jobID string) map[string]any {
	jq.mu.Lock()
	jq.cancelledJobs[jobID] = true
	jq.mu.Unlock()

	jobDoc := jq.Firestore.GetDoc("akkord_jobs", jobID)
	if jobDoc == nil {
		return map[string]any{"error": fmt.Sprintf("Job '%s' not found", jobID)}
	}
	for _, it := range getItemsSlice(jobDoc) {
		st, _ := it["status"].(string)
		if st == "queued" || st == "deferred_next_day" {
			it["status"] = "cancelled"
		}
	}
	jobDoc["status"] = "cancelled"
	jobDoc["current_file"] = nil
	jobDoc["updated_at"] = nowISO()
	jq.Firestore.SetDoc("akkord_jobs", jobID, jobDoc)
	return jobDoc
}

// ResumeDeferredJobs resumes `deferred_next_day` items up to today's remaining quota.
func (jq *JobQueueManager) ResumeDeferredJobs() map[string]any {
	quota := jq.Activity.GetTodayQuotaStatus()
	remaining, _ := quota["remaining"].(int)
	if remaining <= 0 {
		return map[string]any{
			"status":    "quota_full",
			"resumed":   0,
			"remaining": 0,
		}
	}

	docs := jq.Firestore.ListDocs("akkord_jobs", 50)
	sort.Slice(docs, func(i, j int) bool {
		ci, _ := docs[i]["created_at"].(string)
		cj, _ := docs[j]["created_at"].(string)
		return ci < cj
	})

	resumedCount := 0
	var resumedJobs []string
	tKey := store.TodayKey()

	for _, jobDoc := range docs {
		if remaining <= 0 {
			break
		}
		st, _ := jobDoc["status"].(string)
		if st != "deferred_next_day" && st != "running" {
			continue
		}
		jobID, _ := jobDoc["job_id"].(string)
		var runnableIDs []string
		for _, it := range getItemsSlice(jobDoc) {
			if remaining <= 0 {
				break
			}
			if it["status"] == "deferred_next_day" {
				it["status"] = "queued"
				it["scheduled_date"] = tKey
				if id, ok := it["item_id"].(string); ok {
					runnableIDs = append(runnableIDs, id)
				}
				remaining--
				resumedCount++
			}
		}
		if len(runnableIDs) > 0 {
			jq.recomputeJobSummary(jobDoc)
			jq.Firestore.SetDoc("akkord_jobs", jobID, jobDoc)
			resumedJobs = append(resumedJobs, jobID)
			jq.dispatchItems(jobID, runnableIDs)
		}
	}

	return map[string]any{
		"status":       "ok",
		"resumed_files": resumedCount,
		"resumed_jobs": resumedJobs,
		"date":         tKey,
	}
}

// BuildJobZipBytes creates an in-memory ZIP archive containing all completed PDFs for a job.
func (jq *JobQueueManager) BuildJobZipBytes(jobID string) ([]byte, string) {
	jobDoc := jq.GetJob(jobID)
	if jobDoc == nil {
		return nil, ""
	}
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	added := 0

	for _, it := range getItemsSlice(jobDoc) {
		if it["status"] != "completed" {
			continue
		}
		outFname, _ := it["output_filename"].(string)
		if outFname == "" {
			continue
		}
		var pdfBytes []byte
		localPath := filepath.Join(jq.OutputDir, outFname)
		if data, err := os.ReadFile(localPath); err == nil {
			pdfBytes = data
		} else if gcsObj, _ := it["gcs_output_object"].(string); gcsObj != "" {
			pdfBytes = jq.GCS.DownloadBytes(gcsObj)
		}
		if len(pdfBytes) > 0 {
			if w, err := zw.Create(outFname); err == nil {
				_, _ = w.Write(pdfBytes)
				added++
			}
		}
	}
	_ = zw.Close()
	if added == 0 {
		return nil, ""
	}
	return buf.Bytes(), fmt.Sprintf("akkord-%s.zip", jobID)
}
