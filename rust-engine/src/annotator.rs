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

//! Native Rust PDF Vector Overlay & Report Page Generator using `lopdf`.
//!
//! Draws:
//! - Uniform-sized chord + superscript reference badges (`E7/B ¹`, `Gm/Bb ²`) in Analyze mode
//! - Adaptive, ink-aware, non-overlapping blue chord pills in Add Chords mode
//! - Multi-row 6-string guitar fretboard diagrams (`x`, `0`, `1..4`, barre fret labels)
//! - Appended harmonic analysis report pages with wrapped header card, numbered footnotes,
//!   counterpoint/walking-bass bullet sections, and guitar chord diagrams.

use std::collections::BTreeMap;
use std::fmt::Write as _;
use std::path::Path;

use anyhow::{Context, Result};
use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use lopdf::{dictionary, Document, Object, ObjectId, Stream};
use regex::Regex;

use crate::layout::{find_clear_rect, ink_density_in_rect, normalize_music_ascii};
use crate::models::{
    AnnotateRequest, ChordAnnotation, GuitarDiagram, HarmonyAnalysisResult, PageLayout,
};

#[derive(Debug, Clone, Copy)]
pub struct PillStyle {
    pub fill: (f64, f64, f64),
    pub stroke: (f64, f64, f64),
    pub text: (f64, f64, f64),
}

pub fn get_pill_style(key: &str) -> PillStyle {
    match key {
        "correct" => PillStyle {
            fill: hex_to_rgb("#eafaf1"),
            stroke: hex_to_rgb("#27ae60"),
            text: hex_to_rgb("#145a32"),
        },
        "improve" => PillStyle {
            fill: hex_to_rgb("#fff3cd"),
            stroke: hex_to_rgb("#b45309"),
            text: hex_to_rgb("#451a03"),
        },
        "missing" => PillStyle {
            fill: hex_to_rgb("#fdedec"),
            stroke: hex_to_rgb("#c0392b"),
            text: hex_to_rgb("#78281f"),
        },
        _ => PillStyle {
            fill: hex_to_rgb("#eef6fb"),
            stroke: hex_to_rgb("#2980b9"),
            text: hex_to_rgb("#0b3c5d"),
        },
    }
}

pub fn hex_to_rgb(hex: &str) -> (f64, f64, f64) {
    let h = hex.trim_start_matches('#');
    if h.len() == 6 {
        let r = u8::from_str_radix(&h[0..2], 16).unwrap_or(0) as f64 / 255.0;
        let g = u8::from_str_radix(&h[2..4], 16).unwrap_or(0) as f64 / 255.0;
        let b = u8::from_str_radix(&h[4..6], 16).unwrap_or(0) as f64 / 255.0;
        (r, g, b)
    } else {
        (0.0, 0.0, 0.0)
    }
}

/// Extract compact chord symbol (`Bm(maj7)/A#`) and optional extra text, identical to Python `extract_compact_chord_symbol`.
pub fn extract_compact_chord_symbol(raw: Option<&str>) -> (String, String) {
    let s = match raw {
        Some(v) => normalize_music_ascii(v).trim().to_string(),
        None => return (String::new(), String::new()),
    };
    if s.is_empty() {
        return (String::new(), String::new());
    }

    let mut cleaned = if s.contains('|') {
        s.split('|')
            .map(str::trim)
            .find(|seg| !seg.is_empty())
            .unwrap_or("")
            .to_string()
    } else {
        s
    };

    let mut bracket_extra = String::new();
    if let Some(idx) = cleaned.find('[') {
        let after = cleaned[idx..].trim().to_string();
        cleaned = cleaned[..idx].trim().to_string();
        bracket_extra = after;
    }

    let mut parts = cleaned.splitn(2, char::is_whitespace);
    let mut symbol = parts
        .next()
        .unwrap_or("")
        .trim_end_matches(&[',', ';', ':'][..])
        .to_string();
    let mut extra = parts.next().unwrap_or("").trim().to_string();
    if !bracket_extra.is_empty() {
        extra = format!("{extra} {bracket_extra}").trim().to_string();
    }

    if symbol.matches('/').count() > 1 {
        let slash_parts: Vec<&str> = symbol
            .split('/')
            .map(str::trim)
            .filter(|p| !p.is_empty())
            .collect();
        let base_chord = slash_parts.first().copied().unwrap_or("");
        let note_re = Regex::new(r"^[A-G][#b]?$").unwrap();
        let prefix_re = Regex::new(r"^([A-G][#b]?)").unwrap();
        let mut chosen_bass = String::new();
        for &sp in slash_parts.iter().skip(1) {
            if note_re.is_match(sp) {
                chosen_bass = sp.to_string();
                break;
            }
        }
        if chosen_bass.is_empty() && slash_parts.len() > 1 {
            for &sp in slash_parts.iter().skip(1) {
                if let Some(cap) = prefix_re.captures(sp) {
                    let b = &cap[1];
                    if !base_chord.starts_with(b) {
                        chosen_bass = b.to_string();
                        if sp.contains('#') || sp.contains('b') {
                            break;
                        }
                    }
                }
            }
        }
        symbol = if !chosen_bass.is_empty() {
            format!("{base_chord}/{chosen_bass}")
        } else {
            base_chord.to_string()
        };
    }

    if let Some(open_idx) = symbol.find('(') {
        let prefix = &symbol[..open_idx];
        let inner = symbol[open_idx + 1..].trim_end_matches(')').to_lowercase();
        if !prefix.is_empty()
            && ["do", "ré", "re", "mi", "fa", "sol", "la", "si", " "]
                .iter()
                .any(|sol| inner.contains(sol))
        {
            symbol = prefix.to_string();
        }
    }

    if symbol.chars().count() > 16 {
        symbol = symbol.chars().take(16).collect();
    }
    (symbol, extra)
}

/// Transliterate Cyrillic characters to readable Latin equivalents when writing to standard Type1 WinAnsi PDF streams,
/// while preserving full French/English accents (é, è, ê, à, ç, ô, û, œ, «, », °, •) in WinAnsiEncoding.
pub fn sanitize_pdf_text(text: &str) -> String {
    let replaced = text
        .replace('↻', "*")
        .replace('✓', "OK ")
        .replace('♯', "#")
        .replace('♭', "b")
        .replace('♮', "")
        .replace('𝄪', "##")
        .replace('→', "->")
        .replace('ø', "m7b5")
        .replace('—', "-")
        .replace('–', "-")
        .replace('…', "...");

    let mut out = String::with_capacity(replaced.len());
    for ch in replaced.chars() {
        if let Some(lat) = cyrillic_to_latin(ch) {
            out.push_str(lat);
        } else {
            out.push(ch);
        }
    }
    let trimmed = out.trim().to_string();
    if trimmed.is_empty() {
        "Score".to_string()
    } else {
        trimmed
    }
}

fn cyrillic_to_latin(ch: char) -> Option<&'static str> {
    match ch {
        'А' => Some("A"),
        'Б' => Some("B"),
        'В' => Some("V"),
        'Г' => Some("G"),
        'Д' => Some("D"),
        'Е' => Some("E"),
        'Ё' => Some("Yo"),
        'Ж' => Some("Zh"),
        'З' => Some("Z"),
        'И' => Some("I"),
        'Й' => Some("Y"),
        'К' => Some("K"),
        'Л' => Some("L"),
        'М' => Some("M"),
        'Н' => Some("N"),
        'О' => Some("O"),
        'П' => Some("P"),
        'Р' => Some("R"),
        'С' => Some("S"),
        'Т' => Some("T"),
        'У' => Some("U"),
        'Ф' => Some("F"),
        'Х' => Some("Kh"),
        'Ц' => Some("Ts"),
        'Ч' => Some("Ch"),
        'Ш' => Some("Sh"),
        'Щ' => Some("Shch"),
        'Ъ' | 'Ь' => Some("'"),
        'Ы' => Some("Y"),
        'Э' => Some("E"),
        'Ю' => Some("Yu"),
        'Я' => Some("Ya"),
        'а' => Some("a"),
        'б' => Some("b"),
        'в' => Some("v"),
        'г' => Some("g"),
        'д' => Some("d"),
        'е' => Some("e"),
        'ё' => Some("yo"),
        'ж' => Some("zh"),
        'з' => Some("z"),
        'и' => Some("i"),
        'й' => Some("y"),
        'к' => Some("k"),
        'л' => Some("l"),
        'м' => Some("m"),
        'н' => Some("n"),
        'о' => Some("o"),
        'п' => Some("p"),
        'р' => Some("r"),
        'с' => Some("s"),
        'т' => Some("t"),
        'у' => Some("u"),
        'ф' => Some("f"),
        'х' => Some("kh"),
        'ц' => Some("ts"),
        'ч' => Some("ch"),
        'ш' => Some("sh"),
        'щ' => Some("shch"),
        'ъ' | 'ь' => Some("'"),
        'ы' => Some("y"),
        'э' => Some("e"),
        'ю' => Some("yu"),
        'я' => Some("ya"),
        _ => None,
    }
}

/// Encode a UTF-8 string into a PDF literal string `(...)` using WinAnsiEncoding (CP1252).
fn encode_winansi_pdf_string(text: &str) -> String {
    let mut out = String::with_capacity(text.len() + 8);
    out.push('(');
    for ch in text.chars() {
        let byte: u8 = match ch {
            '\u{0020}'..='\u{007E}' | '\u{00A0}'..='\u{00FF}' => ch as u8,
            '•' => 0x95,
            '–' => 0x96,
            '—' => 0x97,
            '’' | '‘' => b'\'',
            '“' | '”' => b'"',
            'œ' => 0x9C,
            'Œ' => 0x8C,
            '€' => 0x80,
            _ => b'?',
        };
        match byte {
            b'(' => out.push_str("\\("),
            b')' => out.push_str("\\)"),
            b'\\' => out.push_str("\\\\"),
            0x20..=0x7E => out.push(byte as char),
            _ => {
                let _ = write!(out, "\\{:03o}", byte);
            }
        }
    }
    out.push(')');
    out
}

/// Accurate Helvetica/Arial string width estimator in PDF points.
pub fn string_width(text: &str, bold: bool, font_size: f64) -> f64 {
    let mut units = 0.0_f64;
    for ch in text.chars() {
        let w = match ch {
            ' ' | '.' | ',' | ':' | ';' | '!' | '|' | '\'' | 'i' | 'l' | 'I' | '1' => 0.28,
            '(' | ')' | '[' | ']' | '-' | '/' | 'f' | 'j' | 'r' | 't' => 0.34,
            'm' | 'w' | 'M' | 'W' => 0.84,
            'A'..='Z' => 0.68,
            '0'..='9' => 0.56,
            _ => 0.54,
        };
        units += if bold { w * 1.05 } else { w };
    }
    units * font_size
}

/// Lightweight PDF Content Stream builder supporting rounded rectangles, lines, circles, and styled text.
pub struct PdfCanvas {
    buf: String,
}

impl PdfCanvas {
    pub fn new() -> Self {
        Self {
            buf: String::with_capacity(4096),
        }
    }

    pub fn into_bytes(self) -> Vec<u8> {
        self.buf.into_bytes()
    }

    pub fn set_fill_rgb(&mut self, (r, g, b): (f64, f64, f64)) {
        let _ = writeln!(self.buf, "{r:.3} {g:.3} {b:.3} rg");
    }

    pub fn set_stroke_rgb(&mut self, (r, g, b): (f64, f64, f64)) {
        let _ = writeln!(self.buf, "{r:.3} {g:.3} {b:.3} RG");
    }

    pub fn set_line_width(&mut self, w: f64) {
        let _ = writeln!(self.buf, "{w:.2} w");
    }

    pub fn line(&mut self, x1: f64, y1: f64, x2: f64, y2: f64) {
        let _ = writeln!(self.buf, "{x1:.2} {y1:.2} m {x2:.2} {y2:.2} l S");
    }

    pub fn round_rect(&mut self, x: f64, y: f64, w: f64, h: f64, r: f64, fill: bool, stroke: bool) {
        let r = r.min(w / 2.0).min(h / 2.0).max(0.0);
        let k = 0.55228475 * r;
        let x0 = x;
        let y0 = y;
        let x1 = x + w;
        let y1 = y + h;
        let _ = writeln!(self.buf, "{:.2} {:.2} m", x0 + r, y0);
        let _ = writeln!(self.buf, "{:.2} {:.2} l", x1 - r, y0);
        let _ = writeln!(
            self.buf,
            "{:.2} {:.2} {:.2} {:.2} {:.2} {:.2} c",
            x1 - r + k,
            y0,
            x1,
            y0 + r - k,
            x1,
            y0 + r
        );
        let _ = writeln!(self.buf, "{:.2} {:.2} l", x1, y1 - r);
        let _ = writeln!(
            self.buf,
            "{:.2} {:.2} {:.2} {:.2} {:.2} {:.2} c",
            x1,
            y1 - r + k,
            x1 - r + k,
            y1,
            x1 - r,
            y1
        );
        let _ = writeln!(self.buf, "{:.2} {:.2} l", x0 + r, y1);
        let _ = writeln!(
            self.buf,
            "{:.2} {:.2} {:.2} {:.2} {:.2} {:.2} c",
            x0 + r - k,
            y1,
            x0,
            y1 - r + k,
            x0,
            y1 - r
        );
        let _ = writeln!(self.buf, "{:.2} {:.2} l", x0, y0 + r);
        let _ = writeln!(
            self.buf,
            "{:.2} {:.2} {:.2} {:.2} {:.2} {:.2} c",
            x0,
            y0 + r - k,
            x0 + r - k,
            y0,
            x0 + r,
            y0
        );
        let op = match (fill, stroke) {
            (true, true) => "B",
            (true, false) => "f",
            (false, true) => "S",
            (false, false) => "n",
        };
        let _ = writeln!(self.buf, "h {op}");
    }

    pub fn circle(&mut self, cx: f64, cy: f64, r: f64, fill: bool, stroke: bool) {
        let k = 0.55228475 * r;
        let _ = writeln!(self.buf, "{:.2} {:.2} m", cx + r, cy);
        let _ = writeln!(
            self.buf,
            "{:.2} {:.2} {:.2} {:.2} {:.2} {:.2} c",
            cx + r,
            cy + k,
            cx + k,
            cy + r,
            cx,
            cy + r
        );
        let _ = writeln!(
            self.buf,
            "{:.2} {:.2} {:.2} {:.2} {:.2} {:.2} c",
            cx - k,
            cy + r,
            cx - r,
            cy + k,
            cx - r,
            cy
        );
        let _ = writeln!(
            self.buf,
            "{:.2} {:.2} {:.2} {:.2} {:.2} {:.2} c",
            cx - r,
            cy - k,
            cx - k,
            cy - r,
            cx,
            cy - r
        );
        let _ = writeln!(
            self.buf,
            "{:.2} {:.2} {:.2} {:.2} {:.2} {:.2} c",
            cx + k,
            cy - r,
            cx + r,
            cy - k,
            cx + r,
            cy
        );
        let op = match (fill, stroke) {
            (true, true) => "B",
            (true, false) => "f",
            (false, true) => "S",
            (false, false) => "n",
        };
        let _ = writeln!(self.buf, "h {op}");
    }

    /// Draw text at `(x, y)` using `/F1` (Regular), `/F2` (Bold), or `/F3` (Italic).
    pub fn draw_string(&mut self, font_tag: &str, font_size: f64, x: f64, y: f64, text: &str) {
        let safe = sanitize_pdf_text(text);
        let encoded = encode_winansi_pdf_string(&safe);
        let _ = writeln!(
            self.buf,
            "BT /{font_tag} {font_size:.2} Tf 1 0 0 1 {x:.2} {y:.2} Tm {encoded} Tj ET"
        );
    }

    pub fn draw_centered_string(
        &mut self,
        font_tag: &str,
        font_size: f64,
        cx: f64,
        y: f64,
        text: &str,
    ) {
        let safe = sanitize_pdf_text(text);
        let w = string_width(&safe, font_tag == "F2", font_size);
        self.draw_string(font_tag, font_size, cx - w / 2.0, y, &safe);
    }

    pub fn draw_right_string(
        &mut self,
        font_tag: &str,
        font_size: f64,
        rx: f64,
        y: f64,
        text: &str,
    ) {
        let safe = sanitize_pdf_text(text);
        let w = string_width(&safe, font_tag == "F2", font_size);
        self.draw_string(font_tag, font_size, rx - w, y, &safe);
    }
}

/// Wrap text into lines guaranteed not to exceed `max_width_pt`.
pub fn wrap_pdf_line(text: &str, bold: bool, font_size: f64, max_width_pt: f64) -> Vec<String> {
    let cleaned = sanitize_pdf_text(text);
    if cleaned.is_empty() {
        return Vec::new();
    }
    let mut lines = Vec::new();
    let mut current = String::new();
    for word in cleaned.split_whitespace() {
        let candidate = if current.is_empty() {
            word.to_string()
        } else {
            format!("{current} {word}")
        };
        if string_width(&candidate, bold, font_size) <= max_width_pt {
            current = candidate;
        } else {
            if !current.is_empty() {
                lines.push(current);
            }
            current = word.to_string();
        }
    }
    if !current.is_empty() {
        lines.push(current);
    }
    lines
}

fn format_pill_text(ann: &ChordAnnotation, has_existing_chords: bool) -> String {
    let (mut base_chord, _) = extract_compact_chord_symbol(Some(&ann.chord));
    if base_chord.is_empty() {
        base_chord = ann.chord.trim().chars().take(14).collect();
    }
    if !has_existing_chords || ann.status == "added" {
        return sanitize_pdf_text(&base_chord);
    }
    if ann.status == "correct" {
        return sanitize_pdf_text(&format!("OK {base_chord}"));
    }
    if ann.status == "improve" {
        let (target, _) = extract_compact_chord_symbol(ann.suggested_chord.as_deref());
        if !target.is_empty() && target != base_chord {
            return sanitize_pdf_text(&format!("* {base_chord} -> {target}"));
        }
        return sanitize_pdf_text(&format!("* {base_chord}"));
    }
    if ann.status == "missing" {
        let (target, _) = extract_compact_chord_symbol(
            ann.suggested_chord.as_deref().or(Some(ann.chord.as_str())),
        );
        let t = if target.is_empty() { base_chord } else { target };
        return sanitize_pdf_text(&format!("+ {t}"));
    }
    sanitize_pdf_text(&base_chord)
}

fn get_suggested_chord_for_badge(ann: &ChordAnnotation) -> String {
    let (sugg, _) = extract_compact_chord_symbol(ann.suggested_chord.as_deref());
    if !sugg.is_empty() {
        return sanitize_pdf_text(&sugg);
    }
    let (base, _) = extract_compact_chord_symbol(Some(&ann.chord));
    if !base.is_empty() {
        sanitize_pdf_text(&base)
    } else {
        sanitize_pdf_text(&ann.chord.trim().chars().take(12).collect::<String>())
    }
}

fn resolve_system_y(
    page_layout: &PageLayout,
    ann: &ChordAnnotation,
    has_existing_chords: bool,
) -> f64 {
    if let Some(y) = ann.y_pt {
        if y >= 20.0 && y <= page_layout.height_pt - 20.0 {
            return y;
        }
    }
    if !page_layout.systems.is_empty() {
        let idx = ann.system_index.clamp(1, page_layout.systems.len());
        let base_y = page_layout.systems[idx - 1].chord_y_pt;
        return (base_y + if has_existing_chords { 7.5 } else { 0.0 })
            .min(page_layout.height_pt - 36.0);
    }
    page_layout.height_pt - 120.0 * (ann.system_index.max(1) as f64)
}

fn system_vertical_bounds(page_layout: &PageLayout, sys_idx: usize, pill_h: f64) -> (f64, f64) {
    if page_layout.systems.is_empty() {
        return (40.0, page_layout.height_pt - 28.0);
    }
    let idx0 = sys_idx
        .saturating_sub(1)
        .min(page_layout.systems.len() - 1);
    let sys_obj = &page_layout.systems[idx0];
    let y_min = sys_obj.y_top_pt + 3.0;
    let y_max = if idx0 > 0 {
        let prev_bot = page_layout.systems[idx0 - 1].y_bottom_pt;
        (y_min + pill_h + 1.0).max(prev_bot - 2.5)
    } else {
        (y_min + pill_h + 1.0).max((page_layout.height_pt - 22.0).min(sys_obj.y_top_pt + 44.0))
    };
    (y_min, y_max)
}

#[allow(clippy::too_many_arguments)]
fn measure_and_draw_chord_ref_badge(
    c: &mut PdfCanvas,
    chord_label: &str,
    note_num: usize,
    style: PillStyle,
    base_font_size: f64,
    pill_w: f64,
    pill_h: f64,
    rect_x: f64,
    rect_y: f64,
) {
    let ref_str = note_num.to_string();
    let mut chord_fs = base_font_size;
    let mut sup_fs = (chord_fs * 0.56 * 100.0).round() / 100.0;
    let min_pad_x = 1.8;
    let gap_x = 0.9;
    let max_content_w = pill_w - 2.0 * min_pad_x;

    while chord_fs > 5.0 {
        let cw = string_width(chord_label, true, chord_fs);
        let sw = string_width(&ref_str, true, sup_fs);
        if (cw + gap_x + sw) <= max_content_w {
            break;
        }
        chord_fs = ((chord_fs - 0.3) * 100.0).round() / 100.0;
        sup_fs = (chord_fs * 0.56 * 100.0).round() / 100.0;
    }

    let cw = string_width(chord_label, true, chord_fs);
    let sw = string_width(&ref_str, true, sup_fs);
    let content_w = cw + gap_x + sw;

    c.set_fill_rgb(style.fill);
    c.set_stroke_rgb(style.stroke);
    c.set_line_width(0.75);
    c.round_rect(rect_x, rect_y, pill_w, pill_h, 2.5, true, true);

    let start_x = rect_x + min_pad_x.max((pill_w - content_w) / 2.0);
    let base_y = rect_y + (pill_h - chord_fs) * 0.42 + 0.6;
    let sup_y = base_y + chord_fs * 0.42;

    c.set_fill_rgb(style.text);
    c.draw_string("F2", chord_fs, start_x, base_y, chord_label);
    c.draw_string("F2", sup_fs, start_x + cw + gap_x, sup_y, &ref_str);
}

fn draw_minimal_footnote_markers(
    c: &mut PdfCanvas,
    page_layout: &PageLayout,
    ink_grid: &[u8],
    numbered_page_anns: &[(usize, ChordAnnotation)],
) {
    let mut by_system: BTreeMap<usize, Vec<(usize, ChordAnnotation)>> = BTreeMap::new();
    for (num, ann) in numbered_page_anns {
        by_system
            .entry(ann.system_index)
            .or_default()
            .push((*num, ann.clone()));
    }

    let base_font_size = if page_layout.systems.len() >= 6 {
        7.2
    } else {
        7.6
    };
    let uniform_pill_w = if page_layout.systems.len() >= 6 {
        26.0
    } else {
        27.5
    };
    let uniform_pill_h = if page_layout.systems.len() >= 6 {
        10.8
    } else {
        11.4
    };
    let pad_x = 2.4;
    let pad_y = 1.5;
    let mut placed_rects: Vec<(f64, f64, f64, f64)> = Vec::new();

    for (sys_idx, mut sys_items) in by_system {
        sys_items.sort_by(|a, b| {
            a.1.x_pt
                .partial_cmp(&b.1.x_pt)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let mut last_right_edge = -1000.0_f64;

        let max_raw_x = sys_items
            .iter()
            .map(|(_, a)| a.x_pt)
            .fold(0.0_f64, f64::max);
        let min_raw_x = sys_items
            .iter()
            .map(|(_, a)| a.x_pt)
            .fold(80.0_f64, f64::min);
        let usable_right = page_layout.width_pt - 58.0;
        let usable_left = min_raw_x.max(45.0).min(96.0);
        let rescale_x = max_raw_x > (page_layout.width_pt - 32.0) && max_raw_x > min_raw_x;

        for (note_num, ann) in sys_items {
            let chord_label = get_suggested_chord_for_badge(&ann);
            let style_key = if ann.status == "missing" {
                "missing"
            } else {
                "improve"
            };
            let style = get_pill_style(style_key);
            let (pill_w, pill_h) = (uniform_pill_w, uniform_pill_h);

            let mut raw_x = ann.x_pt;
            if rescale_x {
                raw_x = usable_left
                    + ((raw_x - min_raw_x) / (max_raw_x - min_raw_x))
                        * (usable_right - usable_left);
            }
            if ann.status == "improve" {
                raw_x += 18.0;
            }

            let mut x = raw_x.clamp(36.0, page_layout.width_pt - pill_w - 20.0);
            let y = resolve_system_y(page_layout, &ann, true);
            if x < last_right_edge + 3.0 {
                x = (last_right_edge + 3.0).min(page_layout.width_pt - pill_w - 18.0);
            }

            let (y_min, y_max) = system_vertical_bounds(page_layout, sys_idx, pill_h);
            let (rect_x, rect_y) = find_clear_rect(
                ink_grid,
                page_layout.ink_cols,
                page_layout.ink_rows,
                page_layout.width_pt,
                page_layout.height_pt,
                x - pad_x,
                y - pad_y,
                pill_w,
                pill_h,
                (last_right_edge + 2.5)
                    .max(x - pad_x - 20.0)
                    .max(32.0),
                (x - pad_x + pill_w + 28.0).min(page_layout.width_pt - 14.0),
                y_min,
                y_max,
                &placed_rects,
                1.0,
            );
            placed_rects.push((rect_x, rect_y, pill_w, pill_h));

            measure_and_draw_chord_ref_badge(
                c,
                &chord_label,
                note_num,
                style,
                base_font_size,
                pill_w,
                pill_h,
                rect_x,
                rect_y,
            );
            last_right_edge = rect_x + pill_w;
        }
    }
}

fn condense_dense_system_annotations(
    sys_anns: &[ChordAnnotation],
    has_existing_chords: bool,
    page_width_pt: f64,
) -> Vec<ChordAnnotation> {
    if has_existing_chords || sys_anns.len() <= 6 {
        return sys_anns.to_vec();
    }
    let mut deduped: Vec<ChordAnnotation> = Vec::new();
    for ann in sys_anns {
        let lbl = format_pill_text(ann, has_existing_chords);
        if lbl.is_empty() {
            continue;
        }
        if let Some(prev) = deduped.last() {
            let prev_lbl = format_pill_text(prev, has_existing_chords);
            if lbl == prev_lbl && (ann.x_pt - prev.x_pt).abs() < 110.0 {
                continue;
            }
        }
        deduped.push(ann.clone());
    }

    let max_per_sys = if page_width_pt <= 640.0 { 7 } else { 8 };
    if deduped.len() > max_per_sys {
        let mut compact = Vec::new();
        let mut i = 0;
        while i < deduped.len() {
            let curr = &deduped[i];
            compact.push(curr.clone());
            if i + 2 < deduped.len() && deduped.len() > max_per_sys {
                let c0 = curr.chord.split('/').next().unwrap_or("").trim();
                let c1 = deduped[i + 1].chord.split('/').next().unwrap_or("").trim();
                let c2 = deduped[i + 2].chord.split('/').next().unwrap_or("").trim();
                if !c0.is_empty()
                    && c0 == c1
                    && c1 == c2
                    && (deduped[i + 2].x_pt - curr.x_pt) < 125.0
                {
                    compact.push(deduped[i + 1].clone());
                    i += 3;
                    continue;
                }
            }
            i += 1;
        }
        deduped = compact;
    }
    deduped
}

fn draw_chord_pills(
    c: &mut PdfCanvas,
    page_layout: &PageLayout,
    ink_grid: &[u8],
    annotations: &[ChordAnnotation],
    has_existing_chords: bool,
) {
    let mut by_system: BTreeMap<usize, Vec<ChordAnnotation>> = BTreeMap::new();
    for ann in annotations {
        by_system
            .entry(ann.system_index)
            .or_default()
            .push(ann.clone());
    }

    let mut placed_rects: Vec<(f64, f64, f64, f64)> = Vec::new();

    for (sys_idx, mut raw_sys_anns) in by_system {
        raw_sys_anns.sort_by(|a, b| {
            a.x_pt
                .partial_cmp(&b.x_pt)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let sys_anns = condense_dense_system_annotations(
            &raw_sys_anns,
            has_existing_chords,
            page_layout.width_pt,
        );
        let labels: Vec<String> = sys_anns
            .iter()
            .map(|a| format_pill_text(a, has_existing_chords))
            .filter(|l| !l.is_empty())
            .collect();
        if labels.is_empty() {
            continue;
        }

        let n_sys = page_layout.systems.len();
        let idx0 = sys_idx.saturating_sub(1).min(n_sys.saturating_sub(1));
        let treble_h = if n_sys > 0 {
            page_layout.systems[idx0].treble_height_pt
        } else {
            20.0
        };
        let inter_gap = if n_sys > 0 && idx0 > 0 {
            page_layout.systems[idx0 - 1].y_bottom_pt - page_layout.systems[idx0].y_top_pt
        } else {
            48.0
        };

        let mut font_size: f64 = if treble_h <= 16.8 || inter_gap <= 34.0 || n_sys >= 7 {
            7.4
        } else if treble_h <= 19.5 || inter_gap <= 42.0 || n_sys >= 6 {
            8.4
        } else if n_sys == 5 || page_layout.width_pt < 620.0 {
            9.4
        } else if has_existing_chords {
            10.2
        } else {
            10.6
        };
        let mut pad_x: f64 = (font_size * 0.24).max(1.6);
        let mut pad_y: f64 = (font_size * 0.15).max(1.0);

        let usable_span = (page_layout.width_pt - 76.0).max(220.0);
        while font_size > 6.4 {
            let total_w: f64 = labels
                .iter()
                .map(|lbl| string_width(lbl, true, font_size) + 2.0 * pad_x + 4.0)
                .sum();
            if total_w <= usable_span * 0.90 {
                break;
            }
            font_size -= 0.4;
            pad_x = (font_size * 0.22).max(1.4);
            pad_y = (font_size * 0.14).max(0.9);
        }

        let pill_h = font_size + 2.0 * pad_y;
        let (y_min, y_max) = system_vertical_bounds(page_layout, sys_idx, pill_h);

        let max_raw_x = sys_anns.iter().map(|a| a.x_pt).fold(0.0_f64, f64::max);
        let min_raw_x = sys_anns.iter().map(|a| a.x_pt).fold(80.0_f64, f64::min);
        let usable_right = page_layout.width_pt - 54.0;
        let usable_left = min_raw_x.max(42.0).min(92.0);
        let rescale_x = max_raw_x > (page_layout.width_pt - 32.0) && max_raw_x > min_raw_x;

        let mut last_right_edge = -1000.0_f64;

        for ann in sys_anns {
            let label = format_pill_text(&ann, has_existing_chords);
            if label.is_empty() {
                continue;
            }
            let w = string_width(&label, true, font_size);
            let pill_w = w + 2.0 * pad_x;

            let mut raw_x = ann.x_pt;
            if rescale_x {
                raw_x = usable_left
                    + ((raw_x - min_raw_x) / (max_raw_x - min_raw_x))
                        * (usable_right - usable_left);
            }
            if ann.status == "improve" {
                raw_x += 18.0;
            }

            let mut x = raw_x.clamp(36.0, page_layout.width_pt - pill_w - 20.0);
            let y = resolve_system_y(page_layout, &ann, has_existing_chords);

            if x - pad_x < last_right_edge + 3.0 {
                x = (last_right_edge + 3.0 + pad_x).min(page_layout.width_pt - pill_w - 16.0);
            }

            let (rect_x, rect_y) = find_clear_rect(
                ink_grid,
                page_layout.ink_cols,
                page_layout.ink_rows,
                page_layout.width_pt,
                page_layout.height_pt,
                x - pad_x,
                y - pad_y,
                pill_w,
                pill_h,
                (last_right_edge + 2.5)
                    .max(x - pad_x - 28.0)
                    .max(32.0),
                (x - pad_x + pill_w + 38.0).min(page_layout.width_pt - 14.0),
                y_min,
                y_max,
                &placed_rects,
                1.2,
            );
            placed_rects.push((rect_x, rect_y, pill_w, pill_h));
            let draw_x = rect_x + pad_x;
            let draw_y = rect_y + pad_y;

            let style_key = if has_existing_chords {
                ann.status.as_str()
            } else {
                "added"
            };
            let style = get_pill_style(style_key);

            c.set_fill_rgb(style.fill);
            c.set_stroke_rgb(style.stroke);
            c.set_line_width(0.6);
            c.round_rect(rect_x, rect_y, pill_w, pill_h, 2.2, true, true);

            c.set_fill_rgb(style.text);
            c.draw_string("F2", font_size, draw_x, draw_y + font_size * 0.09, &label);

            last_right_edge = rect_x + pill_w;
        }
    }
}

fn fretboard_diagram_rows_count(
    diagrams: &[GuitarDiagram],
    available_width: f64,
) -> (usize, usize) {
    let count = diagrams.len().min(8);
    if count == 0 {
        return (0, 1);
    }
    let max_cols = (((available_width + 10.0) / 105.0).floor() as usize).clamp(1, 4);
    if count <= max_cols {
        return (1, count);
    }
    let cols = ((count + 1) / 2).min(max_cols).max(1);
    let rows = (count + cols - 1) / cols;
    (rows, cols)
}

fn normalize_frets(frets: &[String]) -> Vec<i32> {
    // -1 = 'x', 0 = open, >0 = fret
    let mut out = Vec::with_capacity(6);
    for f in frets.iter().take(6) {
        let s = f.trim().to_lowercase();
        if s == "x" || s == "-1" {
            out.push(-1);
        } else {
            out.push(s.parse::<i32>().unwrap_or(0).max(0));
        }
    }
    while out.len() < 6 {
        out.push(0);
    }
    out
}

fn draw_fretboard_diagrams(
    c: &mut PdfCanvas,
    diagrams: &[GuitarDiagram],
    start_x: f64,
    top_y: f64,
    available_width: f64,
) -> f64 {
    let shown: Vec<&GuitarDiagram> = diagrams.iter().take(8).collect();
    if shown.is_empty() {
        return 0.0;
    }
    let (rows, cols) = fretboard_diagram_rows_count(diagrams, available_width);
    let str_space = 10.0;
    let fret_space = 15.0;
    let grid_w = 5.0 * str_space;
    let row_stride_y = 94.0;

    let spacing_x = if cols > 1 {
        ((available_width - grid_w - 12.0) / (cols - 1) as f64).min(118.0)
    } else {
        0.0
    };

    for (idx, diag) in shown.iter().enumerate() {
        let r = idx / cols;
        let col = idx % cols;
        let dx = start_x + col as f64 * spacing_x;
        let row_top_y = top_y - r as f64 * row_stride_y;
        let frets = normalize_frets(&diag.frets);

        let raw_label = sanitize_pdf_text(&diag.name.chars().take(20).collect::<String>());
        let mut lbl_font = 9.2;
        let max_lbl_w = if cols > 1 {
            (spacing_x - 6.0).max(64.0)
        } else {
            available_width
        };
        while lbl_font > 7.2 && string_width(&raw_label, true, lbl_font) > max_lbl_w {
            lbl_font -= 0.4;
        }
        c.set_fill_rgb(hex_to_rgb("#0b3c5d"));
        c.draw_centered_string("F2", lbl_font, dx + 2.5 * str_space, row_top_y + 20.0, &raw_label);

        let numeric_frets: Vec<i32> = frets.iter().copied().filter(|&f| f > 0).collect();
        let max_fret = numeric_frets.iter().copied().max().unwrap_or(0);
        let min_fret = numeric_frets.iter().copied().min().unwrap_or(1);
        let base_fret = if max_fret <= 4 { 1 } else { min_fret };

        c.set_stroke_rgb(hex_to_rgb("#2c3e50"));
        c.set_line_width(if base_fret == 1 { 2.4 } else { 1.0 });
        c.line(dx, row_top_y, dx + 5.0 * str_space, row_top_y);

        if base_fret > 1 {
            c.set_fill_rgb(hex_to_rgb("#2c3e50"));
            c.draw_right_string("F2", 7.2, dx - 3.0, row_top_y - 10.0, &format!("{base_fret}fr"));
        }

        c.set_line_width(0.7);
        for f in 1..=4 {
            let fy = row_top_y - f as f64 * fret_space;
            c.line(dx, fy, dx + 5.0 * str_space, fy);
        }
        for s in 0..6 {
            let sx = dx + s as f64 * str_space;
            c.line(sx, row_top_y, sx, row_top_y - 4.0 * fret_space);
        }

        for (s, &val) in frets.iter().enumerate() {
            let sx = dx + s as f64 * str_space;
            if val == -1 {
                c.set_fill_rgb(hex_to_rgb("#c0392b"));
                c.draw_centered_string("F2", 8.5, sx, row_top_y + 5.5, "x");
            } else if val == 0 {
                c.set_stroke_rgb(hex_to_rgb("#27ae60"));
                c.set_line_width(1.2);
                c.circle(sx, row_top_y + 8.5, 3.0, false, true);
            } else if val > 0 {
                let rel_fret = (val - base_fret + 1).clamp(1, 4) as f64;
                let fy = row_top_y - (rel_fret - 0.5) * fret_space;
                c.set_fill_rgb(hex_to_rgb("#1a5276"));
                c.circle(sx, fy, 4.0, true, false);
                c.set_fill_rgb((1.0, 1.0, 1.0));
                c.draw_centered_string("F2", 6.8, sx, fy - 2.3, &val.to_string());
            }
        }
    }

    rows as f64 * row_stride_y
}

fn compute_add_chords_summary_box_height(width_pt: f64, result: &HarmonyAnalysisResult) -> f64 {
    let margin_x = 39.4;
    let box_w = width_pt - 2.0 * margin_x;
    let avail_diag_w = box_w - 45.0;
    let (rows, _) = fretboard_diagram_rows_count(&result.chord_diagrams, avail_diag_w);
    let diag_h = if rows > 0 { rows as f64 * 94.0 } else { 20.0 };
    let notes_count = result.slash_chord_notes.len().min(2) + result.bass_line_proposals.len().min(3);
    let notes_h = if notes_count > 0 {
        22.0 + notes_count as f64 * 22.0
    } else {
        44.0
    };
    (56.0 + diag_h + notes_h + 28.0).max(250.0)
}

fn draw_add_chords_summary_box(
    c: &mut PdfCanvas,
    width_pt: f64,
    box_bottom_y: f64,
    box_height: f64,
    result: &HarmonyAnalysisResult,
    language: &str,
) {
    let is_fr = language == "fr";
    let margin_x = 39.4;
    let box_w = width_pt - 2.0 * margin_x;
    let inner_w = box_w - 31.2;

    c.set_stroke_rgb(hex_to_rgb("#2c3e50"));
    c.set_fill_rgb(hex_to_rgb("#f8f9fa"));
    c.set_line_width(1.0);
    c.round_rect(margin_x, box_bottom_y, box_w, box_height, 6.0, true, true);

    let mut cursor_y = box_bottom_y + box_height - 22.0;
    c.set_fill_rgb(hex_to_rgb("#1a5276"));
    let safe_title = sanitize_pdf_text(if result.title.is_empty() {
        "Score"
    } else {
        &result.title
    });
    let title_str = if is_fr {
        format!("Diagrammes des accords principaux ({safe_title})")
    } else {
        format!("Main Guitar Chord Diagrams ({safe_title})")
    };
    for t_line in wrap_pdf_line(&title_str, true, 11.5, inner_w)
        .into_iter()
        .take(2)
    {
        c.draw_string("F2", 11.5, margin_x + 15.6, cursor_y, &t_line);
        cursor_y -= 14.0;
    }

    let diag_top_y = cursor_y - 28.0;
    let diag_used_h = draw_fretboard_diagrams(
        c,
        &result.chord_diagrams,
        margin_x + 22.6,
        diag_top_y,
        box_w - 45.0,
    );

    let mut text_y = if diag_used_h > 0.0 {
        diag_top_y - diag_used_h + 14.0
    } else {
        cursor_y - 10.0
    };
    let footer_ceil_y = box_bottom_y + 26.0;

    if !result.slash_chord_notes.is_empty() || !result.bass_line_proposals.is_empty() {
        c.set_fill_rgb(hex_to_rgb("#1a5276"));
        let slash_heading = if is_fr {
            "Propositions de basses - Contrepoint & Walking Bass (anti-fondamentale / anti-doublage) :"
        } else {
            "Bass Line Proposals - Counterpoint & Walking Bass (anti-root / anti-melody-doubling):"
        };
        for st_line in wrap_pdf_line(slash_heading, true, 9.0, inner_w)
            .into_iter()
            .take(1)
        {
            if text_y > footer_ceil_y {
                c.draw_string("F2", 9.0, margin_x + 15.6, text_y, &st_line);
                text_y -= 12.5;
            }
        }
        c.set_fill_rgb(hex_to_rgb("#2c3e50"));
        for note_item in result.slash_chord_notes.iter().take(2) {
            let clean_note = sanitize_pdf_text(note_item.trim_start_matches(&['•', '-', ' '][..]));
            for line in wrap_pdf_line(&format!("• {clean_note}"), false, 8.2, inner_w)
                .into_iter()
                .take(2)
            {
                if text_y > footer_ceil_y {
                    c.draw_string("F1", 8.2, margin_x + 15.6, text_y, &line);
                    text_y -= 11.0;
                }
            }
        }
        for bp in result.bass_line_proposals.iter().take(3) {
            let tag = if bp.technique == "walking_bass" {
                "Walking Bass"
            } else if is_fr {
                "Contrepoint"
            } else {
                "Counterpoint"
            };
            let m_lbl = bp
                .measure_number
                .map(|m| format!("m.{m} "))
                .unwrap_or_default();
            let bp_line = format!(
                "• [{tag}] {m_lbl}{} -> {} : {}",
                bp.original_chord, bp.proposed_slash_chord, bp.explanation
            );
            for line in wrap_pdf_line(&bp_line, false, 8.2, inner_w)
                .into_iter()
                .take(2)
            {
                if text_y > footer_ceil_y {
                    c.draw_string("F1", 8.2, margin_x + 15.6, text_y, &line);
                    text_y -= 11.0;
                }
            }
        }
    } else if !result.overall_summary.is_empty() {
        c.set_fill_rgb(hex_to_rgb("#2c3e50"));
        for line in wrap_pdf_line(&result.overall_summary, false, 8.5, inner_w)
            .into_iter()
            .take(3)
        {
            if text_y > footer_ceil_y {
                c.draw_string("F1", 8.5, margin_x + 15.6, text_y, &line);
                text_y -= 12.0;
            }
        }
    }

    c.set_fill_rgb(hex_to_rgb("#2c3e50"));
    let footer_note = if is_fr {
        "Note : Chaque étiquette bleue au-dessus de la portée indique l'accord ou le renversement de basse aligné sur le temps."
    } else {
        "Note: Each blue pill above the staff marks the chord or inverted bass note aligned directly with its beat."
    };
    if let Some(first_footer) = wrap_pdf_line(footer_note, false, 8.0, inner_w).first() {
        c.draw_string("F3", 8.0, margin_x + 15.6, box_bottom_y + 11.0, first_footer);
    }
}

fn build_analysis_notes_pages_streams(
    page_w: f64,
    page_h: f64,
    result: &HarmonyAnalysisResult,
    numbered_notes: &[(usize, ChordAnnotation)],
    language: &str,
) -> Vec<Vec<u8>> {
    let is_fr = language == "fr";
    let margin_x = 38.0;
    let content_w = page_w - 2.0 * margin_x;
    let inner_pad_x = 14.0;
    let inner_w = content_w - 2.0 * inner_pad_x;
    let top_margin = 46.0;
    let bottom_margin = 44.0;

    let mut pages_streams: Vec<Vec<u8>> = Vec::new();
    let mut c = PdfCanvas::new();
    let mut cursor_y = page_h - top_margin;

    let key_str = if result.detected_key.is_empty() {
        "Am"
    } else {
        &result.detected_key
    };
    let raw_subtitle = sanitize_pdf_text(&if is_fr {
        format!("Analyse harmonique, contrepoint & revue des accords (Tonalité : {key_str})")
    } else {
        format!("Harmonic Analysis, Counterpoint & Chord Review (Key: {key_str})")
    });

    let start_new_page = |pages_streams: &mut Vec<Vec<u8>>,
                          c: &mut PdfCanvas,
                          cursor_y: &mut f64| {
        let finished = std::mem::replace(c, PdfCanvas::new());
        pages_streams.push(finished.into_bytes());
        *cursor_y = page_h - top_margin;
        let sub_lines = wrap_pdf_line(&raw_subtitle, true, 10.0, content_w);
        c.set_fill_rgb(hex_to_rgb("#1a5276"));
        for sline in sub_lines {
            c.draw_string("F2", 10.0, margin_x, *cursor_y, &sline);
            *cursor_y -= 13.5;
        }
        *cursor_y -= 8.0;
    };

    let title_lines = wrap_pdf_line(&raw_subtitle, true, 11.5, inner_w);
    let mut safe_title = sanitize_pdf_text(if result.title.is_empty() {
        "Score"
    } else {
        &result.title
    });
    if safe_title.len() > 38 && safe_title.contains('(') {
        safe_title = safe_title.split('(').next().unwrap_or("Score").trim().to_string();
    }
    if safe_title.chars().count() > 44 {
        safe_title = format!("{}...", safe_title.chars().take(42).collect::<String>());
    }
    let box_title_str = if is_fr {
        format!("Bilan harmonique & contrepoint de basse ({safe_title})")
    } else {
        format!("Harmonic & Bass Counterpoint Review ({safe_title})")
    };
    let box_title_lines = wrap_pdf_line(&box_title_str, true, 10.0, inner_w);

    let acc_text = if is_fr {
        format!(
            "Précision globale des accords existants : {}%",
            result.accuracy_score
        )
    } else {
        format!(
            "Overall accuracy of existing chords: {}%",
            result.accuracy_score
        )
    };
    let legend_note = if is_fr {
        "Badges sur la partition : Accord suggéré + n° de renvoi en exposant (Orange = Amélioration / Basse, Rouge = Accord manquant)"
    } else {
        "Score badges: Suggested chord + superscript ref # (Amber = Chord / Bass improvement, Red = Missing chord)"
    };
    let legend_lines = wrap_pdf_line(legend_note, true, 8.2, inner_w);

    let card_h = 14.0
        + title_lines.len() as f64 * 14.5
        + 4.0
        + box_title_lines.len() as f64 * 13.0
        + 14.5
        + 3.0
        + legend_lines.len() as f64 * 11.5
        + 10.0;

    c.set_fill_rgb(hex_to_rgb("#f0f7fc"));
    c.set_stroke_rgb(hex_to_rgb("#2980b9"));
    c.set_line_width(1.0);
    c.round_rect(
        margin_x,
        cursor_y - card_h,
        content_w,
        card_h,
        6.0,
        true,
        true,
    );

    let mut header_y = cursor_y - 16.0;
    c.set_fill_rgb(hex_to_rgb("#0b3c5d"));
    for tline in &title_lines {
        c.draw_string("F2", 11.5, margin_x + inner_pad_x, header_y, tline);
        header_y -= 14.5;
    }
    header_y -= 2.0;
    c.set_fill_rgb(hex_to_rgb("#1a5276"));
    for btline in &box_title_lines {
        c.draw_string("F2", 10.0, margin_x + inner_pad_x, header_y, btline);
        header_y -= 13.0;
    }

    let acc_color = if result.accuracy_score >= 80 {
        hex_to_rgb("#145a32")
    } else if result.accuracy_score >= 50 {
        hex_to_rgb("#7e5109")
    } else {
        hex_to_rgb("#78281f")
    };
    c.set_fill_rgb(acc_color);
    c.draw_string("F2", 9.8, margin_x + inner_pad_x, header_y, &acc_text);
    header_y -= 14.5;

    c.set_fill_rgb(hex_to_rgb("#34495e"));
    for lline in &legend_lines {
        c.draw_string("F2", 8.2, margin_x + inner_pad_x, header_y, lline);
        header_y -= 11.5;
    }

    cursor_y -= card_h + 16.0;

    if !result.overall_summary.is_empty() {
        let summary_lines = wrap_pdf_line(&result.overall_summary, false, 9.5, content_w);
        let needed = summary_lines.len() as f64 * 13.5 + 12.0;
        if cursor_y - needed < bottom_margin {
            start_new_page(&mut pages_streams, &mut c, &mut cursor_y);
        }
        c.set_fill_rgb(hex_to_rgb("#1e293b"));
        for line in summary_lines {
            c.draw_string("F1", 9.5, margin_x, cursor_y, &line);
            cursor_y -= 13.5;
        }
        cursor_y -= 10.0;
    }

    if !numbered_notes.is_empty() {
        if cursor_y - 36.0 < bottom_margin {
            start_new_page(&mut pages_streams, &mut c, &mut cursor_y);
        }
        c.set_fill_rgb(hex_to_rgb("#1a5276"));
        let notes_heading = if is_fr {
            format!(
                "Notes détaillées renvoyées depuis la partition ([1] à [{}]) :",
                numbered_notes.len()
            )
        } else {
            format!("Detailed Score Footnotes ([1] to [{}]):", numbered_notes.len())
        };
        c.draw_string("F2", 10.8, margin_x, cursor_y, &notes_heading);
        cursor_y -= 16.0;

        for (note_num, ann) in numbered_notes {
            let (mut base_chord, _) = extract_compact_chord_symbol(Some(&ann.chord));
            if base_chord.is_empty() {
                base_chord = ann.chord.trim().chars().take(14).collect();
            }
            let (sugg_chord, _) = extract_compact_chord_symbol(ann.suggested_chord.as_deref());
            let (chord_change, style) = if ann.status == "missing" {
                let target = if sugg_chord.is_empty() {
                    &base_chord
                } else {
                    &sugg_chord
                };
                (format!("+ {target}"), get_pill_style("missing"))
            } else {
                let chg = if !sugg_chord.is_empty() && sugg_chord != base_chord {
                    format!("* {base_chord} -> {sugg_chord}")
                } else {
                    format!("* {base_chord}")
                };
                (chg, get_pill_style("improve"))
            };

            let sys_lbl = if is_fr {
                format!("Système {}", ann.system_index)
            } else {
                format!("System {}", ann.system_index)
            };
            let meas_lbl = match (ann.measure_number, is_fr) {
                (Some(m), true) => format!(", Mesure {m}"),
                (Some(m), false) => format!(", Measure {m}"),
                _ => String::new(),
            };
            let header_line = format!("{sys_lbl}{meas_lbl} : {chord_change}");

            let chord_badge_lbl = get_suggested_chord_for_badge(ann);
            let bw = 29.0;
            let bh = 12.2;
            let note_indent = bw + 8.0;
            let note_avail_w = content_w - note_indent;

            let note_body = ann.note.as_deref().unwrap_or("");
            let wrapped_body = if !note_body.is_empty() {
                wrap_pdf_line(note_body, false, 9.0, note_avail_w)
            } else {
                Vec::new()
            };
            let block_h = 18.0 + wrapped_body.len() as f64 * 12.8 + 6.0;
            if cursor_y - block_h < bottom_margin {
                start_new_page(&mut pages_streams, &mut c, &mut cursor_y);
            }

            measure_and_draw_chord_ref_badge(
                &mut c,
                &chord_badge_lbl,
                *note_num,
                style,
                7.8,
                bw,
                bh,
                margin_x,
                cursor_y - 2.6,
            );

            c.set_fill_rgb(style.text);
            c.draw_string("F2", 9.4, margin_x + note_indent, cursor_y, &header_line);
            cursor_y -= 14.0;

            if !wrapped_body.is_empty() {
                c.set_fill_rgb(hex_to_rgb("#2c3e50"));
                for bline in wrapped_body {
                    c.draw_string("F1", 9.0, margin_x + note_indent, cursor_y, &bline);
                    cursor_y -= 12.8;
                }
            }
            cursor_y -= 5.0;
        }
        cursor_y -= 6.0;
    }

    let mut draw_bullet_section = |heading: &str, color_hex: &str, items: &[String]| {
        if items.is_empty() {
            return;
        }
        if cursor_y - 32.0 < bottom_margin {
            start_new_page(&mut pages_streams, &mut c, &mut cursor_y);
        }
        c.set_fill_rgb(hex_to_rgb(color_hex));
        c.draw_string("F2", 10.5, margin_x, cursor_y, heading);
        cursor_y -= 15.0;

        for item in items {
            let clean = item.trim_start_matches(&['•', '-', ' '][..]);
            let lines = wrap_pdf_line(&format!("• {clean}"), false, 9.0, content_w - 10.0);
            if cursor_y - (lines.len() as f64 * 12.8 + 4.0) < bottom_margin {
                start_new_page(&mut pages_streams, &mut c, &mut cursor_y);
            }
            c.set_fill_rgb(hex_to_rgb("#2c3e50"));
            for (l_idx, line) in lines.iter().enumerate() {
                let x_off = if l_idx > 0 { 10.0 } else { 0.0 };
                c.draw_string("F1", 9.0, margin_x + x_off, cursor_y, line);
                cursor_y -= 12.8;
            }
            cursor_y -= 3.0;
        }
        cursor_y -= 6.0;
    };

    let no_issues = if is_fr {
        "Aucun accord manquant ou erroné détecté.".to_string()
    } else {
        "No missing or inaccurate chords detected.".to_string()
    };

    let improvements: Vec<String> = if !result.review_improvements.is_empty() {
        result.review_improvements.clone()
    } else {
        let v: Vec<String> = result
            .annotations
            .iter()
            .filter(|a| a.status == "improve")
            .map(|a| {
                format!(
                    "m.{}: {} -> {} ({})",
                    a.measure_number
                        .map(|m| m.to_string())
                        .unwrap_or_else(|| "?".to_string()),
                    a.chord,
                    a.suggested_chord.as_deref().unwrap_or(""),
                    a.note.as_deref().unwrap_or("")
                )
            })
            .collect();
        if v.is_empty() {
            vec![no_issues.clone()]
        } else {
            v
        }
    };
    draw_bullet_section(
        if is_fr {
            "Améliorations & basses contrepoint suggérées :"
        } else {
            "Suggested Chord & Bass Improvements:"
        },
        "#b45309",
        &improvements,
    );

    let missing: Vec<String> = if !result.review_missing.is_empty() {
        result.review_missing.clone()
    } else {
        let v: Vec<String> = result
            .annotations
            .iter()
            .filter(|a| a.status == "missing")
            .map(|a| {
                format!(
                    "m.{}: + {} ({})",
                    a.measure_number
                        .map(|m| m.to_string())
                        .unwrap_or_else(|| "?".to_string()),
                    a.suggested_chord.as_deref().unwrap_or(&a.chord),
                    a.note.as_deref().unwrap_or("")
                )
            })
            .collect();
        if v.is_empty() {
            vec![no_issues]
        } else {
            v
        }
    };
    draw_bullet_section(
        if is_fr {
            "Accords manquants détectés :"
        } else {
            "Missing Chords Detected:"
        },
        "#78281f",
        &missing,
    );

    if !result.bass_line_proposals.is_empty() {
        let bass_items: Vec<String> = result
            .bass_line_proposals
            .iter()
            .map(|bp| {
                let tag = if bp.technique == "walking_bass" {
                    "Walking Bass"
                } else if is_fr {
                    "Contrepoint"
                } else {
                    "Counterpoint"
                };
                let m_lbl = bp
                    .measure_number
                    .map(|m| format!("m.{m} "))
                    .unwrap_or_default();
                format!(
                    "[{tag}] {m_lbl}({} -> {}) : {}",
                    bp.original_chord, bp.proposed_slash_chord, bp.explanation
                )
            })
            .collect();
        draw_bullet_section(
            if is_fr {
                "Ligne de basse - Contrepoint & Walking Bass :"
            } else {
                "Bass Line - Counterpoint & Walking Bass:"
            },
            "#1a5276",
            &bass_items,
        );
    }

    if !result.review_correct.is_empty() {
        draw_bullet_section(
            if is_fr {
                "Accords existants validés :"
            } else {
                "Confirmed Existing Chords:"
            },
            "#145a32",
            &result.review_correct,
        );
    }

    if !result.chord_diagrams.is_empty() {
        let diag_title_str = if is_fr {
            format!("Diagrammes des accords principaux ({safe_title})")
        } else {
            format!("Main Guitar Chord Diagrams ({safe_title})")
        };
        let diag_title_lines = wrap_pdf_line(&diag_title_str, true, 10.5, content_w);
        let (diag_rows, _) =
            fretboard_diagram_rows_count(&result.chord_diagrams, content_w - 24.0);
        let needed_diag_h =
            diag_rows as f64 * 94.0 + 34.0 + diag_title_lines.len() as f64 * 14.0;
        if cursor_y - needed_diag_h < bottom_margin {
            start_new_page(&mut pages_streams, &mut c, &mut cursor_y);
        }
        cursor_y -= 6.0;
        c.set_fill_rgb(hex_to_rgb("#1a5276"));
        for dt_line in diag_title_lines {
            c.draw_string("F2", 10.5, margin_x, cursor_y, &dt_line);
            cursor_y -= 14.0;
        }
        let _ = draw_fretboard_diagrams(
            &mut c,
            &result.chord_diagrams,
            margin_x + 12.0,
            cursor_y - 26.0,
            content_w - 24.0,
        );
    }

    pages_streams.push(c.into_bytes());
    pages_streams
}

/// Register F1 (Helvetica), F2 (Helvetica-Bold), and F3 (Helvetica-Oblique) with WinAnsiEncoding in `doc`.
fn add_standard_fonts(doc: &mut Document) -> (ObjectId, ObjectId, ObjectId) {
    let f1 = doc.add_object(dictionary! {
        "Type" => "Font",
        "Subtype" => "Type1",
        "BaseFont" => "Helvetica",
        "Encoding" => "WinAnsiEncoding",
    });
    let f2 = doc.add_object(dictionary! {
        "Type" => "Font",
        "Subtype" => "Type1",
        "BaseFont" => "Helvetica-Bold",
        "Encoding" => "WinAnsiEncoding",
    });
    let f3 = doc.add_object(dictionary! {
        "Type" => "Font",
        "Subtype" => "Type1",
        "BaseFont" => "Helvetica-Oblique",
        "Encoding" => "WinAnsiEncoding",
    });
    (f1, f2, f3)
}

/// Attach fonts F1, F2, F3 to an existing page's Resources and append an overlay content stream wrapped in `q ... Q`.
fn append_overlay_to_page(
    doc: &mut Document,
    page_id: ObjectId,
    fonts: (ObjectId, ObjectId, ObjectId),
    overlay_bytes: Vec<u8>,
) -> Result<()> {
    if overlay_bytes.is_empty() {
        return Ok(());
    }

    // Wrap existing page contents in `q` ... `Q` so coordinate/graphics state changes in original PDF don't affect our overlay
    let q_push_id = doc.add_object(Stream::new(dictionary! {}, b"q\n".to_vec()));
    let q_pop_id = doc.add_object(Stream::new(dictionary! {}, b"\nQ\n".to_vec()));
    let overlay_stream_id = doc.add_object(Stream::new(dictionary! {}, overlay_bytes));

    // Update page Contents
    let existing_contents = doc
        .get_dictionary(page_id)
        .ok()
        .and_then(|d| d.get(b"Contents").ok().cloned());

    let new_contents = match existing_contents {
        Some(Object::Reference(id)) => Object::Array(vec![
            Object::Reference(q_push_id),
            Object::Reference(id),
            Object::Reference(q_pop_id),
            Object::Reference(overlay_stream_id),
        ]),
        Some(Object::Array(mut arr)) => {
            let mut combined = Vec::with_capacity(arr.len() + 3);
            combined.push(Object::Reference(q_push_id));
            combined.append(&mut arr);
            combined.push(Object::Reference(q_pop_id));
            combined.push(Object::Reference(overlay_stream_id));
            Object::Array(combined)
        }
        _ => Object::Array(vec![Object::Reference(overlay_stream_id)]),
    };

    if let Ok(page_dict) = doc.get_dictionary_mut(page_id) {
        page_dict.set("Contents", new_contents);
    }

    // Ensure Resources -> Font has F1, F2, F3
    let res_obj = doc
        .get_dictionary(page_id)
        .ok()
        .and_then(|d| d.get(b"Resources").ok().cloned());

    match res_obj {
        Some(Object::Reference(res_id)) => {
            if let Ok(res_dict) = doc.get_dictionary_mut(res_id) {
                inject_fonts_into_resources_dict(res_dict, fonts);
            }
        }
        Some(Object::Dictionary(mut res_dict)) => {
            inject_fonts_into_resources_dict(&mut res_dict, fonts);
            if let Ok(page_dict) = doc.get_dictionary_mut(page_id) {
                page_dict.set("Resources", Object::Dictionary(res_dict));
            }
        }
        _ => {
            let mut res_dict = lopdf::Dictionary::new();
            inject_fonts_into_resources_dict(&mut res_dict, fonts);
            if let Ok(page_dict) = doc.get_dictionary_mut(page_id) {
                page_dict.set("Resources", Object::Dictionary(res_dict));
            }
        }
    }

    Ok(())
}

fn inject_fonts_into_resources_dict(
    res_dict: &mut lopdf::Dictionary,
    (f1, f2, f3): (ObjectId, ObjectId, ObjectId),
) {
    if let Ok(Object::Dictionary(font_dict)) = res_dict.get_mut(b"Font") {
        font_dict.set("F1", Object::Reference(f1));
        font_dict.set("F2", Object::Reference(f2));
        font_dict.set("F3", Object::Reference(f3));
        return;
    }
    res_dict.set(
        "Font",
        dictionary! {
            "F1" => Object::Reference(f1),
            "F2" => Object::Reference(f2),
            "F3" => Object::Reference(f3),
        },
    );
}

/// Append a brand-new page with dimensions `(width_pt, height_pt)` and content stream `stream_bytes` to `doc`.
fn append_new_page_to_doc(
    doc: &mut Document,
    width_pt: f64,
    height_pt: f64,
    fonts: (ObjectId, ObjectId, ObjectId),
    stream_bytes: Vec<u8>,
) -> Result<()> {
    let pages_id = doc
        .catalog()
        .context("Missing PDF Catalog")?
        .get(b"Pages")
        .context("Missing Pages in Catalog")?
        .as_reference()
        .context("Pages is not a reference")?;

    let content_id = doc.add_object(Stream::new(dictionary! {}, stream_bytes));
    let (f1, f2, f3) = fonts;
    let resources_id = doc.add_object(dictionary! {
        "Font" => dictionary! {
            "F1" => Object::Reference(f1),
            "F2" => Object::Reference(f2),
            "F3" => Object::Reference(f3),
        },
    });

    let page_id = doc.add_object(dictionary! {
        "Type" => "Page",
        "Parent" => Object::Reference(pages_id),
        "MediaBox" => vec![0.into(), 0.into(), Object::Real(width_pt as f32), Object::Real(height_pt as f32)],
        "Resources" => Object::Reference(resources_id),
        "Contents" => Object::Reference(content_id),
    });

    if let Ok(pages_dict) = doc.get_dictionary_mut(pages_id) {
        if let Ok(Object::Array(kids)) = pages_dict.get_mut(b"Kids") {
            kids.push(Object::Reference(page_id));
        }
        let current_count = pages_dict
            .get(b"Count")
            .ok()
            .and_then(|o| o.as_i64().ok())
            .unwrap_or(0);
        pages_dict.set("Count", Object::Integer(current_count + 1));
    }

    Ok(())
}

/// Execute the full PDF annotation pipeline in native Rust and write the annotated PDF to `req.output_pdf_path`.
pub fn annotate_music_sheet_pdf(req: &AnnotateRequest) -> Result<()> {
    let input_path = Path::new(&req.input_pdf_path);
    let output_path = Path::new(&req.output_pdf_path);
    if let Some(parent) = output_path.parent() {
        std::fs::create_dir_all(parent)?;
    }

    let mut doc = Document::load(input_path)
        .with_context(|| format!("Failed to load input PDF {}", input_path.display()))?;
    let fonts = add_standard_fonts(&mut doc);
    let page_map = doc.get_pages();
    let num_pages = page_map.len();

    let default_layout = PageLayout {
        page_num: 1,
        width_pt: 595.28,
        height_pt: 841.89,
        systems: Vec::new(),
        bottom_free_pt: 120.0,
        clean_png_path: String::new(),
        guide_png_path: String::new(),
        ink_grid_b64: String::new(),
        ink_cols: 0,
        ink_rows: 0,
    };
    let last_layout = req.layouts.last().unwrap_or(&default_layout);
    let is_fr = req.language == "fr";

    if req.result.has_existing_chords {
        let mut actionable_anns: Vec<ChordAnnotation> = req
            .result
            .annotations
            .iter()
            .filter(|a| a.status == "improve" || a.status == "missing")
            .cloned()
            .collect();
        actionable_anns.sort_by(|a, b| {
            a.page_num
                .cmp(&b.page_num)
                .then_with(|| a.system_index.cmp(&b.system_index))
                .then_with(|| {
                    a.x_pt
                        .partial_cmp(&b.x_pt)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
        });
        let numbered_notes: Vec<(usize, ChordAnnotation)> = actionable_anns
            .into_iter()
            .enumerate()
            .map(|(idx, ann)| (idx + 1, ann))
            .collect();

        for (&p_num_u32, &page_id) in &page_map {
            let page_num = p_num_u32 as usize;
            let layout = req
                .layouts
                .get(page_num.saturating_sub(1))
                .unwrap_or(last_layout);
            let ink_grid = BASE64.decode(&layout.ink_grid_b64).unwrap_or_default();

            let page_numbered: Vec<(usize, ChordAnnotation)> = numbered_notes
                .iter()
                .filter(|(_, a)| a.page_num == page_num)
                .cloned()
                .collect();

            let mut c = PdfCanvas::new();
            if page_num == 1 {
                let ref_label = if is_fr {
                    format!(
                        "Notes d'analyse [1..{}] -> voir pages ajoutées",
                        numbered_notes.len()
                    )
                } else {
                    format!(
                        "Analysis notes [1..{}] -> see appended pages",
                        numbered_notes.len()
                    )
                };
                let lbl_w = string_width(&ref_label, true, 8.2) + 8.0;
                let lbl_h = 11.5;
                let (rx, ry) = find_clear_rect(
                    &ink_grid,
                    layout.ink_cols,
                    layout.ink_rows,
                    layout.width_pt,
                    layout.height_pt,
                    layout.width_pt - 36.0 - lbl_w,
                    layout.height_pt - 18.5,
                    lbl_w,
                    lbl_h,
                    32.0,
                    layout.width_pt - 24.0,
                    layout.height_pt - 26.0,
                    layout.height_pt - 4.0,
                    &[],
                    1.0,
                );
                c.set_fill_rgb(hex_to_rgb("#f8f9fa"));
                c.round_rect(rx, ry, lbl_w, lbl_h, 2.0, true, false);
                c.set_fill_rgb(hex_to_rgb("#1a5276"));
                c.draw_string("F2", 8.2, rx + 4.0, ry + 2.2, &ref_label);
            }

            draw_minimal_footnote_markers(&mut c, layout, &ink_grid, &page_numbered);
            append_overlay_to_page(&mut doc, page_id, fonts, c.into_bytes())?;
        }

        let notes_streams = build_analysis_notes_pages_streams(
            last_layout.width_pt,
            last_layout.height_pt,
            &req.result,
            &numbered_notes,
            &req.language,
        );
        for stream_bytes in notes_streams {
            append_new_page_to_doc(
                &mut doc,
                last_layout.width_pt,
                last_layout.height_pt,
                fonts,
                stream_bytes,
            )?;
        }
    } else {
        let required_box_h =
            compute_add_chords_summary_box_height(last_layout.width_pt, &req.result);
        let margin_x = 39.4;
        let box_w = last_layout.width_pt - 2.0 * margin_x;
        let last_ink = BASE64.decode(&last_layout.ink_grid_b64).unwrap_or_default();
        let bottom_ink = ink_density_in_rect(
            &last_ink,
            last_layout.ink_cols,
            last_layout.ink_rows,
            last_layout.width_pt,
            last_layout.height_pt,
            margin_x,
            20.0,
            box_w,
            required_box_h,
            2.0,
        );
        let summary_fits_on_last_page =
            last_layout.bottom_free_pt >= (required_box_h + 24.0) && bottom_ink <= 0.005;

        for (&p_num_u32, &page_id) in &page_map {
            let page_num = p_num_u32 as usize;
            let layout = req
                .layouts
                .get(page_num.saturating_sub(1))
                .unwrap_or(last_layout);
            let ink_grid = BASE64.decode(&layout.ink_grid_b64).unwrap_or_default();
            let page_anns: Vec<ChordAnnotation> = req
                .result
                .annotations
                .iter()
                .filter(|a| a.page_num == page_num)
                .cloned()
                .collect();

            let mut c = PdfCanvas::new();
            if page_num == 1 {
                let sub_font_size = 8.2;
                let key_str = if req.result.detected_key.is_empty() {
                    "Am"
                } else {
                    &req.result.detected_key
                };
                let sub_text = if is_fr {
                    format!("Grille d'accords & lignes de basse (Tonalité : {key_str})")
                } else {
                    format!("Guitar Chord Chart & Bass Counterpoint (Key: {key_str})")
                };
                let sub_w = string_width(&sub_text, true, sub_font_size) + 10.0;
                let sub_h = sub_font_size + 4.0;
                let y_min_top = layout
                    .systems
                    .first()
                    .map(|s| s.chord_y_pt + 18.0)
                    .unwrap_or(layout.height_pt - 48.0)
                    .max(layout.height_pt - 36.0);
                let (rx, ry) = find_clear_rect(
                    &ink_grid,
                    layout.ink_cols,
                    layout.ink_rows,
                    layout.width_pt,
                    layout.height_pt,
                    (layout.width_pt - sub_w) / 2.0,
                    layout.height_pt - 16.5,
                    sub_w,
                    sub_h,
                    24.0,
                    layout.width_pt - 24.0,
                    y_min_top,
                    layout.height_pt - 3.0,
                    &[],
                    1.0,
                );
                c.set_fill_rgb(hex_to_rgb("#f8f9fa"));
                c.set_stroke_rgb(hex_to_rgb("#d6eaf8"));
                c.set_line_width(0.5);
                c.round_rect(rx, ry, sub_w, sub_h, 2.5, true, true);
                c.set_fill_rgb(hex_to_rgb("#1a5276"));
                c.draw_string("F2", sub_font_size, rx + 5.0, ry + 2.5, &sub_text);
            }

            draw_chord_pills(&mut c, layout, &ink_grid, &page_anns, false);

            if page_num == num_pages && summary_fits_on_last_page {
                let box_height = required_box_h.min(layout.bottom_free_pt - 20.0);
                let box_bottom_y = ((layout.bottom_free_pt - box_height) / 2.0 + 8.0).max(20.0);
                draw_add_chords_summary_box(
                    &mut c,
                    layout.width_pt,
                    box_bottom_y,
                    box_height,
                    &req.result,
                    &req.language,
                );
            }

            append_overlay_to_page(&mut doc, page_id, fonts, c.into_bytes())?;
        }

        if !summary_fits_on_last_page {
            let mut c = PdfCanvas::new();
            let box_h = required_box_h.min(last_layout.height_pt - 56.0);
            let box_bottom_y = (last_layout.height_pt - box_h - 36.0).max(28.0);
            draw_add_chords_summary_box(
                &mut c,
                last_layout.width_pt,
                box_bottom_y,
                box_h,
                &req.result,
                &req.language,
            );
            append_new_page_to_doc(
                &mut doc,
                last_layout.width_pt,
                last_layout.height_pt,
                fonts,
                c.into_bytes(),
            )?;
        }
    }

    doc.save(output_path)
        .with_context(|| format!("Failed to save annotated PDF to {}", output_path.display()))?;
    Ok(())
}
