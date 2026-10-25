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

// Package store provides Cloud Firestore REST persistence, Cloud Storage (GCS) artifact storage,
// and daily activity/quota tracking (25 PDFs/day in Europe/Paris + 18:00 daily email digest).
package store

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"html"
	"io"
	"math"
	"net/http"
	"net/smtp"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/alexismp/akkord/internal/config"
)

// ADCTokenProvider caches Google Cloud Application Default Credentials access tokens.
type ADCTokenProvider struct {
	mu          sync.Mutex
	accessToken string
	expiresAt   time.Time
}

var GlobalADC = &ADCTokenProvider{}

// GetAccessToken retrieves a valid GCP bearer token from the GCE/Cloud Run metadata server or gcloud ADC.
func (p *ADCTokenProvider) GetAccessToken() string {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.accessToken != "" && time.Now().Before(p.expiresAt) {
		return p.accessToken
	}

	if envTok := strings.TrimSpace(os.Getenv("GOOGLE_OAUTH_ACCESS_TOKEN")); envTok != "" {
		p.accessToken = envTok
		p.expiresAt = time.Now().Add(30 * time.Minute)
		return p.accessToken
	}

	// 1. Try Cloud Run / GCE Metadata Server
	client := &http.Client{Timeout: 1500 * time.Millisecond}
	req, err := http.NewRequest("GET", "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token", nil)
	if err == nil {
		req.Header.Set("Metadata-Flavor", "Google")
		if resp, err := client.Do(req); err == nil {
			defer resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				var tok struct {
					AccessToken string `json:"access_token"`
					ExpiresIn   int    `json:"expires_in"`
				}
				if json.NewDecoder(resp.Body).Decode(&tok) == nil && tok.AccessToken != "" {
					p.accessToken = tok.AccessToken
					exp := tok.ExpiresIn - 60
					if exp < 60 {
						exp = 60
					}
					p.expiresAt = time.Now().Add(time.Duration(exp) * time.Second)
					return p.accessToken
				}
			}
		}
	}

	// 2. Fallback to `gcloud auth application-default print-access-token` or `gcloud auth print-access-token`
	if os.Getenv("AKKORD_DISABLE_REMOTE_GCP") == "1" {
		return ""
	}
	for _, args := range [][]string{
		{"auth", "application-default", "print-access-token"},
		{"auth", "print-access-token"},
	} {
		cmd := exec.Command("gcloud", args...)
		if out, err := cmd.Output(); err == nil {
			tok := strings.TrimSpace(string(out))
			if tok != "" {
				p.accessToken = tok
				p.expiresAt = time.Now().Add(45 * time.Minute)
				return p.accessToken
			}
		}
	}
	return ""
}

// ToFirestoreValue converts an arbitrary Go value into a Cloud Firestore REST v1 Value object.
func ToFirestoreValue(val any) map[string]any {
	if val == nil {
		return map[string]any{"nullValue": nil}
	}
	switch v := val.(type) {
	case bool:
		return map[string]any{"booleanValue": v}
	case int:
		return map[string]any{"integerValue": strconv.Itoa(v)}
	case int64:
		return map[string]any{"integerValue": strconv.FormatInt(v, 10)}
	case float64:
		if math.Trunc(v) == v && v >= -9007199254740991 && v <= 9007199254740991 {
			return map[string]any{"integerValue": strconv.FormatInt(int64(v), 10)}
		}
		return map[string]any{"doubleValue": v}
	case string:
		return map[string]any{"stringValue": v}
	case []any:
		arr := make([]map[string]any, 0, len(v))
		for _, item := range v {
			arr = append(arr, ToFirestoreValue(item))
		}
		return map[string]any{"arrayValue": map[string]any{"values": arr}}
	case []string:
		arr := make([]map[string]any, 0, len(v))
		for _, item := range v {
			arr = append(arr, map[string]any{"stringValue": item})
		}
		return map[string]any{"arrayValue": map[string]any{"values": arr}}
	case map[string]any:
		fields := make(map[string]any, len(v))
		for k, sub := range v {
			fields[k] = ToFirestoreValue(sub)
		}
		return map[string]any{"mapValue": map[string]any{"fields": fields}}
	default:
		// Marshal and unmarshal via JSON for struct types
		raw, err := json.Marshal(v)
		if err == nil {
			var generic any
			if json.Unmarshal(raw, &generic) == nil {
				return ToFirestoreValue(generic)
			}
		}
		return map[string]any{"stringValue": fmt.Sprintf("%v", v)}
	}
}

// FromFirestoreValue converts a Cloud Firestore REST v1 Value object back to a Go value.
func FromFirestoreValue(fv map[string]any) any {
	if _, ok := fv["nullValue"]; ok {
		return nil
	}
	if b, ok := fv["booleanValue"]; ok {
		if bv, ok := b.(bool); ok {
			return bv
		}
	}
	if i, ok := fv["integerValue"]; ok {
		switch iv := i.(type) {
		case string:
			if n, err := strconv.ParseInt(iv, 10, 64); err == nil {
				return int(n)
			}
		case float64:
			return int(iv)
		}
	}
	if d, ok := fv["doubleValue"]; ok {
		if dv, ok := d.(float64); ok {
			return dv
		}
	}
	if s, ok := fv["stringValue"]; ok {
		if sv, ok := s.(string); ok {
			return sv
		}
	}
	if a, ok := fv["arrayValue"].(map[string]any); ok {
		vals, _ := a["values"].([]any)
		out := make([]any, 0, len(vals))
		for _, item := range vals {
			if m, ok := item.(map[string]any); ok {
				out = append(out, FromFirestoreValue(m))
			}
		}
		return out
	}
	if m, ok := fv["mapValue"].(map[string]any); ok {
		fields, _ := m["fields"].(map[string]any)
		out := make(map[string]any, len(fields))
		for k, item := range fields {
			if sub, ok := item.(map[string]any); ok {
				out[k] = FromFirestoreValue(sub)
			}
		}
		return out
	}
	return nil
}

// FirestoreBackend provides Cloud Firestore REST persistence with local JSON mirror fallback.
type FirestoreBackend struct {
	ProjectID  string
	DatabaseID string
	LocalDir   string
	mu         sync.Mutex
}

// NewFirestoreBackend creates a FirestoreBackend with local disk mirror fallback.
func NewFirestoreBackend(projectID, localDir string) *FirestoreBackend {
	if projectID == "" {
		projectID = config.EnvOr("AKKORD_GCP_PROJECT", config.EnvOr("GOOGLE_CLOUD_PROJECT", config.DefaultGCPProject))
	}
	if localDir == "" {
		localDir = filepath.Join(config.DefaultOutputDir(), "_firestore_mirror")
	}
	_ = os.MkdirAll(localDir, 0o755)
	return &FirestoreBackend{
		ProjectID:  projectID,
		DatabaseID: config.EnvOr("AKKORD_FIRESTORE_DB", "(default)"),
		LocalDir:   localDir,
	}
}

func (f *FirestoreBackend) baseURL() string {
	return fmt.Sprintf("https://firestore.googleapis.com/v1/projects/%s/databases/%s/documents", f.ProjectID, f.DatabaseID)
}

func (f *FirestoreBackend) localDocPath(collection, docID string) string {
	colDir := filepath.Join(f.LocalDir, collection)
	_ = os.MkdirAll(colDir, 0o755)
	safeID := strings.ReplaceAll(strings.ReplaceAll(docID, "/", "_"), "..", "_")
	return filepath.Join(colDir, safeID+".json")
}

// SetDoc writes a document to Firestore REST API and mirrors it locally.
func (f *FirestoreBackend) SetDoc(collection, docID string, data map[string]any) bool {
	f.mu.Lock()
	localPath := f.localDocPath(collection, docID)
	if raw, err := json.MarshalIndent(data, "", "  "); err == nil {
		_ = os.WriteFile(localPath, raw, 0o644)
	}
	f.mu.Unlock()

	if os.Getenv("AKKORD_DISABLE_FIRESTORE") == "1" {
		return false
	}
	token := GlobalADC.GetAccessToken()
	if token == "" {
		return false
	}

	fields := make(map[string]any, len(data))
	for k, v := range data {
		fields[k] = ToFirestoreValue(v)
	}
	bodyBytes, err := json.Marshal(map[string]any{"fields": fields})
	if err != nil {
		return false
	}

	docURL := fmt.Sprintf("%s/%s/%s", f.baseURL(), collection, url.PathEscape(docID))
	req, err := http.NewRequest("PATCH", docURL, bytes.NewReader(bodyBytes))
	if err != nil {
		return false
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 8 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode >= 200 && resp.StatusCode < 300
}

// GetDoc retrieves a document from Firestore REST API or local fallback.
func (f *FirestoreBackend) GetDoc(collection, docID string) map[string]any {
	if os.Getenv("AKKORD_DISABLE_FIRESTORE") != "1" {
		if token := GlobalADC.GetAccessToken(); token != "" {
			docURL := fmt.Sprintf("%s/%s/%s", f.baseURL(), collection, url.PathEscape(docID))
			req, err := http.NewRequest("GET", docURL, nil)
			if err == nil {
				req.Header.Set("Authorization", "Bearer "+token)
				client := &http.Client{Timeout: 8 * time.Second}
				if resp, err := client.Do(req); err == nil {
					defer resp.Body.Close()
					if resp.StatusCode == http.StatusOK {
						var doc struct {
							Fields map[string]map[string]any `json:"fields"`
						}
						if json.NewDecoder(resp.Body).Decode(&doc) == nil {
							out := make(map[string]any, len(doc.Fields))
							for k, v := range doc.Fields {
								out[k] = FromFirestoreValue(v)
							}
							return out
						}
					}
				}
			}
		}
	}

	f.mu.Lock()
	defer f.mu.Unlock()
	localPath := f.localDocPath(collection, docID)
	raw, err := os.ReadFile(localPath)
	if err != nil {
		return nil
	}
	var out map[string]any
	if json.Unmarshal(raw, &out) != nil {
		return nil
	}
	return out
}

// DeleteDoc deletes a document from Firestore and local mirror.
func (f *FirestoreBackend) DeleteDoc(collection, docID string) bool {
	f.mu.Lock()
	_ = os.Remove(f.localDocPath(collection, docID))
	f.mu.Unlock()

	if os.Getenv("AKKORD_DISABLE_FIRESTORE") == "1" {
		return true
	}
	if token := GlobalADC.GetAccessToken(); token != "" {
		docURL := fmt.Sprintf("%s/%s/%s", f.baseURL(), collection, url.PathEscape(docID))
		req, err := http.NewRequest("DELETE", docURL, nil)
		if err == nil {
			req.Header.Set("Authorization", "Bearer "+token)
			client := &http.Client{Timeout: 8 * time.Second}
			if resp, err := client.Do(req); err == nil {
				resp.Body.Close()
			}
		}
	}
	return true
}

// ListDocs lists documents in a collection up to pageSize.
func (f *FirestoreBackend) ListDocs(collection string, pageSize int) []map[string]any {
	if pageSize <= 0 {
		pageSize = 100
	}
	if os.Getenv("AKKORD_DISABLE_FIRESTORE") != "1" {
		if token := GlobalADC.GetAccessToken(); token != "" {
			listURL := fmt.Sprintf("%s/%s?pageSize=%d", f.baseURL(), collection, pageSize)
			req, err := http.NewRequest("GET", listURL, nil)
			if err == nil {
				req.Header.Set("Authorization", "Bearer "+token)
				client := &http.Client{Timeout: 8 * time.Second}
				if resp, err := client.Do(req); err == nil {
					defer resp.Body.Close()
					if resp.StatusCode == http.StatusOK {
						var payload struct {
							Documents []struct {
								Fields map[string]map[string]any `json:"fields"`
							} `json:"documents"`
						}
						if json.NewDecoder(resp.Body).Decode(&payload) == nil && len(payload.Documents) > 0 {
							results := make([]map[string]any, 0, len(payload.Documents))
							for _, d := range payload.Documents {
								row := make(map[string]any, len(d.Fields))
								for k, v := range d.Fields {
									row[k] = FromFirestoreValue(v)
								}
								results = append(results, row)
							}
							return results
						}
					}
				}
			}
		}
	}

	f.mu.Lock()
	defer f.mu.Unlock()
	colDir := filepath.Join(f.LocalDir, collection)
	entries, err := os.ReadDir(colDir)
	if err != nil {
		return nil
	}
	type fileMtime struct {
		path  string
		mtime time.Time
	}
	var files []fileMtime
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".json") {
			info, err := e.Info()
			mtime := time.Time{}
			if err == nil {
				mtime = info.ModTime()
			}
			files = append(files, fileMtime{
				path:  filepath.Join(colDir, e.Name()),
				mtime: mtime,
			})
		}
	}
	sort.Slice(files, func(i, j int) bool {
		return files[i].mtime.After(files[j].mtime)
	})
	if len(files) > pageSize {
		files = files[:pageSize]
	}
	var out []map[string]any
	for _, fm := range files {
		if raw, err := os.ReadFile(fm.path); err == nil {
			var doc map[string]any
			if json.Unmarshal(raw, &doc) == nil {
				out = append(out, doc)
			}
		}
	}
	return out
}

// GCSBackend stores and retrieves PDF blobs in Google Cloud Storage with local mirror fallback.
type GCSBackend struct {
	BucketName string
	LocalDir   string
}

// NewGCSBackend creates a GCSBackend.
func NewGCSBackend(bucketName, localDir string) *GCSBackend {
	if bucketName == "" {
		bucketName = config.EnvOr("AKKORD_GCS_BUCKET", config.DefaultGCSBucket)
	}
	if localDir == "" {
		localDir = filepath.Join(config.DefaultOutputDir(), "_gcs_mirror")
	}
	_ = os.MkdirAll(localDir, 0o755)
	return &GCSBackend{
		BucketName: bucketName,
		LocalDir:   localDir,
	}
}

func (g *GCSBackend) localBlobPath(objectName string) string {
	safe := strings.ReplaceAll(strings.TrimLeft(objectName, "/"), "..", "_")
	target := filepath.Join(g.LocalDir, safe)
	_ = os.MkdirAll(filepath.Dir(target), 0o755)
	return target
}

// UploadBytes writes data to the local mirror and uploads to GCS if credentials are available.
func (g *GCSBackend) UploadBytes(objectName string, data []byte, contentType string) string {
	if contentType == "" {
		contentType = "application/pdf"
	}
	localPath := g.localBlobPath(objectName)
	_ = os.WriteFile(localPath, data, 0o644)

	if os.Getenv("AKKORD_DISABLE_GCS") == "1" {
		return localPath
	}
	token := GlobalADC.GetAccessToken()
	if token == "" {
		return localPath
	}

	uploadURL := fmt.Sprintf("https://storage.googleapis.com/upload/storage/v1/b/%s/o?uploadType=media&name=%s",
		url.PathEscape(g.BucketName), url.QueryEscape(objectName))
	req, err := http.NewRequest("POST", uploadURL, bytes.NewReader(data))
	if err != nil {
		return localPath
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", contentType)
	client := &http.Client{Timeout: 30 * time.Second}
	if resp, err := client.Do(req); err == nil {
		defer resp.Body.Close()
		if resp.StatusCode >= 200 && resp.StatusCode < 300 {
			return fmt.Sprintf("gs://%s/%s", g.BucketName, objectName)
		}
	}
	return localPath
}

// UploadFile uploads a local file to GCS.
func (g *GCSBackend) UploadFile(objectName, filePath, contentType string) string {
	data, err := os.ReadFile(filePath)
	if err != nil {
		return ""
	}
	return g.UploadBytes(objectName, data, contentType)
}

// DownloadBytes downloads an object from local mirror or GCS.
func (g *GCSBackend) DownloadBytes(objectName string) []byte {
	localPath := g.localBlobPath(objectName)
	if data, err := os.ReadFile(localPath); err == nil {
		return data
	}
	if os.Getenv("AKKORD_DISABLE_GCS") == "1" {
		return nil
	}
	token := GlobalADC.GetAccessToken()
	if token == "" {
		return nil
	}
	dlURL := fmt.Sprintf("https://storage.googleapis.com/storage/v1/b/%s/o/%s?alt=media",
		url.PathEscape(g.BucketName), url.PathEscape(objectName))
	req, err := http.NewRequest("GET", dlURL, nil)
	if err != nil {
		return nil
	}
	req.Header.Set("Authorization", "Bearer "+token)
	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusOK {
		if data, err := io.ReadAll(resp.Body); err == nil {
			_ = os.WriteFile(localPath, data, 0o644)
			return data
		}
	}
	return nil
}

// DownloadToFile downloads an object to destPath.
func (g *GCSBackend) DownloadToFile(objectName, destPath string) bool {
	data := g.DownloadBytes(objectName)
	if data == nil {
		return false
	}
	_ = os.MkdirAll(filepath.Dir(destPath), 0o755)
	return os.WriteFile(destPath, data, 0o644) == nil
}

// ActivityManager manages the 25 PDFs/day quota in Europe/Paris, records token/cost activity,
// and generates/sends the 18:00 daily usage email report.
type ActivityManager struct {
	OutputDir       string
	StoragePath     string
	DailyLimit      int
	ReportEmail     string
	ReportHourLocal int
	Firestore       *FirestoreBackend
	mu              sync.Mutex
}

// NewActivityManager creates an ActivityManager.
func NewActivityManager(outputDir string, fs *FirestoreBackend) *ActivityManager {
	if outputDir == "" {
		outputDir = config.DefaultOutputDir()
	}
	_ = os.MkdirAll(outputDir, 0o755)
	if fs == nil {
		fs = NewFirestoreBackend("", filepath.Join(outputDir, "_firestore_mirror"))
	}
	limit := config.DailyFileLimit
	if v, err := strconv.Atoi(config.EnvOr("AKKORD_DAILY_FILE_LIMIT", "")); err == nil && v > 0 {
		limit = v
	}
	hour := config.DailyReportHour
	if v, err := strconv.Atoi(config.EnvOr("AKKORD_DAILY_REPORT_HOUR", "")); err == nil && v >= 0 && v <= 23 {
		hour = v
	}
	return &ActivityManager{
		OutputDir:       outputDir,
		StoragePath:     filepath.Join(outputDir, "activity_usage.json"),
		DailyLimit:      limit,
		ReportEmail:     config.EnvOr("AKKORD_REPORT_EMAIL", config.AdminEmail),
		ReportHourLocal: hour,
		Firestore:       fs,
	}
}

func parisNow() time.Time {
	loc, err := time.LoadLocation("Europe/Paris")
	if err != nil {
		return time.Now()
	}
	return time.Now().In(loc)
}

func TodayKey() string {
	return parisNow().Format("2006-01-02")
}

func NextDayKey(fromDate string) string {
	if fromDate == "" {
		fromDate = TodayKey()
	}
	d, err := time.Parse("2006-01-02", fromDate)
	if err != nil {
		return TodayKey()
	}
	return d.AddDate(0, 0, 1).Format("2006-01-02")
}

func newDayEntry(dateKey string) map[string]any {
	return map[string]any{
		"date":                 dateKey,
		"files_processed":      0,
		"quota_reset_baseline": 0,
		"quota_resets":         []any{},
		"input_tokens":         0,
		"output_tokens":        0,
		"thinking_tokens":      0,
		"cached_tokens":        0,
		"total_tokens":         0,
		"estimated_cost_usd":   0.0,
		"estimated_cost_eur":   0.0,
		"report_sent":          false,
		"report_sent_at":       nil,
		"events":               []any{},
	}
}

func (a *ActivityManager) loadStoreUnlocked() map[string]any {
	storeData := map[string]any{"days": map[string]any{}}
	if raw, err := os.ReadFile(a.StoragePath); err == nil {
		var parsed map[string]any
		if json.Unmarshal(raw, &parsed) == nil {
			if _, ok := parsed["days"].(map[string]any); ok {
				storeData = parsed
			}
		}
	}
	daysMap, _ := storeData["days"].(map[string]any)
	if daysMap == nil {
		daysMap = map[string]any{}
		storeData["days"] = daysMap
	}
	tKey := TodayKey()
	if fsDay := a.Firestore.GetDoc("akkord_daily_usage", tKey); fsDay != nil {
		if _, ok := fsDay["files_processed"]; ok {
			daysMap[tKey] = fsDay
		}
	}
	return storeData
}

func (a *ActivityManager) saveStoreUnlocked(storeData map[string]any) {
	if raw, err := json.MarshalIndent(storeData, "", "  "); err == nil {
		_ = os.WriteFile(a.StoragePath, raw, 0o644)
	}
	daysMap, _ := storeData["days"].(map[string]any)
	tKey := TodayKey()
	if todayEntry, ok := daysMap[tKey].(map[string]any); ok {
		a.Firestore.SetDoc("akkord_daily_usage", tKey, todayEntry)
	}
}

func (a *ActivityManager) ensureDayUnlocked(storeData map[string]any, dateKey string) map[string]any {
	daysMap, _ := storeData["days"].(map[string]any)
	if existing, ok := daysMap[dateKey].(map[string]any); ok {
		return existing
	}
	if fsDay := a.Firestore.GetDoc("akkord_daily_usage", dateKey); fsDay != nil {
		if _, ok := fsDay["files_processed"]; ok {
			daysMap[dateKey] = fsDay
			return fsDay
		}
	}
	entry := newDayEntry(dateKey)
	daysMap[dateKey] = entry
	return entry
}

func toInt(v any) int {
	switch val := v.(type) {
	case int:
		return val
	case int64:
		return int(val)
	case float64:
		return int(val)
	case string:
		n, _ := strconv.Atoi(val)
		return n
	default:
		return 0
	}
}

func toFloat(v any) float64 {
	switch val := v.(type) {
	case float64:
		return val
	case int:
		return float64(val)
	case int64:
		return float64(val)
	case string:
		f, _ := strconv.ParseFloat(val, 64)
		return f
	default:
		return 0.0
	}
}

// GetTodayQuotaStatus returns the current daily quota status in Europe/Paris.
func (a *ActivityManager) GetTodayQuotaStatus() map[string]any {
	a.mu.Lock()
	defer a.mu.Unlock()
	storeData := a.loadStoreUnlocked()
	tKey := TodayKey()
	day := a.ensureDayUnlocked(storeData, tKey)
	totalFiles := toInt(day["files_processed"])
	baseline := toInt(day["quota_reset_baseline"])
	used := totalFiles - baseline
	if used < 0 {
		used = 0
	}
	remaining := a.DailyLimit - used
	if remaining < 0 {
		remaining = 0
	}
	return map[string]any{
		"date":                 tKey,
		"used":                 used,
		"total_processed_today": totalFiles,
		"quota_reset_baseline": baseline,
		"limit":                a.DailyLimit,
		"remaining":            remaining,
		"exceeded":             used >= a.DailyLimit,
	}
}

// ResetDailyQuota resets the effective daily counter to 0 while preserving cumulative token/cost stats.
func (a *ActivityManager) ResetDailyQuota(dateKey, resetBy string) map[string]any {
	a.mu.Lock()
	defer a.mu.Unlock()
	if dateKey == "" {
		dateKey = TodayKey()
	}
	if resetBy == "" {
		resetBy = "admin"
	}
	storeData := a.loadStoreUnlocked()
	day := a.ensureDayUnlocked(storeData, dateKey)
	totalFiles := toInt(day["files_processed"])
	day["quota_reset_baseline"] = totalFiles
	resets, _ := day["quota_resets"].([]any)
	resets = append(resets, map[string]any{
		"timestamp":          parisNow().Format(time.RFC3339),
		"reset_by":           resetBy,
		"baseline_set_to":    totalFiles,
	})
	day["quota_resets"] = resets
	a.saveStoreUnlocked(storeData)
	if dateKey != TodayKey() {
		a.Firestore.SetDoc("akkord_daily_usage", dateKey, day)
	}
	return map[string]any{
		"date":                 dateKey,
		"used":                 0,
		"total_processed_today": totalFiles,
		"quota_reset_baseline": totalFiles,
		"limit":                a.DailyLimit,
		"remaining":            a.DailyLimit,
		"exceeded":             false,
	}
}

// CheckAndConsumeQuota checks if a file can be processed today.
func (a *ActivityManager) CheckAndConsumeQuota() (bool, map[string]any) {
	status := a.GetTodayQuotaStatus()
	used := toInt(status["used"])
	limit := toInt(status["limit"])
	return used < limit, status
}

// RecordFileProcessed logs a completed PDF processing event and updates daily token/cost totals.
func (a *ActivityManager) RecordFileProcessed(
	filename, mode, model, language, detectedKey string,
	accuracyScore int,
	tokenUsage map[string]any,
	userEmail, jobID string,
) map[string]any {
	a.mu.Lock()
	defer a.mu.Unlock()

	storeData := a.loadStoreUnlocked()
	tKey := TodayKey()
	day := a.ensureDayUnlocked(storeData, tKey)

	inTok := toInt(tokenUsage["input_tokens"])
	outTok := toInt(tokenUsage["output_tokens"])
	thinkTok := toInt(tokenUsage["thinking_tokens"])
	cacheTok := toInt(tokenUsage["cached_tokens"])
	totalTok := toInt(tokenUsage["total_tokens"])
	if totalTok == 0 {
		totalTok = inTok + outTok + thinkTok
	}
	costUSD := toFloat(tokenUsage["estimated_cost_usd"])
	costEUR := toFloat(tokenUsage["estimated_cost_eur"])

	day["files_processed"] = toInt(day["files_processed"]) + 1
	day["input_tokens"] = toInt(day["input_tokens"]) + inTok
	day["output_tokens"] = toInt(day["output_tokens"]) + outTok
	day["thinking_tokens"] = toInt(day["thinking_tokens"]) + thinkTok
	day["cached_tokens"] = toInt(day["cached_tokens"]) + cacheTok
	day["total_tokens"] = toInt(day["total_tokens"]) + totalTok
	day["estimated_cost_usd"] = math.Round((toFloat(day["estimated_cost_usd"])+costUSD)*1e6) / 1e6
	day["estimated_cost_eur"] = math.Round((toFloat(day["estimated_cost_eur"])+costEUR)*1e6) / 1e6

	event := map[string]any{
		"timestamp":          parisNow().Format(time.RFC3339),
		"filename":           filename,
		"mode":               mode,
		"model":              model,
		"language":           language,
		"detected_key":       detectedKey,
		"accuracy_score":     accuracyScore,
		"user_email":         userEmail,
		"job_id":             jobID,
		"input_tokens":       inTok,
		"output_tokens":      outTok,
		"thinking_tokens":    thinkTok,
		"cached_tokens":      cacheTok,
		"total_tokens":       totalTok,
		"estimated_cost_usd": math.Round(costUSD*1e6) / 1e6,
		"estimated_cost_eur": math.Round(costEUR*1e6) / 1e6,
	}
	events, _ := day["events"].([]any)
	events = append(events, event)
	day["events"] = events

	a.saveStoreUnlocked(storeData)
	return event
}

// GetUsageSummary returns today's summary, all-time totals, and recent daily history.
func (a *ActivityManager) GetUsageSummary(daysLimit int) map[string]any {
	if daysLimit <= 0 {
		daysLimit = 14
	}
	a.mu.Lock()
	defer a.mu.Unlock()

	storeData := a.loadStoreUnlocked()
	daysMap, _ := storeData["days"].(map[string]any)
	if daysMap == nil {
		daysMap = map[string]any{}
		storeData["days"] = daysMap
	}

	for _, fsDoc := range a.Firestore.ListDocs("akkord_daily_usage", 60) {
		if dKey, ok := fsDoc["date"].(string); ok && dKey != "" {
			if _, exists := daysMap[dKey]; !exists {
				daysMap[dKey] = fsDoc
			}
		}
	}

	tKey := TodayKey()
	todayEntry := a.ensureDayUnlocked(storeData, tKey)

	keys := make([]string, 0, len(daysMap))
	for k := range daysMap {
		keys = append(keys, k)
	}
	sort.Sort(sort.Reverse(sort.StringSlice(keys)))
	if len(keys) > daysLimit {
		keys = keys[:daysLimit]
	}

	recentDays := make([]map[string]any, 0, len(keys))
	for _, k := range keys {
		if d, ok := daysMap[k].(map[string]any); ok {
			recentDays = append(recentDays, d)
		}
	}

	totalFiles := 0
	totalTokens := 0
	totalCostUSD := 0.0
	totalCostEUR := 0.0
	for _, v := range daysMap {
		if d, ok := v.(map[string]any); ok {
			totalFiles += toInt(d["files_processed"])
			totalTokens += toInt(d["total_tokens"])
			totalCostUSD += toFloat(d["estimated_cost_usd"])
			totalCostEUR += toFloat(d["estimated_cost_eur"])
		}
	}

	todayTotalFiles := toInt(todayEntry["files_processed"])
	todayBaseline := toInt(todayEntry["quota_reset_baseline"])
	todayUsed := todayTotalFiles - todayBaseline
	if todayUsed < 0 {
		todayUsed = 0
	}
	todayRem := a.DailyLimit - todayUsed
	if todayRem < 0 {
		todayRem = 0
	}

	return map[string]any{
		"today":        todayEntry,
		"daily_limit":  a.DailyLimit,
		"report_email": a.ReportEmail,
		"report_hour":  fmt.Sprintf("%02d:00", a.ReportHourLocal),
		"quota": map[string]any{
			"date":                  tKey,
			"used":                  todayUsed,
			"total_processed_today": todayTotalFiles,
			"quota_reset_baseline":  todayBaseline,
			"limit":                 a.DailyLimit,
			"remaining":             todayRem,
			"exceeded":              todayUsed >= a.DailyLimit,
		},
		"totals": map[string]any{
			"files_processed":    totalFiles,
			"total_tokens":       totalTokens,
			"estimated_cost_usd": math.Round(totalCostUSD*1e4) / 1e4,
			"estimated_cost_eur": math.Round(totalCostEUR*1e4) / 1e4,
		},
		"recent_days": recentDays,
	}
}

// BuildDailyReportEmail constructs the subject, plain-text body, and HTML body for the 18:00 report.
func (a *ActivityManager) BuildDailyReportEmail(dateKey string) (string, string, string) {
	a.mu.Lock()
	storeData := a.loadStoreUnlocked()
	if dateKey == "" {
		dateKey = TodayKey()
	}
	day := a.ensureDayUnlocked(storeData, dateKey)
	a.mu.Unlock()

	filesCount := toInt(day["files_processed"])
	inTok := toInt(day["input_tokens"])
	outTok := toInt(day["output_tokens"])
	thinkTok := toInt(day["thinking_tokens"])
	totalTok := toInt(day["total_tokens"])
	costUSD := toFloat(day["estimated_cost_usd"])
	costEUR := toFloat(day["estimated_cost_eur"])
	events, _ := day["events"].([]any)

	subject := fmt.Sprintf("[Akkord] Rapport d'activité quotidien — %s (%d/%d partitions)", dateKey, filesCount, a.DailyLimit)

	var textLines []string
	textLines = append(textLines,
		fmt.Sprintf("Akkord — Rapport d'activité quotidien (%s)", dateKey),
		strings.Repeat("=", 56),
		fmt.Sprintf("Partitions traitées aujourd'hui : %d / %d", filesCount, a.DailyLimit),
		fmt.Sprintf("Tokens consommés (Total)        : %d tokens", totalTok),
		fmt.Sprintf("  - Prompt (Entrée)             : %d", inTok),
		fmt.Sprintf("  - Réponse (Sortie)            : %d", outTok),
		fmt.Sprintf("  - Raisonnement (Thinking)     : %d", thinkTok),
		fmt.Sprintf("Coût estimé Gemini API          : %.4f EUR ($%.4f USD)", costEUR, costUSD),
		"",
		"Détail des partitions traitées :",
	)
	if len(events) == 0 {
		textLines = append(textLines, "  (Aucune partition traitée sur cette journée)")
	} else {
		for idx, rawEv := range events {
			if ev, ok := rawEv.(map[string]any); ok {
				ts, _ := ev["timestamp"].(string)
				if len(ts) >= 19 {
					ts = ts[11:19]
				}
				textLines = append(textLines, fmt.Sprintf(
					"  %d. [%s] %v — Mode: %v | Modèle: %v | Tonalité: %v | Tokens: %d | Coût: %.4f €",
					idx+1, ts, ev["filename"], ev["mode"], ev["model"], ev["detected_key"],
					toInt(ev["total_tokens"]), toFloat(ev["estimated_cost_eur"]),
				))
			}
		}
	}
	textBody := strings.Join(textLines, "\n")

	var rowsHTML strings.Builder
	if len(events) == 0 {
		rowsHTML.WriteString(`<tr><td colspan="7" style="padding:12px;text-align:center;color:#78716c;">Aucune partition traitée aujourd'hui.</td></tr>`)
	} else {
		for idx, rawEv := range events {
			if ev, ok := rawEv.(map[string]any); ok {
				ts, _ := ev["timestamp"].(string)
				if len(ts) >= 19 {
					ts = ts[11:19]
				}
				fname, _ := ev["filename"].(string)
				mode, _ := ev["mode"].(string)
				model, _ := ev["model"].(string)
				dkey, _ := ev["detected_key"].(string)
				rowsHTML.WriteString(fmt.Sprintf(
					`<tr>`+
						`<td style="padding:8px 10px;border-bottom:1px solid #e7e0d0;">%d</td>`+
						`<td style="padding:8px 10px;border-bottom:1px solid #e7e0d0;font-family:monospace;">%s</td>`+
						`<td style="padding:8px 10px;border-bottom:1px solid #e7e0d0;font-weight:600;">%s</td>`+
						`<td style="padding:8px 10px;border-bottom:1px solid #e7e0d0;">%s</td>`+
						`<td style="padding:8px 10px;border-bottom:1px solid #e7e0d0;">%s</td>`+
						`<td style="padding:8px 10px;border-bottom:1px solid #e7e0d0;">%s</td>`+
						`<td style="padding:8px 10px;border-bottom:1px solid #e7e0d0;text-align:right;font-family:monospace;">%d tok (%.4f €)</td>`+
						`</tr>`,
					idx+1, html.EscapeString(ts), html.EscapeString(fname),
					html.EscapeString(mode), html.EscapeString(model), html.EscapeString(dkey),
					toInt(ev["total_tokens"]), toFloat(ev["estimated_cost_eur"]),
				))
			}
		}
	}

	htmlBody := fmt.Sprintf(`<!DOCTYPE html>
<html>
<body style="font-family:Georgia,serif;background:#f7f3eb;color:#181615;padding:24px;">
  <div style="max-width:740px;margin:0 auto;background:#fcfaf5;border:1px solid #d8ceb8;border-radius:8px;padding:24px;">
    <h2 style="margin-top:0;color:#9e2a2b;border-bottom:2px solid #9e2a2b;padding-bottom:10px;">
      Akkord — Rapport d'activité quotidien (%s)
    </h2>
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin:18px 0;">
      <div style="flex:1;min-width:150px;background:#f0eadc;padding:12px 16px;border-radius:6px;">
        <div style="font-size:11px;text-transform:uppercase;color:#78716c;">Partitions traitées</div>
        <div style="font-size:22px;font-weight:bold;color:#181615;">%d / %d</div>
      </div>
      <div style="flex:1;min-width:150px;background:#f0eadc;padding:12px 16px;border-radius:6px;">
        <div style="font-size:11px;text-transform:uppercase;color:#78716c;">Tokens Gemini</div>
        <div style="font-size:22px;font-weight:bold;color:#1d4e89;">%d</div>
        <div style="font-size:11px;color:#57534e;">In: %d · Out: %d · Think: %d</div>
      </div>
      <div style="flex:1;min-width:150px;background:#f0eadc;padding:12px 16px;border-radius:6px;">
        <div style="font-size:11px;text-transform:uppercase;color:#78716c;">Coût estimé</div>
        <div style="font-size:22px;font-weight:bold;color:#2b6e44;">%.4f €</div>
        <div style="font-size:11px;color:#57534e;">$%.4f USD</div>
      </div>
    </div>
    <h3 style="font-size:15px;margin-top:22px;color:#181615;">Journal détaillé des partitions</h3>
    <table style="width:100%%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="background:#efe8d8;text-align:left;">
          <th style="padding:8px 10px;">#</th>
          <th style="padding:8px 10px;">Heure</th>
          <th style="padding:8px 10px;">Fichier</th>
          <th style="padding:8px 10px;">Mode</th>
          <th style="padding:8px 10px;">Modèle</th>
          <th style="padding:8px 10px;">Tonalité</th>
          <th style="padding:8px 10px;text-align:right;">Tokens & Coût</th>
        </tr>
      </thead>
      <tbody>%s</tbody>
    </table>
  </div>
</body>
</html>`, dateKey, filesCount, a.DailyLimit, totalTok, inTok, outTok, thinkTok, costEUR, costUSD, rowsHTML.String())

	return subject, textBody, htmlBody
}

// SendDailyReportEmail sends the daily activity report via SMTP, Webhook, or Gmail REST API (with OAuth token).
func (a *ActivityManager) SendDailyReportEmail(dateKey string, force bool, oauthAccessToken string) map[string]any {
	if dateKey == "" {
		dateKey = TodayKey()
	}
	a.mu.Lock()
	storeData := a.loadStoreUnlocked()
	day := a.ensureDayUnlocked(storeData, dateKey)
	if sent, _ := day["report_sent"].(bool); sent && !force {
		a.mu.Unlock()
		return map[string]any{
			"status":    "already_sent",
			"date":      dateKey,
			"recipient": a.ReportEmail,
		}
	}
	a.mu.Unlock()

	subject, textBody, htmlBody := a.BuildDailyReportEmail(dateKey)
	methodUsed := "logged_only"
	delivered := false
	var lastError string

	// 1. Try SMTP if configured
	smtpHost := strings.TrimSpace(os.Getenv("AKKORD_SMTP_HOST"))
	smtpUser := strings.TrimSpace(os.Getenv("AKKORD_SMTP_USER"))
	smtpPass := strings.TrimSpace(os.Getenv("AKKORD_SMTP_PASS"))
	smtpPort := config.EnvOr("AKKORD_SMTP_PORT", "587")
	if smtpHost != "" && smtpUser != "" && smtpPass != "" {
		msg := fmt.Sprintf("From: %s\r\nTo: %s\r\nSubject: %s\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n%s",
			smtpUser, a.ReportEmail, subject, htmlBody)
		auth := smtp.PlainAuth("", smtpUser, smtpPass, smtpHost)
		if err := smtp.SendMail(smtpHost+":"+smtpPort, auth, smtpUser, []string{a.ReportEmail}, []byte(msg)); err == nil {
			delivered = true
			methodUsed = "smtp"
		} else {
			lastError = err.Error()
		}
	}

	// 2. Try Gmail REST API if oauthAccessToken is provided
	if !delivered && oauthAccessToken != "" {
		rawMsg := fmt.Sprintf("To: %s\r\nSubject: %s\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n%s",
			a.ReportEmail, subject, htmlBody)
		rawB64 := base64.URLEncoding.EncodeToString([]byte(rawMsg))
		bodyBytes, _ := json.Marshal(map[string]string{"raw": rawB64})
		req, err := http.NewRequest("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", bytes.NewReader(bodyBytes))
		if err == nil {
			req.Header.Set("Authorization", "Bearer "+oauthAccessToken)
			req.Header.Set("Content-Type", "application/json")
			client := &http.Client{Timeout: 15 * time.Second}
			if resp, err := client.Do(req); err == nil {
				defer resp.Body.Close()
				if resp.StatusCode >= 200 && resp.StatusCode < 300 {
					delivered = true
					methodUsed = "gmail_api"
				} else {
					b, _ := io.ReadAll(resp.Body)
					lastError = fmt.Sprintf("Gmail HTTP %d: %s", resp.StatusCode, string(b))
				}
			}
		}
	}

	a.mu.Lock()
	storeData = a.loadStoreUnlocked()
	day = a.ensureDayUnlocked(storeData, dateKey)
	if delivered {
		day["report_sent"] = true
		day["report_sent_at"] = parisNow().Format(time.RFC3339)
		day["report_method"] = methodUsed
		a.saveStoreUnlocked(storeData)
	}
	a.mu.Unlock()

	return map[string]any{
		"status":       map[bool]string{true: "sent", false: "preview_only"}[delivered],
		"delivered":    delivered,
		"method":       methodUsed,
		"date":         dateKey,
		"recipient":    a.ReportEmail,
		"subject":      subject,
		"text_preview": textBody,
		"html_preview": htmlBody,
		"error":        lastError,
	}
}
