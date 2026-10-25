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

//! Data models shared between the Rust PDF Vision/Annotation Engine and the Go Orchestrator.

use serde::{Deserialize, Serialize};

/// Detected staff system on a music sheet page (in PDF points, origin at bottom-left).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct StaffSystem {
    /// 1-based system index on the page (1 = topmost system)
    pub index: usize,
    /// Top of the upper staff (PDF points from bottom)
    pub y_top_pt: f64,
    /// Bottom of the system (PDF points from bottom)
    pub y_bottom_pt: f64,
    /// Recommended Y coordinate in PDF points to place chord pills
    pub chord_y_pt: f64,
    /// Height of the upper staff in PDF points (reflects note/staff scale)
    #[serde(default = "default_treble_height")]
    pub treble_height_pt: f64,
}

fn default_treble_height() -> f64 {
    20.0
}

/// Positioned text/chord token extracted from the PDF vector stream.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ExtractedTextToken {
    pub page_num: usize,
    pub x_pt: f64,
    pub y_pt: f64,
    pub token: String,
}

/// Layout metadata, ink density grid, and rendered PNG paths for a single PDF page.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PageLayout {
    pub page_num: usize,
    pub width_pt: f64,
    pub height_pt: f64,
    pub systems: Vec<StaffSystem>,
    pub bottom_free_pt: f64,
    /// Path to the clean rendered page PNG (if within first 6 pages)
    #[serde(default)]
    pub clean_png_path: String,
    /// Path to the coordinate guide PNG (with red X rulers and S1..Sn markers)
    #[serde(default)]
    pub guide_png_path: String,
    /// Downsampled occupancy map (base64-encoded 0..255 dark density per cell)
    #[serde(default)]
    pub ink_grid_b64: String,
    #[serde(default)]
    pub ink_cols: usize,
    #[serde(default)]
    pub ink_rows: usize,
}

/// Complete output of `akkord-pdf-engine layout <input.pdf> <work_dir>`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LayoutExtractionResult {
    pub detected_title: String,
    pub chord_tokens: Vec<ExtractedTextToken>,
    pub pages: Vec<PageLayout>,
}

/// A single chord symbol or chord review badge positioned on the score.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChordAnnotation {
    pub page_num: usize,
    pub system_index: usize,
    pub x_pt: f64,
    #[serde(default)]
    pub y_pt: Option<f64>,
    pub chord: String,
    #[serde(default = "default_status")]
    pub status: String,
    #[serde(default)]
    pub suggested_chord: Option<String>,
    #[serde(default)]
    pub measure_number: Option<i32>,
    #[serde(default)]
    pub note: Option<String>,
}

fn default_status() -> String {
    "added".to_string()
}

/// Counterpoint or walking-bass proposal for a specific measure/chord.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BassLineProposal {
    #[serde(default)]
    pub measure_number: Option<i32>,
    pub original_chord: String,
    pub proposed_slash_chord: String,
    #[serde(default)]
    pub melody_note: Option<String>,
    #[serde(default = "default_technique")]
    pub technique: String,
    pub explanation: String,
}

fn default_technique() -> String {
    "counterpoint".to_string()
}

/// 6-string guitar chord diagram specification.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GuitarDiagram {
    pub name: String,
    pub frets: Vec<String>,
}

/// Token consumption and estimated monetary cost for a single Gemini analysis.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TokenUsageStats {
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub input_tokens: i64,
    #[serde(default)]
    pub output_tokens: i64,
    #[serde(default)]
    pub thinking_tokens: i64,
    #[serde(default)]
    pub cached_tokens: i64,
    #[serde(default)]
    pub total_tokens: i64,
    #[serde(default)]
    pub estimated_cost_usd: f64,
    #[serde(default)]
    pub estimated_cost_eur: f64,
    #[serde(default)]
    pub source: String,
}

/// Complete structured output from Gemini / Harmony Engine for a music sheet PDF.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HarmonyAnalysisResult {
    pub is_music_sheet: bool,
    pub has_existing_chords: bool,
    pub title: String,
    pub detected_key: String,
    pub overall_summary: String,
    #[serde(default = "default_accuracy")]
    pub accuracy_score: i32,
    #[serde(default)]
    pub annotations: Vec<ChordAnnotation>,
    #[serde(default)]
    pub chord_diagrams: Vec<GuitarDiagram>,
    #[serde(default)]
    pub bass_line_proposals: Vec<BassLineProposal>,
    #[serde(default)]
    pub slash_chord_notes: Vec<String>,
    #[serde(default)]
    pub review_improvements: Vec<String>,
    #[serde(default)]
    pub review_missing: Vec<String>,
    #[serde(default)]
    pub review_correct: Vec<String>,
    #[serde(default)]
    pub token_usage: Option<TokenUsageStats>,
}

fn default_accuracy() -> i32 {
    100
}

/// Input payload for `akkord-pdf-engine annotate`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnnotateRequest {
    pub input_pdf_path: String,
    pub output_pdf_path: String,
    pub language: String,
    pub layouts: Vec<PageLayout>,
    pub result: HarmonyAnalysisResult,
}
