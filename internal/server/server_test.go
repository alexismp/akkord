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

package server

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/alexismp/akkord/internal/config"
	"github.com/alexismp/akkord/internal/drive"
	"github.com/alexismp/akkord/internal/harmony"
	"github.com/alexismp/akkord/internal/jobs"
	"github.com/alexismp/akkord/internal/oauth"
	"github.com/alexismp/akkord/internal/rustbridge"
	"github.com/alexismp/akkord/internal/store"
)

func TestOAuthStatelessCookieRoundTrip(t *testing.T) {
	t.Setenv("AKKORD_DISABLE_FIRESTORE", "1")
	t.Setenv("AKKORD_DISABLE_REMOTE_GCP", "1")

	tmp := t.TempDir()
	fs := store.NewFirestoreBackend("test-proj", filepath.Join(tmp, "_fs"))
	mgr := oauth.NewOAuthManager(tmp, fs)
	mgr.ClientSecret = "unit-test-secret"

	now := float64(time.Now().Unix())
	orig := &oauth.UserSession{
		SessionID:    "sess_12345",
		Email:        "alexis.mp@gmail.com",
		Name:         "Admin User",
		Picture:      "https://example.com/pic.png",
		AccessToken:  "ya29.test_access_token",
		RefreshToken: "1//test_refresh_token",
		ExpiresAt:    now + 3600,
		CreatedAt:    now,
	}

	token := mgr.EncodeSessionCookie(orig)
	if !strings.HasPrefix(token, "v1.") {
		t.Fatalf("expected v1. prefix, got %s", token)
	}

	decoded := mgr.DecodeSessionCookie(token)
	if decoded == nil {
		t.Fatalf("DecodeSessionCookie returned nil")
	}
	if decoded.Email != orig.Email || decoded.AccessToken != orig.AccessToken || !decoded.IsAdmin() {
		t.Fatalf("unexpected decoded session: %+v", decoded)
	}

	// Tampered signature must be rejected
	tampered := token[:len(token)-2] + "ff"
	if mgr.DecodeSessionCookie(tampered) != nil {
		t.Fatalf("expected tampered cookie to be rejected")
	}
}

func TestHarmonyHelpersAndAccuracyScore(t *testing.T) {
	cases := map[string]string{
		"E7/B (renversement)": "E7/B",
		"Am ou C/G":           "Am",
		"F#m7b5 - 2e degré":   "F#m7b5",
		"G m":                 "Gm",
	}
	for input, want := range cases {
		got, _ := harmony.ExtractCompactChordSymbol(input)
		if got != want {
			t.Errorf("ExtractCompactChordSymbol(%q) = %q, want %q", input, got, want)
		}
	}

	res := &rustbridge.HarmonyAnalysisResult{
		IsMusicSheet:      true,
		HasExistingChords: true,
		Annotations: []rustbridge.ChordAnnotation{
			{Chord: "Am", Status: "correct"},
			{Chord: "Dm", Status: "correct"},
			{Chord: "E7", SuggestedChord: "E7/G#", Status: "improve"},
			{Chord: "G", SuggestedChord: "Gm", Status: "improve"},
			{Chord: "C", Status: "missing"},
		},
	}
	score := harmony.ComputeHarmonyAccuracyScore(res)
	if score < 60 || score > 85 {
		t.Errorf("expected blended score in 60..85, got %d", score)
	}
}

func TestQuotaAndAdminResetPreservesHistory(t *testing.T) {
	t.Setenv("AKKORD_DISABLE_FIRESTORE", "1")
	t.Setenv("AKKORD_DISABLE_REMOTE_GCP", "1")

	tmp := t.TempDir()
	fs := store.NewFirestoreBackend("test-proj", filepath.Join(tmp, "_fs"))
	act := store.NewActivityManager(tmp, fs)
	act.DailyLimit = 2

	act.RecordFileProcessed("s1.pdf", "add_chords", "gemini-4-argon", "fr", "Am", 100, map[string]any{"total_tokens": 1000, "estimated_cost_eur": 0.01}, "", "j1")
	act.RecordFileProcessed("s2.pdf", "add_chords", "gemini-4-argon", "fr", "Em", 100, map[string]any{"total_tokens": 1200, "estimated_cost_eur": 0.012}, "", "j1")

	allowed, q1 := act.CheckAndConsumeQuota()
	if allowed || q1["exceeded"] != true {
		t.Fatalf("expected quota exceeded after 2 files, got %+v", q1)
	}

	qReset := act.ResetDailyQuota("", "alexis.mp@gmail.com")
	if qReset["used"] != 0 || qReset["remaining"] != 2 || qReset["total_processed_today"] != 2 {
		t.Fatalf("unexpected quota after reset: %+v", qReset)
	}

	summary := act.GetUsageSummary(7)
	totals, _ := summary["totals"].(map[string]any)
	if totals["files_processed"] != 2 || totals["total_tokens"] != 2200 {
		t.Fatalf("expected cumulative totals preserved after quota reset, got %+v", totals)
	}
}

func TestServerEndpointsAndEndToEndGoRustPipeline(t *testing.T) {
	t.Setenv("AKKORD_DISABLE_FIRESTORE", "1")
	t.Setenv("AKKORD_DISABLE_GCS", "1")
	t.Setenv("AKKORD_DISABLE_REMOTE_GCP", "1")

	tmp := t.TempDir()
	staticDir, err := filepath.Abs("../../akkord/static")
	if err != nil {
		t.Fatal(err)
	}
	srv := NewServer(tmp, staticDir)
	handler := srv.Handler()

	// 1. Check GET /api/config via in-memory httptest.NewRecorder
	req1 := httptest.NewRequest("GET", "/api/config", nil)
	rec1 := httptest.NewRecorder()
	handler.ServeHTTP(rec1, req1)
	if rec1.Code != http.StatusOK {
		t.Fatalf("GET /api/config status = %d", rec1.Code)
	}
	var cfgPayload map[string]any
	if err := json.NewDecoder(rec1.Body).Decode(&cfgPayload); err != nil {
		t.Fatal(err)
	}
	if cfgPayload["runtime_engine"] != "go-rust-polyglot" {
		t.Fatalf("expected runtime_engine=go-rust-polyglot, got %v", cfgPayload["runtime_engine"])
	}

	// 2. Check POST /api/scan-folder on ../../samples
	samplesDir, err := filepath.Abs("../../samples")
	if err != nil {
		t.Fatal(err)
	}
	scanBody, _ := json.Marshal(map[string]string{"drive_folder": samplesDir})
	req2 := httptest.NewRequest("POST", "/api/scan-folder", bytes.NewReader(scanBody))
	req2.Header.Set("Content-Type", "application/json")
	rec2 := httptest.NewRecorder()
	handler.ServeHTTP(rec2, req2)
	if rec2.Code != http.StatusOK {
		t.Fatalf("POST /api/scan-folder status = %d: %s", rec2.Code, rec2.Body.String())
	}
	var scanData map[string]any
	_ = json.NewDecoder(rec2.Body).Decode(&scanData)
	if count, _ := scanData["count"].(float64); count < 2 {
		t.Fatalf("expected at least 2 sample PDFs in %s, got %v", samplesDir, scanData)
	}

	// 3. Run End-to-End Go + Rust Pipeline on Carcassi-Op60-No7.pdf & koh.pdf
	cfg := config.NewDefaultConfig()
	cfg.OutputDir = tmp
	cfg.APIKey = ""
	cfg.VertexAI = false // Forces deterministic offline fallback for unit test

	pipe := jobs.NewPipeline(cfg, "")
	for _, pdfName := range []string{"Carcassi-Op60-No7.pdf", "koh.pdf"} {
		samplePath := filepath.Join(samplesDir, pdfName)
		sheet := drive.SheetFile{
			ID:        pdfName,
			Name:      pdfName,
			LocalPath: samplePath,
		}
		rep, err := pipe.ProcessSingleSheet(sheet, tmp)
		if err != nil {
			t.Fatalf("ProcessSingleSheet(%s) failed: %v", pdfName, err)
		}
		if rep.OutputPath == "" {
			t.Fatalf("expected OutputPath for %s", pdfName)
		}
		outBytes, err := os.ReadFile(rep.OutputPath)
		if err != nil {
			t.Fatalf("failed to read generated PDF %s: %v", rep.OutputPath, err)
		}
		if !bytes.HasPrefix(outBytes, []byte("%PDF")) || len(outBytes) < 5000 {
			t.Fatalf("generated PDF %s is invalid (size=%d)", rep.OutputPath, len(outBytes))
		}
	}
}
