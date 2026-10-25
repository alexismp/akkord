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

// Package rustbridge invokes the native Rust `akkord-pdf-engine` binary for layout detection and vector PDF annotation.
package rustbridge

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os/exec"

	"github.com/alexismp/akkord/internal/config"
)

// StaffSystem represents a detected staff system on a music sheet page (in PDF points, origin at bottom-left).
type StaffSystem struct {
	Index          int     `json:"index"`
	YTopPt         float64 `json:"y_top_pt"`
	YBottomPt      float64 `json:"y_bottom_pt"`
	ChordYPt       float64 `json:"chord_y_pt"`
	TrebleHeightPt float64 `json:"treble_height_pt"`
}

// ExtractedTextToken represents a positioned text/chord token extracted from the PDF vector stream.
type ExtractedTextToken struct {
	PageNum int     `json:"page_num"`
	XPt     float64 `json:"x_pt"`
	YPt     float64 `json:"y_pt"`
	Token   string  `json:"token"`
}

// PageLayout holds layout metadata, 2pt ink density grid, and rendered PNG paths for a single PDF page.
type PageLayout struct {
	PageNum      int           `json:"page_num"`
	WidthPt      float64       `json:"width_pt"`
	HeightPt     float64       `json:"height_pt"`
	Systems      []StaffSystem `json:"systems"`
	BottomFreePt float64       `json:"bottom_free_pt"`
	CleanPNGPath string        `json:"clean_png_path,omitempty"`
	GuidePNGPath string        `json:"guide_png_path,omitempty"`
	InkGridB64   string        `json:"ink_grid_b64,omitempty"`
	InkCols      int           `json:"ink_cols,omitempty"`
	InkRows      int           `json:"ink_rows,omitempty"`
}

// LayoutExtractionResult is the output of `akkord-pdf-engine layout <input.pdf> <work_dir>`.
type LayoutExtractionResult struct {
	DetectedTitle string               `json:"detected_title"`
	ChordTokens   []ExtractedTextToken `json:"chord_tokens"`
	Pages         []PageLayout         `json:"pages"`
}

// ChordAnnotation represents a single chord symbol or chord review badge positioned on the score.
type ChordAnnotation struct {
	PageNum        int      `json:"page_num"`
	SystemIndex    int      `json:"system_index"`
	XPt            float64  `json:"x_pt"`
	YPt            *float64 `json:"y_pt,omitempty"`
	Chord          string   `json:"chord"`
	Status         string   `json:"status"`
	SuggestedChord string   `json:"suggested_chord,omitempty"`
	MeasureNumber  *int     `json:"measure_number,omitempty"`
	Note           string   `json:"note,omitempty"`
}

// BassLineProposal represents a counterpoint or walking-bass proposal for a specific measure/chord.
type BassLineProposal struct {
	MeasureNumber      *int   `json:"measure_number,omitempty"`
	OriginalChord      string `json:"original_chord"`
	ProposedSlashChord string `json:"proposed_slash_chord"`
	MelodyNote         string `json:"melody_note,omitempty"`
	Technique          string `json:"technique"`
	Explanation        string `json:"explanation"`
}

// GuitarDiagram represents a 6-string guitar chord diagram specification.
type GuitarDiagram struct {
	Name  string   `json:"name"`
	Frets []string `json:"frets"`
}

// TokenUsageStats tracks token consumption and estimated monetary cost for a single Gemini analysis.
type TokenUsageStats struct {
	Model            string  `json:"model"`
	InputTokens      int     `json:"input_tokens"`
	OutputTokens     int     `json:"output_tokens"`
	ThinkingTokens   int     `json:"thinking_tokens"`
	CachedTokens     int     `json:"cached_tokens"`
	TotalTokens      int     `json:"total_tokens"`
	EstimatedCostUSD float64 `json:"estimated_cost_usd"`
	EstimatedCostEUR float64 `json:"estimated_cost_eur"`
	Source           string  `json:"source"`
}

// HarmonyAnalysisResult is the complete structured output from Gemini / HarmonyEngine for a music sheet PDF.
type HarmonyAnalysisResult struct {
	IsMusicSheet       bool               `json:"is_music_sheet"`
	HasExistingChords  bool               `json:"has_existing_chords"`
	Title              string             `json:"title"`
	DetectedKey        string             `json:"detected_key"`
	OverallSummary     string             `json:"overall_summary"`
	AccuracyScore      int                `json:"accuracy_score"`
	Annotations        []ChordAnnotation  `json:"annotations,omitempty"`
	ChordDiagrams      []GuitarDiagram    `json:"chord_diagrams,omitempty"`
	BassLineProposals  []BassLineProposal `json:"bass_line_proposals,omitempty"`
	SlashChordNotes    []string           `json:"slash_chord_notes,omitempty"`
	ReviewImprovements []string           `json:"review_improvements,omitempty"`
	ReviewMissing      []string           `json:"review_missing,omitempty"`
	ReviewCorrect      []string           `json:"review_correct,omitempty"`
	TokenUsage         *TokenUsageStats   `json:"token_usage,omitempty"`
}

// AnnotateRequest is passed to `akkord-pdf-engine annotate -`.
type AnnotateRequest struct {
	InputPDFPath  string                `json:"input_pdf_path"`
	OutputPDFPath string                `json:"output_pdf_path"`
	Language      string                `json:"language"`
	Layouts       []PageLayout          `json:"layouts"`
	Result        HarmonyAnalysisResult `json:"result"`
}

// Engine wraps the native Rust `akkord-pdf-engine` binary.
type Engine struct {
	BinPath string
}

// NewEngine creates a Rust PDF engine wrapper.
func NewEngine(binPath string) *Engine {
	if binPath == "" {
		binPath = config.ResolveRustEngineBin()
	}
	return &Engine{BinPath: binPath}
}

// AnalyzeLayout runs `akkord-pdf-engine layout <pdfPath> <workDir>` and parses the resulting LayoutExtractionResult.
func (e *Engine) AnalyzeLayout(pdfPath, workDir string) (*LayoutExtractionResult, error) {
	cmd := exec.Command(e.BinPath, "layout", pdfPath, workDir)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("rust pdf engine layout failed (%v): %s", err, stderr.String())
	}
	var res LayoutExtractionResult
	if err := json.Unmarshal(stdout.Bytes(), &res); err != nil {
		return nil, fmt.Errorf("failed to parse rust layout JSON: %w", err)
	}
	return &res, nil
}

// AnnotatePDF runs `akkord-pdf-engine annotate -` passing the AnnotateRequest JSON via stdin.
func (e *Engine) AnnotatePDF(req AnnotateRequest) error {
	payload, err := json.Marshal(req)
	if err != nil {
		return fmt.Errorf("failed to marshal AnnotateRequest: %w", err)
	}
	cmd := exec.Command(e.BinPath, "annotate", "-")
	cmd.Stdin = bytes.NewReader(payload)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("rust pdf engine annotate failed (%v): %s", err, stderr.String())
	}
	return nil
}
