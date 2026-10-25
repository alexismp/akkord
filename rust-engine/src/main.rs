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

//! `akkord-pdf-engine`: Native Rust PDF Vision, Staff/TAB Detection, Ink-Collision Avoidance,
//! and Vector Annotation Engine for Akkord.
//!
//! Subcommands:
//!   - `akkord-pdf-engine layout <input.pdf> <work_dir>`
//!     Renders pages, detects staff systems and 2pt ink grids, generates clean & guide PNGs,
//!     extracts PDF text/chord tokens, and writes `LayoutExtractionResult` JSON to stdout.
//!   - `akkord-pdf-engine annotate <request.json>`
//!     Reads `AnnotateRequest` JSON (from file or `-` for stdin) and produces the annotated PDF.

pub mod annotator;
pub mod layout;
pub mod models;

use std::env;
use std::fs;
use std::io::{self, Read};
use std::path::Path;

use anyhow::{Context, Result};

use crate::annotator::annotate_music_sheet_pdf;
use crate::layout::analyze_pdf_layout_full;
use crate::models::AnnotateRequest;

fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        anyhow::bail!(
            "Usage:\n  {} layout <input.pdf> <work_dir>\n  {} annotate <request.json|->",
            args.first().map(String::as_str).unwrap_or("akkord-pdf-engine"),
            args.first().map(String::as_str).unwrap_or("akkord-pdf-engine")
        );
    }

    match args[1].as_str() {
        "layout" => {
            if args.len() < 4 {
                anyhow::bail!("Usage: akkord-pdf-engine layout <input.pdf> <work_dir>");
            }
            let pdf_path = Path::new(&args[2]);
            let work_dir = Path::new(&args[3]);
            let res = analyze_pdf_layout_full(pdf_path, work_dir)?;
            let json_out = serde_json::to_string(&res)?;
            println!("{json_out}");
        }
        "annotate" => {
            if args.len() < 3 {
                anyhow::bail!("Usage: akkord-pdf-engine annotate <request.json|->");
            }
            let raw_json = if args[2] == "-" {
                let mut s = String::new();
                io::stdin().read_to_string(&mut s)?;
                s
            } else {
                fs::read_to_string(&args[2])
                    .with_context(|| format!("Failed to read {}", args[2]))?
            };
            let req: AnnotateRequest =
                serde_json::from_str(&raw_json).context("Invalid AnnotateRequest JSON")?;
            annotate_music_sheet_pdf(&req)?;
            println!(r#"{{"status":"ok","output_pdf_path":{:?}}}"#, req.output_pdf_path);
        }
        other => {
            anyhow::bail!("Unknown subcommand '{other}'. Expected 'layout' or 'annotate'.");
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::annotator::extract_compact_chord_symbol;
    use crate::layout::clean_single_staff_cluster;
    use crate::models::{
        BassLineProposal, ChordAnnotation, GuitarDiagram, HarmonyAnalysisResult,
    };

    #[test]
    fn test_clean_single_staff_cluster_strips_outer_beams() {
        // 5 staff lines with step 5.0 (700, 695, 690, 685, 680) plus a close 16th-note beam at 674.0 (diff 6.0 -> >14% from 5.0)
        let raw = vec![700.0, 695.0, 690.0, 685.0, 680.0, 674.0];
        let cleaned = clean_single_staff_cluster(&raw);
        assert_eq!(cleaned, vec![700.0, 695.0, 690.0, 685.0, 680.0]);
    }

    #[test]
    fn test_extract_compact_chord_symbol_cleaning() {
        let (sym, extra) =
            extract_compact_chord_symbol(Some("B7/F#[x-2-1-2-0-2] (Si 7/Fa#)"));
        assert_eq!(sym, "B7/F#");
        assert!(extra.contains("[x-2-1-2-0-2]"));

        let (sym2, _) = extract_compact_chord_symbol(Some("A7/Cdim7/C#7"));
        assert_eq!(sym2, "A7/C#");
    }

    #[test]
    fn test_carcassi_and_koh_layout_and_annotation() -> Result<()> {
        let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
        let repo_root = manifest_dir.parent().unwrap();
        let carcassi_pdf = repo_root.join("samples/Carcassi-Op60-No7.pdf");
        let koh_pdf = repo_root.join("samples/koh.pdf");

        let work_dir = std::env::temp_dir().join("akkord_rust_test_layout");
        let _ = fs::remove_dir_all(&work_dir);

        if carcassi_pdf.is_file() {
            let res = analyze_pdf_layout_full(&carcassi_pdf, &work_dir)?;
            assert_eq!(res.pages.len(), 2);
            // Page 1 of Carcassi Op. 60 No. 7 has 9 staff systems
            assert_eq!(res.pages[0].systems.len(), 9);
        }

        if koh_pdf.is_file() {
            let work_dir2 = std::env::temp_dir().join("akkord_rust_test_koh");
            let _ = fs::remove_dir_all(&work_dir2);
            let res = analyze_pdf_layout_full(&koh_pdf, &work_dir2)?;
            assert_eq!(res.pages.len(), 2);
            assert_eq!(res.pages[0].systems.len(), 4);

            // Test annotating koh.pdf in both add_chords and analyze modes
            let out_pdf = work_dir2.join("koh-annotated.pdf");
            let req = AnnotateRequest {
                input_pdf_path: koh_pdf.to_string_lossy().to_string(),
                output_pdf_path: out_pdf.to_string_lossy().to_string(),
                language: "en".to_string(),
                layouts: res.pages.clone(),
                result: HarmonyAnalysisResult {
                    is_music_sheet: true,
                    has_existing_chords: true,
                    title: "Kon'".to_string(),
                    detected_key: "A minor (Am)".to_string(),
                    overall_summary: "Contrapuntal walking bass review.".to_string(),
                    accuracy_score: 88,
                    annotations: vec![
                        ChordAnnotation {
                            page_num: 1,
                            system_index: 1,
                            x_pt: 96.0,
                            y_pt: None,
                            chord: "Am".to_string(),
                            status: "improve".to_string(),
                            suggested_chord: Some("Am/C".to_string()),
                            measure_number: Some(1),
                            note: Some("First inversion avoids doubling A in melody.".to_string()),
                        },
                        ChordAnnotation {
                            page_num: 1,
                            system_index: 1,
                            x_pt: 240.0,
                            y_pt: None,
                            chord: "E7/G#".to_string(),
                            status: "missing".to_string(),
                            suggested_chord: Some("E7/G#".to_string()),
                            measure_number: Some(2),
                            note: Some("Leading-tone bass G# resolving to A.".to_string()),
                        },
                    ],
                    chord_diagrams: vec![GuitarDiagram {
                        name: "Am".to_string(),
                        frets: vec![
                            "x".into(),
                            "0".into(),
                            "2".into(),
                            "2".into(),
                            "1".into(),
                            "0".into(),
                        ],
                    }],
                    bass_line_proposals: vec![BassLineProposal {
                        measure_number: Some(1),
                        original_chord: "Am".to_string(),
                        proposed_slash_chord: "Am/C".to_string(),
                        melody_note: Some("A".to_string()),
                        technique: "counterpoint".to_string(),
                        explanation: "Contrary motion bass.".to_string(),
                    }],
                    slash_chord_notes: vec![],
                    review_improvements: vec!["m.1: Am -> Am/C".to_string()],
                    review_missing: vec!["m.2: + E7/G#".to_string()],
                    review_correct: vec!["Other measures accurate.".to_string()],
                    token_usage: None,
                },
            };
            annotate_music_sheet_pdf(&req)?;
            assert!(out_pdf.is_file());
            let saved_doc = lopdf::Document::load(&out_pdf)?;
            // 2 original pages + 1 appended harmonic analysis notes page = 3 pages
            assert_eq!(saved_doc.get_pages().len(), 3);
        }

        Ok(())
    }
}
