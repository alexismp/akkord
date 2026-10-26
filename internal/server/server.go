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

// Package server implements the Akkord HTTP web server and REST API.
package server

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/alexismp/akkord/internal/config"
	"github.com/alexismp/akkord/internal/drive"
	"github.com/alexismp/akkord/internal/jobs"
	"github.com/alexismp/akkord/internal/oauth"
	"github.com/alexismp/akkord/internal/store"
)

// Server holds the shared state and handlers for the Akkord HTTP application.
type Server struct {
	OutputDir    string
	OriginalsDir string
	StaticDir    string
	Firestore    *store.FirestoreBackend
	GCS          *store.GCSBackend
	Activity     *store.ActivityManager
	OAuth        *oauth.OAuthManager
	JobQueue     *jobs.JobQueueManager
	cancelMu     sync.Mutex
	cancelActive bool
}

// NewServer creates and initializes a new Server instance.
func NewServer(outputDir, staticDir string) *Server {
	if outputDir == "" {
		outputDir = config.DefaultOutputDir()
	}
	_ = os.MkdirAll(outputDir, 0o755)
	originalsDir := filepath.Join(outputDir, "originals")
	_ = os.MkdirAll(originalsDir, 0o755)

	if staticDir == "" {
		candidates := []string{
			"akkord/static",
			"../akkord/static",
			"../../akkord/static",
			"/app/akkord/static",
		}
		for _, c := range candidates {
			if st, err := os.Stat(c); err == nil && st.IsDir() {
				if abs, err := filepath.Abs(c); err == nil {
					staticDir = abs
				} else {
					staticDir = c
				}
				break
			}
		}
	}

	fs := store.NewFirestoreBackend("", filepath.Join(outputDir, "_firestore_mirror"))
	gcs := store.NewGCSBackend("", filepath.Join(outputDir, "_gcs_mirror"))
	activity := store.NewActivityManager(outputDir, fs)
	oauthMgr := oauth.NewOAuthManager(outputDir, fs)
	jq := jobs.NewJobQueueManager(outputDir, fs, gcs, activity, oauthMgr)

	return &Server{
		OutputDir:    outputDir,
		OriginalsDir: originalsDir,
		StaticDir:    staticDir,
		Firestore:    fs,
		GCS:          gcs,
		Activity:     activity,
		OAuth:        oauthMgr,
		JobQueue:     jq,
	}
}

// Handler returns the root http.Handler routing all endpoints.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("/", s.handleIndexOrStatic)
	mux.HandleFunc("/api/config", s.handleConfig)
	mux.HandleFunc("/api/auth/status", s.handleAuthStatus)
	mux.HandleFunc("/auth/login", s.handleAuthLogin)
	mux.HandleFunc("/auth/callback", s.handleAuthCallback)
	mux.HandleFunc("/api/auth/logout", s.handleAuthLogout)
	mux.HandleFunc("/api/cancel", s.handleCancel)
	mux.HandleFunc("/api/jobs/drive", s.handleCreateDriveJob)
	mux.HandleFunc("/api/jobs/upload", s.handleCreateUploadJob)
	mux.HandleFunc("/api/jobs", s.handleListJobs)
	mux.HandleFunc("/api/jobs/", s.handleJobSubroutes)
	mux.HandleFunc("/api/internal/tasks/process-file", s.handleTaskProcessFile)
	mux.HandleFunc("/api/internal/tasks/resume-deferred", s.handleTaskResumeDeferred)
	mux.HandleFunc("/api/admin/usage", s.handleAdminUsage)
	mux.HandleFunc("/api/admin/reset-quota", s.handleAdminResetQuota)
	mux.HandleFunc("/api/daily-report/preview", s.handleDailyReportPreview)
	mux.HandleFunc("/api/daily-report/send", s.handleDailyReportSend)
	mux.HandleFunc("/api/drive/browse", s.handleDriveBrowse)
	mux.HandleFunc("/api/scan-folder", s.handleScanFolder)
	mux.HandleFunc("/api/process", s.handleProcessSync)
	mux.HandleFunc("/api/process-stream", s.handleProcessStream)
	mux.HandleFunc("/api/process-upload", s.handleProcessUploadSync)
	mux.HandleFunc("/api/process-upload-stream", s.handleProcessUploadStream)
	mux.HandleFunc("/api/originals/", s.handleGetOriginal)
	mux.HandleFunc("/api/outputs/", s.handleGetOutput)

	return mux
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]any{"detail": detail})
}

func requestBaseURL(r *http.Request) string {
	proto := r.Header.Get("X-Forwarded-Proto")
	if proto == "" {
		if r.TLS != nil {
			proto = "https"
		} else {
			proto = "http"
		}
	}
	host := r.Header.Get("X-Forwarded-Host")
	if host == "" {
		host = r.Host
	}
	if host == "" {
		host = "localhost:8080"
	}
	return fmt.Sprintf("%s://%s", proto, host)
}

func (s *Server) currentUser(r *http.Request) *oauth.UserSession {
	c, err := r.Cookie(config.SessionCookieName)
	if err != nil || c.Value == "" {
		return nil
	}
	return s.OAuth.GetSession(c.Value)
}

func (s *Server) resolveOwnerID(w http.ResponseWriter, r *http.Request) (*oauth.UserSession, string) {
	user := s.currentUser(r)
	if user != nil && strings.TrimSpace(user.Email) != "" {
		return user, "user:" + strings.ToLower(strings.TrimSpace(user.Email))
	}
	if c, err := r.Cookie("akkord_anon"); err == nil && strings.TrimSpace(c.Value) != "" {
		val := strings.TrimSpace(c.Value)
		if strings.HasPrefix(val, "anon:") {
			return nil, val
		}
		return nil, "anon:" + val
	}
	anonID := "anon_session_default"
	http.SetCookie(w, &http.Cookie{
		Name:     "akkord_anon",
		Value:    anonID,
		Path:     "/",
		MaxAge:   30 * 24 * 3600,
		HttpOnly: true,
		SameSite: http.SameSiteLaxMode,
	})
	return nil, "anon:" + anonID
}

func (s *Server) handleIndexOrStatic(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path == "/" {
		indexPath := filepath.Join(s.StaticDir, "index.html")
		http.ServeFile(w, r, indexPath)
		return
	}
	if strings.HasPrefix(r.URL.Path, "/static/") {
		rel := strings.TrimPrefix(r.URL.Path, "/static/")
		rel = filepath.Clean(rel)
		if strings.Contains(rel, "..") {
			http.NotFound(w, r)
			return
		}
		http.ServeFile(w, r, filepath.Join(s.StaticDir, rel))
		return
	}
	http.NotFound(w, r)
}

func (s *Server) handleConfig(w http.ResponseWriter, r *http.Request) {
	user, ownerID := s.resolveOwnerID(w, r)
	var userDict any = map[string]any{"authenticated": false}
	if user != nil {
		userDict = user.ToPublicDict()
	}
	activeJobs := s.JobQueue.ListJobs(10, ownerID)
	var runningJob any
	if len(activeJobs) > 0 {
		for _, j := range activeJobs {
			st, _ := j["status"].(string)
			if st == "running" || st == "deferred_next_day" {
				runningJob = j
				break
			}
		}
		if runningJob == nil {
			runningJob = activeJobs[0]
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"default_model":      config.DefaultModel,
		"available_models":   config.AvailableModels,
		"default_language":   config.DefaultLanguage,
		"languages":          []string{"fr", "en"},
		"default_project":    config.EnvOr("AKKORD_GCP_PROJECT", config.EnvOr("GOOGLE_CLOUD_PROJECT", config.DefaultGCPProject)),
		"default_location":   config.EnvOr("GOOGLE_CLOUD_LOCATION", config.DefaultGCPLocation),
		"oauth_configured":   s.OAuth.IsConfigured(),
		"user":               userDict,
		"quota":              s.Activity.GetTodayQuotaStatus(),
		"daily_report_hour":  fmt.Sprintf("%02d:00", s.Activity.ReportHourLocal),
		"daily_report_email": s.Activity.ReportEmail,
		"active_job":         runningJob,
		"recent_history":     s.JobQueue.GetRecentHistory(25, ownerID),
		"runtime_engine":     "go-rust-polyglot",
	})
}

func (s *Server) handleAuthStatus(w http.ResponseWriter, r *http.Request) {
	user := s.currentUser(r)
	if user != nil {
		resp := user.ToPublicDict()
		resp["oauth_configured"] = s.OAuth.IsConfigured()
		writeJSON(w, http.StatusOK, resp)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"authenticated":    false,
		"oauth_configured": s.OAuth.IsConfigured(),
	})
}

func (s *Server) handleAuthLogin(w http.ResponseWriter, r *http.Request) {
	if !s.OAuth.IsConfigured() {
		writeError(w, http.StatusServiceUnavailable, "Google OAuth 2.0 client credentials are not configured on this server.")
		return
	}
	authURL, _ := s.OAuth.BuildAuthorizationURL(requestBaseURL(r))
	http.Redirect(w, r, authURL, http.StatusFound)
}

func (s *Server) handleAuthCallback(w http.ResponseWriter, r *http.Request) {
	if errMsg := r.URL.Query().Get("error"); errMsg != "" {
		http.Redirect(w, r, "/?auth_error="+errMsg, http.StatusFound)
		return
	}
	code := r.URL.Query().Get("code")
	state := r.URL.Query().Get("state")
	if code == "" {
		http.Redirect(w, r, "/?auth_error=missing_code", http.StatusFound)
		return
	}
	sess, err := s.OAuth.ExchangeCodeForSession(code, state, requestBaseURL(r))
	if err != nil {
		http.Redirect(w, r, "/?auth_error=token_exchange_failed", http.StatusFound)
		return
	}
	cookieTok := s.OAuth.EncodeSessionCookie(sess)
	isHTTPS := strings.HasPrefix(requestBaseURL(r), "https://")
	http.SetCookie(w, &http.Cookie{
		Name:     config.SessionCookieName,
		Value:    cookieTok,
		Path:     "/",
		MaxAge:   30 * 24 * 3600,
		HttpOnly: true,
		Secure:   isHTTPS,
		SameSite: http.SameSiteLaxMode,
	})
	http.Redirect(w, r, "/?auth=success", http.StatusFound)
}

func (s *Server) handleAuthLogout(w http.ResponseWriter, r *http.Request) {
	if c, err := r.Cookie(config.SessionCookieName); err == nil && c.Value != "" {
		s.OAuth.DeleteSession(c.Value)
	}
	http.SetCookie(w, &http.Cookie{
		Name:   config.SessionCookieName,
		Value:  "",
		Path:   "/",
		MaxAge: -1,
	})
	writeJSON(w, http.StatusOK, map[string]any{"status": "logged_out"})
}

func (s *Server) handleCancel(w http.ResponseWriter, r *http.Request) {
	s.cancelMu.Lock()
	s.cancelActive = true
	s.cancelMu.Unlock()
	var body map[string]any
	_ = json.NewDecoder(r.Body).Decode(&body)
	if jobID, ok := body["job_id"].(string); ok && jobID != "" {
		s.JobQueue.CancelJob(jobID)
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"status":  "cancelling",
		"message": "Cancellation requested.",
	})
}

func (s *Server) handleCreateDriveJob(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "POST required")
		return
	}
	var req struct {
		DriveFolder   string   `json:"drive_folder"`
		Model         string   `json:"model"`
		Language      string   `json:"language"`
		UploadToDrive bool     `json:"upload_to_drive"`
		SelectedFiles []string `json:"selected_files"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid JSON payload")
		return
	}
	folder := strings.TrimSpace(req.DriveFolder)
	if folder == "" {
		writeError(w, http.StatusBadRequest, "drive_folder cannot be empty")
		return
	}
	user, ownerID := s.resolveOwnerID(w, r)
	oauthTok := ""
	userEmail := ""
	sessID := ownerID
	if user != nil {
		oauthTok = user.AccessToken
		userEmail = user.Email
		sessID = user.SessionID
	}

	conn := drive.NewDriveConnector("", oauthTok)
	sheets, err := conn.ListPDFs(folder)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if len(req.SelectedFiles) > 0 {
		sel := make(map[string]bool, len(req.SelectedFiles))
		for _, sf := range req.SelectedFiles {
			sel[sf] = true
		}
		var filtered []drive.SheetFile
		for _, sh := range sheets {
			if sel[sh.ID] || sel[sh.Name] {
				filtered = append(filtered, sh)
			}
		}
		sheets = filtered
	}
	if len(sheets) == 0 {
		writeError(w, http.StatusNotFound, "No music sheet PDFs found in the specified folder.")
		return
	}

	itemsInput := make([]map[string]any, 0, len(sheets))
	for _, sh := range sheets {
		itemsInput = append(itemsInput, map[string]any{
			"name":            sh.Name,
			"drive_file_id":   sh.ID,
			"drive_parent_id": sh.DriveParentID,
			"web_view_link":   sh.WebViewLink,
			"local_path":      sh.LocalPath,
		})
	}
	model := req.Model
	if model == "" {
		model = config.DefaultModel
	}
	lang := config.NormalizeLanguage(req.Language)

	jobDoc := s.JobQueue.CreateBatchJob("drive", itemsInput, model, lang, req.UploadToDrive, userEmail, sessID, folder)
	writeJSON(w, http.StatusOK, map[string]any{
		"job":   jobDoc,
		"quota": s.Activity.GetTodayQuotaStatus(),
	})
}

func (s *Server) handleCreateUploadJob(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "POST required")
		return
	}
	if err := r.ParseMultipartForm(64 << 20); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid multipart upload")
		return
	}
	model := r.FormValue("model")
	if model == "" {
		model = config.DefaultModel
	}
	lang := config.NormalizeLanguage(r.FormValue("language"))
	user, ownerID := s.resolveOwnerID(w, r)
	userEmail := ""
	sessID := ownerID
	if user != nil {
		userEmail = user.Email
		sessID = user.SessionID
	}

	files := r.MultipartForm.File["files"]
	var itemsInput []map[string]any
	for _, fh := range files {
		fname := filepath.Base(fh.Filename)
		if !strings.HasSuffix(strings.ToLower(fname), ".pdf") || drive.IsGeneratedOutput(fname) {
			continue
		}
		src, err := fh.Open()
		if err != nil {
			continue
		}
		data, err := io.ReadAll(src)
		src.Close()
		if err != nil {
			continue
		}
		origPath := filepath.Join(s.OriginalsDir, fname)
		_ = os.WriteFile(origPath, data, 0o644)
		itemsInput = append(itemsInput, map[string]any{
			"name":       fname,
			"local_path": origPath,
		})
	}
	if len(itemsInput) == 0 {
		writeError(w, http.StatusBadRequest, "No valid PDF files uploaded.")
		return
	}
	jobDoc := s.JobQueue.CreateBatchJob("upload", itemsInput, model, lang, false, userEmail, sessID, "")
	writeJSON(w, http.StatusOK, map[string]any{
		"job":   jobDoc,
		"quota": s.Activity.GetTodayQuotaStatus(),
	})
}

func (s *Server) handleListJobs(w http.ResponseWriter, r *http.Request) {
	_, ownerID := s.resolveOwnerID(w, r)
	writeJSON(w, http.StatusOK, map[string]any{
		"jobs":           s.JobQueue.ListJobs(20, ownerID),
		"recent_history": s.JobQueue.GetRecentHistory(30, ownerID),
		"quota":          s.Activity.GetTodayQuotaStatusForOwner(ownerID),
	})
}

func (s *Server) handleJobSubroutes(w http.ResponseWriter, r *http.Request) {
	_, ownerID := s.resolveOwnerID(w, r)
	trimmed := strings.TrimPrefix(r.URL.Path, "/api/jobs/")
	parts := strings.Split(strings.Trim(trimmed, "/"), "/")
	if len(parts) == 0 || parts[0] == "" {
		http.NotFound(w, r)
		return
	}
	jobID := parts[0]
	jobDoc := s.JobQueue.GetJob(jobID)
	if jobDoc == nil {
		writeError(w, http.StatusNotFound, fmt.Sprintf("Job '%s' not found.", jobID))
		return
	}
	if !jobs.JobBelongsToOwner(jobDoc, ownerID) {
		writeError(w, http.StatusForbidden, "Accès refusé : ce traitement appartient à un autre utilisateur.")
		return
	}
	if len(parts) == 1 {
		writeJSON(w, http.StatusOK, map[string]any{
			"job":   jobDoc,
			"quota": s.Activity.GetTodayQuotaStatus(),
		})
		return
	}
	action := parts[1]
	switch action {
	case "cancel":
		cancelledDoc := s.JobQueue.CancelJob(jobID)
		if errMsg, ok := cancelledDoc["error"].(string); ok && errMsg != "" {
			writeError(w, http.StatusNotFound, errMsg)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"job": cancelledDoc})
	case "download-zip":
		zipBytes, zipName := s.JobQueue.BuildJobZipBytes(jobID)
		if len(zipBytes) == 0 {
			writeError(w, http.StatusNotFound, "No completed PDFs available for ZIP download in this job.")
			return
		}
		w.Header().Set("Content-Type", "application/zip")
		w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, zipName))
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(zipBytes)
	default:
		http.NotFound(w, r)
	}
}

func (s *Server) handleTaskProcessFile(w http.ResponseWriter, r *http.Request) {
	var body struct {
		JobID  string `json:"job_id"`
		ItemID string `json:"item_id"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	if body.JobID == "" || body.ItemID == "" {
		writeError(w, http.StatusBadRequest, "job_id and item_id are required")
		return
	}
	jobDoc := s.JobQueue.ProcessJobItem(body.JobID, body.ItemID)
	writeJSON(w, http.StatusOK, map[string]any{
		"status":  "processed",
		"job_id":  body.JobID,
		"item_id": body.ItemID,
		"job":     jobDoc,
	})
}

func (s *Server) handleTaskResumeDeferred(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, s.JobQueue.ResumeDeferredJobs())
}

func (s *Server) handleAdminUsage(w http.ResponseWriter, r *http.Request) {
	user := s.currentUser(r)
	summary := s.Activity.GetUsageSummary(14)
	isAdmin := user != nil && user.IsAdmin()
	summary["is_admin"] = isAdmin
	if user != nil {
		summary["viewer_email"] = user.Email
	}
	summary["recent_jobs"] = s.JobQueue.ListJobs(15, "")
	writeJSON(w, http.StatusOK, summary)
}

func (s *Server) handleAdminResetQuota(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "POST required")
		return
	}
	user := s.currentUser(r)
	if s.OAuth.IsConfigured() && (user == nil || !user.IsAdmin()) {
		writeError(w, http.StatusForbidden, "Seul l'administrateur (alexis.mp@gmail.com) peut remettre le quota journalier à zéro.")
		return
	}
	var body struct {
		Date           string `json:"date"`
		ResumeDeferred *bool  `json:"resume_deferred"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	resetBy := "admin"
	if user != nil && user.Email != "" {
		resetBy = user.Email
	}
	newQuota := s.Activity.ResetDailyQuota(body.Date, resetBy)
	resumeFlag := true
	if body.ResumeDeferred != nil {
		resumeFlag = *body.ResumeDeferred
	}
	var resumeResult any
	if resumeFlag {
		resumeResult = s.JobQueue.ResumeDeferredJobs()
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"status":  "quota_reset",
		"quota":   newQuota,
		"resumed": resumeResult,
		"usage":   s.Activity.GetUsageSummary(14),
	})
}

func (s *Server) handleDailyReportPreview(w http.ResponseWriter, r *http.Request) {
	dateKey := r.URL.Query().Get("date")
	subj, txt, htm := s.Activity.BuildDailyReportEmail(dateKey)
	d := dateKey
	if d == "" {
		d = store.TodayKey()
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"date":         d,
		"recipient":    s.Activity.ReportEmail,
		"subject":      subj,
		"text_preview": txt,
		"html_preview": htm,
	})
}

func (s *Server) handleDailyReportSend(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Date  string `json:"date"`
		Force bool   `json:"force"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	user := s.currentUser(r)
	oauthTok := ""
	if user != nil {
		oauthTok = user.AccessToken
	}
	if oauthTok == "" {
		oauthTok = s.OAuth.GetAdminAccessToken()
	}
	res := s.Activity.SendDailyReportEmail(body.Date, body.Force, oauthTok)
	writeJSON(w, http.StatusOK, res)
}

func (s *Server) handleDriveBrowse(w http.ResponseWriter, r *http.Request) {
	folderID := r.URL.Query().Get("folder_id")
	if folderID == "" {
		folderID = "root"
	}
	query := r.URL.Query().Get("query")
	user := s.currentUser(r)
	oauthTok := ""
	if user != nil {
		oauthTok = user.AccessToken
	}
	conn := drive.NewDriveConnector("", oauthTok)
	res, err := conn.BrowseDriveFolder(folderID, query)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, res)
}

func (s *Server) handleScanFolder(w http.ResponseWriter, r *http.Request) {
	var req struct {
		DriveFolder string `json:"drive_folder"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || strings.TrimSpace(req.DriveFolder) == "" {
		writeError(w, http.StatusBadRequest, "drive_folder cannot be empty")
		return
	}
	user := s.currentUser(r)
	oauthTok := ""
	if user != nil {
		oauthTok = user.AccessToken
	}
	conn := drive.NewDriveConnector("", oauthTok)
	files, err := conn.ListPDFs(strings.TrimSpace(req.DriveFolder))
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	fileList := make([]map[string]any, 0, len(files))
	for _, f := range files {
		fileList = append(fileList, map[string]any{
			"id":            f.ID,
			"name":          f.Name,
			"local_path":    f.LocalPath,
			"web_view_link": f.WebViewLink,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"folder": req.DriveFolder,
		"count":  len(fileList),
		"files":  fileList,
		"quota":  s.Activity.GetTodayQuotaStatus(),
	})
}

func (s *Server) handleProcessSync(w http.ResponseWriter, r *http.Request) {
	var req struct {
		DriveFolder   string   `json:"drive_folder"`
		Model         string   `json:"model"`
		Language      string   `json:"language"`
		UploadToDrive bool     `json:"upload_to_drive"`
		SelectedFiles []string `json:"selected_files"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || strings.TrimSpace(req.DriveFolder) == "" {
		writeError(w, http.StatusBadRequest, "drive_folder cannot be empty")
		return
	}
	allowed, quotaStatus := s.Activity.CheckAndConsumeQuota()
	if !allowed {
		writeError(w, http.StatusTooManyRequests, fmt.Sprintf("Daily limit of %v music sheets reached.", quotaStatus["limit"]))
		return
	}
	user := s.currentUser(r)
	oauthTok := ""
	userEmail := ""
	if user != nil {
		oauthTok = user.AccessToken
		userEmail = user.Email
	}
	cfg := config.NewDefaultConfig()
	if req.Model != "" {
		cfg.Model = req.Model
	}
	cfg.Language = config.NormalizeLanguage(req.Language)
	cfg.OutputDir = s.OutputDir
	cfg.UploadToDrive = req.UploadToDrive

	pipe := jobs.NewPipeline(cfg, oauthTok)
	sheets, err := pipe.Drive.ListPDFs(req.DriveFolder)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if len(req.SelectedFiles) > 0 {
		sel := make(map[string]bool)
		for _, sf := range req.SelectedFiles {
			sel[sf] = true
		}
		var filtered []drive.SheetFile
		for _, sh := range sheets {
			if sel[sh.ID] || sel[sh.Name] {
				filtered = append(filtered, sh)
			}
		}
		sheets = filtered
	}

	tmpDir, _ := os.MkdirTemp("", "akkord_sync_")
	defer os.RemoveAll(tmpDir)

	var results []map[string]any
	for _, sh := range sheets {
		allowed, _ := s.Activity.CheckAndConsumeQuota()
		if !allowed {
			break
		}
		rep, err := pipe.ProcessSingleSheet(sh, tmpDir)
		if err != nil {
			continue
		}
		var outFname, outURL any
		if rep.OutputPath != "" {
			fname := filepath.Base(rep.OutputPath)
			outFname = fname
			outURL = "/api/outputs/" + fname
		}
		var tokMap map[string]any
		if rep.TokenUsage != nil {
			raw, _ := json.Marshal(rep.TokenUsage)
			_ = json.Unmarshal(raw, &tokMap)
		}
		if rep.Mode != "skipped" {
			s.Activity.RecordFileProcessed(rep.InputName, rep.Mode, cfg.Model, cfg.Language, rep.DetectedKey, rep.AccuracyScore, tokMap, userEmail, "")
		}
		results = append(results, map[string]any{
			"input_name":          rep.InputName,
			"mode":                rep.Mode,
			"detected_key":        rep.DetectedKey,
			"accuracy_score":      rep.AccuracyScore,
			"annotations_count":   rep.AnnotationsCount,
			"summary":             rep.Summary,
			"output_filename":     outFname,
			"output_url":          outURL,
			"original_url":        "/api/originals/" + filepath.Base(sh.Name),
			"drive_uploaded_id":   rep.DriveUploadedID,
			"drive_web_view_link": rep.DriveWebViewLink,
			"token_usage":         tokMap,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"total":   len(results),
		"model":   cfg.Model,
		"results": results,
		"quota":   s.Activity.GetTodayQuotaStatus(),
	})
}

func (s *Server) handleProcessStream(w http.ResponseWriter, r *http.Request) {
	// Stream NDJSON for single/folder processing
	s.handleCreateDriveJob(w, r)
}

func (s *Server) handleProcessUploadSync(w http.ResponseWriter, r *http.Request) {
	s.handleCreateUploadJob(w, r)
}

func (s *Server) handleProcessUploadStream(w http.ResponseWriter, r *http.Request) {
	s.handleCreateUploadJob(w, r)
}

func (s *Server) handleGetOriginal(w http.ResponseWriter, r *http.Request) {
	fname := filepath.Base(strings.TrimPrefix(r.URL.Path, "/api/originals/"))
	candidate := filepath.Join(s.OriginalsDir, fname)
	if _, err := os.Stat(candidate); err == nil {
		w.Header().Set("Content-Type", "application/pdf")
		http.ServeFile(w, r, candidate)
		return
	}
	if st, err := os.Stat("samples"); err == nil && st.IsDir() {
		samplePath := filepath.Join("samples", fname)
		if _, err := os.Stat(samplePath); err == nil {
			w.Header().Set("Content-Type", "application/pdf")
			http.ServeFile(w, r, samplePath)
			return
		}
	}
	writeError(w, http.StatusNotFound, fmt.Sprintf("Original file '%s' not found.", fname))
}

func (s *Server) handleGetOutput(w http.ResponseWriter, r *http.Request) {
	fname := filepath.Base(strings.TrimPrefix(r.URL.Path, "/api/outputs/"))
	candidate := filepath.Join(s.OutputDir, fname)
	if _, err := os.Stat(candidate); err != nil {
		jobID := r.URL.Query().Get("job_id")
		if jobID != "" {
			gcsObj := fmt.Sprintf("jobs/%s/outputs/%s", jobID, fname)
			s.GCS.DownloadToFile(gcsObj, candidate)
		}
	}
	if _, err := os.Stat(candidate); err != nil {
		writeError(w, http.StatusNotFound, fmt.Sprintf("Output file '%s' not found.", fname))
		return
	}
	w.Header().Set("Content-Type", "application/pdf")
	if r.URL.Query().Get("download") == "1" {
		w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, fname))
	}
	http.ServeFile(w, r, candidate)
}
