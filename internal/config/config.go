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

// Package config provides runtime configuration andlocalization (i18n) for the Go Akkord server and CLI.
package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

const (
	DefaultModel        = "gemini-4-argon"
	DefaultGCPProject   = "alexismp-runner"
	DefaultGCPLocation  = "europe-west1"
	DefaultGCSBucket    = "alexismp-runner-akkord-data"
	DefaultTasksQueue   = "akkord-pdf-queue"
	DefaultServiceURL   = "https://akkord-2500276981.europe-west1.run.app"
	DefaultLanguage     = "fr"
	DailyFileLimit      = 25
	DailyReportHour     = 18
	AdminEmail          = "alexis.mp@gmail.com"
	DefaultOAuthClient  = "2500276981-gmjvvn9ucbagv4g44n7rsdq9qo688hpb.apps.googleusercontent.com"
	DefaultRedirectURI  = "https://akkord-2500276981.europe-west1.run.app/auth/callback"
	SessionCookieName   = "akkord_session"
)

var AvailableModels = []string{
	"gemini-4-argon",
	"gemini-3.8-flash",
	"gemini-3.5-flash-lite",
	"gemini-2.5-pro",
	"gemini-2.5-flash",
}

// AkkordConfig holds runtime settings for processing music sheets.
type AkkordConfig struct {
	Model                 string
	VertexAI              bool
	Project               string
	Location              string
	APIKey                string
	Language              string
	OutputDir             string
	UploadToDrive         bool
	GoogleCredentialsPath string
	RustEngineBin         string
}

// NewDefaultConfig creates a validated AkkordConfig from environment variables.
func NewDefaultConfig() AkkordConfig {
	model := EnvOr("AKKORD_MODEL", DefaultModel)
	vertexRaw := strings.ToLower(EnvOr("AKKORD_VERTEXAI", "true"))
	vertexAI := vertexRaw == "1" || vertexRaw == "true" || vertexRaw == "yes"
	project := EnvOr("AKKORD_GCP_PROJECT", EnvOr("GOOGLE_CLOUD_PROJECT", DefaultGCPProject))
	location := EnvOr("GOOGLE_CLOUD_LOCATION", DefaultGCPLocation)
	apiKey := EnvOr("AKKORD_GEMINI_API_KEY", EnvOr("GEMINI_API_KEY", ""))
	lang := NormalizeLanguage(EnvOr("AKKORD_LANG", DefaultLanguage))
	outDir := EnvOr("AKKORD_OUTPUT_DIR", DefaultOutputDir())
	_ = os.MkdirAll(outDir, 0o755)

	return AkkordConfig{
		Model:                 model,
		VertexAI:              vertexAI,
		Project:               project,
		Location:              location,
		APIKey:                apiKey,
		Language:              lang,
		OutputDir:             outDir,
		UploadToDrive:         false,
		GoogleCredentialsPath: os.Getenv("GOOGLE_APPLICATION_CREDENTIALS"),
		RustEngineBin:         ResolveRustEngineBin(),
	}
}

// DefaultOutputDir returns "outputs" locally if it exists, or "/tmp/akkord_outputs" on Cloud Run.
func DefaultOutputDir() string {
	if st, err := os.Stat("outputs"); err == nil && st.IsDir() {
		abs, err := filepath.Abs("outputs")
		if err == nil {
			return abs
		}
		return "outputs"
	}
	return "/tmp/akkord_outputs"
}

// ResolveRustEngineBin locates the compiled Rust `akkord-pdf-engine` binary.
func ResolveRustEngineBin() string {
	if envBin := strings.TrimSpace(os.Getenv("AKKORD_RUST_ENGINE_BIN")); envBin != "" {
		return envBin
	}
	candidates := []string{
		"/usr/local/bin/akkord-pdf-engine",
		"rust-engine/target/release/akkord-pdf-engine",
		"rust-engine/target/debug/akkord-pdf-engine",
		"../rust-engine/target/release/akkord-pdf-engine",
		"../../rust-engine/target/release/akkord-pdf-engine",
	}
	for _, c := range candidates {
		if st, err := os.Stat(c); err == nil && !st.IsDir() {
			if abs, err := filepath.Abs(c); err == nil {
				return abs
			}
			return c
		}
	}
	return "akkord-pdf-engine"
}

// EnvOr returns the environment variable value if non-empty, or fallback.
func EnvOr(key, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return fallback
}

// NormalizeLanguage validates and normalizes language code ("fr" or "en").
func NormalizeLanguage(lang string) string {
	l := strings.ToLower(strings.TrimSpace(lang))
	if l == "en" {
		return "en"
	}
	return "fr"
}

// ValidateLanguage returns an error if lang is neither "fr" nor "en".
func ValidateLanguage(lang string) (string, error) {
	l := strings.ToLower(strings.TrimSpace(lang))
	if l == "" {
		return DefaultLanguage, nil
	}
	if l != "fr" && l != "en" {
		return "", fmt.Errorf("unsupported language '%s'. Choose from: ('fr', 'en')", lang)
	}
	return l, nil
}

// FileSuffix returns the localized output PDF suffix for "analyze" or "add_chords" mode.
func FileSuffix(lang string, hasExistingChords bool) string {
	isFr := NormalizeLanguage(lang) == "fr"
	if hasExistingChords {
		if isFr {
			return "-analyse-accords.pdf"
		}
		return "-chord-analysis.pdf"
	}
	if isFr {
		return "-avec-accords.pdf"
	}
	return "-with-chords.pdf"
}

// PromptDirective returns the localized Gemini prompt instruction block.
func PromptDirective(lang string) string {
	if NormalizeLanguage(lang) == "en" {
		return "Respond strictly in English. " +
			"Use standard international chord notation (e.g., 'Am', 'Dm/F', 'E7/G#', 'G/B'). " +
			"CRITICAL COUNTERPOINT & WALKING BASS RULE: " +
			"Avoid systematically placing the chord root in the bass or doubling the melody note! " +
			"Use counterpoint rules (contrary motion against the melody, placing the 3rd, 5th, or 7th in the bass when the melody plays the root) " +
			"and walking bass movement (stepwise diatonic or chromatic bass lines across measures, e.g., Am -> Am/G -> Dm/F -> E7). " +
			"Populate `bass_line_proposals` with specific measure-by-measure bass proposals explaining how each slash chord avoids melody doubling or root monotony. " +
			"Write all harmonic explanations, counterpoint/walking-bass notes, and review comments in clear English."
	}
	return "Respond strictly in French (Français). " +
		"For guitar chord diagram titles, include both standard international notation " +
		"and French Solfège in parentheses, e.g., 'Am (La m)', 'Dm (Ré m)', 'E (Mi)', " +
		"'C (Do)', 'G (Sol)', 'F (Fa)', 'A7 (La 7)'. " +
		"For inline staff chord symbols, keep standard international symbols (e.g., 'Am', 'Dm/F', 'G/B', 'E7/G#') " +
		"so they stay compact above the staff. " +
		"CRITICAL COUNTERPOINT & WALKING BASS RULE: " +
		"Avoid the trap of systematically using the root note (fondamentale) in the bass or doubling the melody note! " +
		"Apply strict counterpoint rules (contrary motion / mouvement contraire against the melody, using the 3rd, 5th, or 7th in the bass when the melody plays the root or moves in parallel) " +
		"and walking bass principles (conjoint diatonic or chromatic bass lines connecting chords across measures, e.g. Am -> Am/G -> Dm/F -> E7 or Em -> D/F# -> G -> E7/G# -> Am). " +
		"Populate `bass_line_proposals` with specific measure-by-measure bass proposals explaining how each slash chord avoids melody doubling or root monotony. " +
		"Write all harmonic explanations, counterpoint/walking-bass notes, and review comments in French."
}
