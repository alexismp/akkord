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

//! High-speed staff system detection, 2pt ink density grid, spiral collision avoidance,
//! and coordinate guide image generator in native Rust.

use std::fs;
use std::path::Path;
use std::process::Command;

use anyhow::{Context, Result};
use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use image::{GrayImage, Luma, Rgb, RgbImage};
use regex::Regex;

use crate::models::{ExtractedTextToken, LayoutExtractionResult, PageLayout, StaffSystem};

/// Compute dark-pixel ink density in a PDF rectangle (origin at bottom-left in PDF points).
pub fn ink_density_in_rect(
    ink_grid: &[u8],
    ink_cols: usize,
    ink_rows: usize,
    width_pt: f64,
    height_pt: f64,
    x_pt: f64,
    y_pt: f64,
    w_pt: f64,
    h_pt: f64,
    pad_pt: f64,
) -> f64 {
    if ink_grid.is_empty() || ink_cols == 0 || ink_rows == 0 || width_pt <= 0.0 || height_pt <= 0.0
    {
        return 0.0;
    }
    let x0 = (x_pt - pad_pt).max(0.0);
    let x1 = (x_pt + w_pt + pad_pt).min(width_pt);
    let y0 = (y_pt - pad_pt).max(0.0);
    let y1 = (y_pt + h_pt + pad_pt).min(height_pt);
    if x1 <= x0 || y1 <= y0 {
        return 0.0;
    }

    let c0 = (((x0 / width_pt) * ink_cols as f64) as usize).min(ink_cols - 1);
    let c1 = (((x1 / width_pt) * ink_cols as f64) as usize).min(ink_cols - 1);
    // PDF Y=0 is bottom, image row 0 is top
    let r0 = ((((height_pt - y1) / height_pt) * ink_rows as f64) as usize).min(ink_rows - 1);
    let r1 = ((((height_pt - y0) / height_pt) * ink_rows as f64) as usize).min(ink_rows - 1);

    let mut total: u64 = 0;
    let mut ink_cells: u64 = 0;
    let mut max_val: u8 = 0;
    let mut count: u64 = 0;

    for r in r0..=r1 {
        let row_off = r * ink_cols;
        for c in c0..=c1 {
            if let Some(&val) = ink_grid.get(row_off + c) {
                total += val as u64;
                if val >= 12 {
                    ink_cells += 1;
                }
                if val > max_val {
                    max_val = val;
                }
                count += 1;
            }
        }
    }

    if count == 0 || max_val < 12 {
        return 0.0;
    }

    (ink_cells as f64 / count as f64)
        + (total as f64 / (255.0 * count as f64))
        + (max_val as f64 / 255.0) * 0.35
}

/// Find a position (x, y) near (x_pt, y_pt) within bounds that minimizes overlap with ink and placed rects.
#[allow(clippy::too_many_arguments)]
pub fn find_clear_rect(
    ink_grid: &[u8],
    ink_cols: usize,
    ink_rows: usize,
    width_pt: f64,
    height_pt: f64,
    x_pt: f64,
    y_pt: f64,
    w_pt: f64,
    h_pt: f64,
    x_min_pt: f64,
    x_max_pt: f64,
    y_min_pt: f64,
    y_max_pt: f64,
    placed_rects: &[(f64, f64, f64, f64)],
    pad_pt: f64,
) -> (f64, f64) {
    let eff_x_max = x_min_pt.max(x_max_pt - w_pt);
    let eff_y_max = y_min_pt.max(y_max_pt - h_pt);
    let base_x = x_pt.clamp(x_min_pt, eff_x_max);
    let base_y = y_pt.clamp(y_min_pt, eff_y_max);

    let overlaps_placed = |cx: f64, cy: f64| -> bool {
        for &(px, py, pw, ph) in placed_rects {
            if cx < px + pw + 2.5
                && cx + w_pt + 2.5 > px
                && cy < py + ph + 1.5
                && cy + h_pt + 1.5 > py
            {
                return true;
            }
        }
        false
    };

    let dy_steps = [
        0.0, 2.0, -2.0, 4.0, -4.0, 6.0, -6.0, 8.0, -8.0, 10.0, 12.0, 14.0, 16.5, 19.0,
    ];
    let dx_steps = [
        0.0, 4.0, -4.0, 8.0, -8.0, 13.0, -12.0, 18.0, -17.0, 24.0, -22.0, 30.0, -28.0, 38.0, -34.0,
    ];

    let mut best_pos = (base_x, base_y);
    let mut best_score = f64::INFINITY;

    for &dy in &dy_steps {
        let mut cy = base_y + dy;
        if cy < y_min_pt - 0.1 || cy > eff_y_max + 0.1 {
            continue;
        }
        cy = cy.clamp(y_min_pt, eff_y_max);
        for &dx in &dx_steps {
            let mut cx = base_x + dx;
            if cx < x_min_pt - 0.1 || cx > eff_x_max + 0.1 {
                continue;
            }
            cx = cx.clamp(x_min_pt, eff_x_max);
            if overlaps_placed(cx, cy) {
                continue;
            }
            let ink = ink_density_in_rect(
                ink_grid, ink_cols, ink_rows, width_pt, height_pt, cx, cy, w_pt, h_pt, pad_pt,
            );
            let dist_penalty = (dx.abs() * 0.0012) + (dy.abs() * 0.0018);
            let score = ink + dist_penalty;
            if score < best_score {
                best_score = score;
                best_pos = (cx, cy);
                if ink == 0.0 && dist_penalty <= 0.006 {
                    return (cx, cy);
                }
            }
        }
    }

    best_pos
}

/// Downsample grayscale page image to ~2pt cells recording dark pixel density (0..255).
pub fn build_ink_grid(gray: &GrayImage, width_pt: f64, height_pt: f64) -> (Vec<u8>, usize, usize) {
    let cols = ((width_pt / 2.0).round() as usize).clamp(60, 360);
    let rows = ((height_pt / 2.0).round() as usize).clamp(80, 480);
    let (img_w, img_h) = gray.dimensions();
    let raw = gray.as_raw();
    let w_usize = img_w as usize;

    let mut grid = vec![0u8; cols * rows];
    for r in 0..rows {
        let y0 = (r * img_h as usize) / rows;
        let y1 = (((r + 1) * img_h as usize) / rows).max(y0 + 1).min(img_h as usize);
        for c in 0..cols {
            let x0 = (c * img_w as usize) / cols;
            let x1 = (((c + 1) * img_w as usize) / cols).max(x0 + 1).min(img_w as usize);
            let mut dark_sum: u32 = 0;
            let mut count: u32 = 0;
            for y in y0..y1 {
                let row_slice = &raw[y * w_usize + x0..y * w_usize + x1];
                for &px in row_slice {
                    if px < 212 {
                        dark_sum += 255;
                    }
                    count += 1;
                }
            }
            grid[r * cols + c] = if count > 0 {
                (dark_sum / count).min(255) as u8
            } else {
                0
            };
        }
    }

    (grid, cols, rows)
}

/// Remove non-staff outlier lines (e.g. volta brackets, text underlines, or 16th-note beams) from a line cluster.
pub fn clean_single_staff_cluster(cluster: &[f64]) -> Vec<f64> {
    if cluster.len() < 4 {
        return Vec::new();
    }
    let mut lines = cluster.to_vec();
    // Sort top to bottom in PDF points (descending)
    lines.sort_by(|a, b| b.partial_cmp(a).unwrap_or(std::cmp::Ordering::Equal));

    while lines.len() > 5 {
        let diffs: Vec<f64> = (0..lines.len() - 1).map(|j| lines[j] - lines[j + 1]).collect();
        let mut sorted_diffs = diffs.clone();
        sorted_diffs.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let med = sorted_diffs[sorted_diffs.len() / 2];
        if med <= 0.0 {
            break;
        }
        let dev_top = (diffs[0] - med).abs();
        let dev_bot = (diffs[diffs.len() - 1] - med).abs();
        if dev_top > med * 0.14 && dev_top >= dev_bot {
            lines.remove(0);
        } else if dev_bot > med * 0.14 {
            lines.pop();
        } else if lines.len() > 6 {
            if dev_top >= dev_bot {
                lines.remove(0);
            } else {
                lines.pop();
            }
        } else {
            break;
        }
    }

    if lines.len() < 4 || lines.len() > 6 {
        return Vec::new();
    }

    let diffs: Vec<f64> = (0..lines.len() - 1).map(|j| lines[j] - lines[j + 1]).collect();
    let mut sorted_diffs = diffs.clone();
    sorted_diffs.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let med = sorted_diffs[sorted_diffs.len() / 2];
    if !(2.2..=13.0).contains(&med) {
        return Vec::new();
    }
    let max_diff = diffs.iter().cloned().fold(0.0_f64, f64::max);
    if max_diff > med * 2.25 {
        return Vec::new();
    }

    lines
}

/// Detect horizontal staff lines directly from the contiguous grayscale buffer and group them into staves.
pub fn extract_staff_line_clusters(gray: &GrayImage, height_pt: f64) -> Vec<Vec<f64>> {
    let (img_w, img_h) = gray.dimensions();
    let w = img_w as usize;
    let h = img_h as usize;
    let raw = gray.as_raw();

    let x_full_0 = (w as f64 * 0.12) as usize;
    let x_full_1 = (w as f64 * 0.88) as usize;
    let span_full = ((x_full_1.saturating_sub(x_full_0)) / 2).max(1) as f64;

    let x_mid_0 = (w as f64 * 0.22) as usize;
    let x_mid_1 = (w as f64 * 0.78) as usize;
    let span_mid = ((x_mid_1.saturating_sub(x_mid_0)) / 2).max(1) as f64;

    let x_left_0 = (w as f64 * 0.10) as usize;
    let x_left_1 = (w as f64 * 0.42) as usize;
    let span_left = ((x_left_1.saturating_sub(x_left_0)) / 2).max(1) as f64;

    let top_limit = (h as f64 * 0.05) as usize;
    let bot_limit = (h as f64 * 0.96) as usize;

    let row_scores = |y: usize| -> (f64, f64, f64) {
        let row = &raw[y * w..(y + 1) * w];
        let dark_full = (x_full_0..x_full_1)
            .step_by(2)
            .filter(|&x| row[x] < 205)
            .count() as f64
            / span_full;
        let dark_mid = (x_mid_0..x_mid_1)
            .step_by(2)
            .filter(|&x| row[x] < 205)
            .count() as f64
            / span_mid;
        let dark_left = (x_left_0..x_left_1)
            .step_by(2)
            .filter(|&x| row[x] < 205)
            .count() as f64
            / span_left;
        (dark_full, dark_mid, dark_left)
    };

    let row_is_staff_line = |y: usize, threshold: f64| -> bool {
        let (df, dm, dl) = row_scores(y);
        df >= threshold || dm >= (threshold + 0.04) || dl >= (threshold + 0.08)
    };

    let max_single_run = ((h as f64 * 0.004) as usize).max(6);
    let mut line_ys_pt: Vec<f64> = Vec::new();
    let mut y = top_limit;

    while y < bot_limit {
        if row_is_staff_line(y, 0.51) {
            let y_start = y;
            while y < bot_limit && row_is_staff_line(y, 0.42) {
                y += 1;
            }
            let run_len = y - y_start;
            if run_len <= max_single_run {
                let y_mid = (y_start + y - 1) as f64 / 2.0;
                let pt = ((height_pt * (1.0 - y_mid / h as f64)) * 10.0).round() / 10.0;
                line_ys_pt.push(pt);
            } else if run_len <= max_single_run * 3 {
                let mid_vals: Vec<f64> = (y_start..y).map(|ry| row_scores(ry).1).collect();
                if mid_vals.len() >= 5 {
                    let mut v_idx = 1;
                    for k in 2..mid_vals.len() - 1 {
                        if mid_vals[k] < mid_vals[v_idx] {
                            v_idx = k;
                        }
                    }
                    let max_top = mid_vals[..v_idx].iter().cloned().fold(0.0_f64, f64::max);
                    let max_bot = mid_vals[v_idx + 1..].iter().cloned().fold(0.0_f64, f64::max);
                    if max_top >= 0.48
                        && max_bot >= 0.48
                        && mid_vals[v_idx] < max_top.min(max_bot) * 0.78
                    {
                        let y_split = y_start + v_idx;
                        if (y_split - y_start) <= max_single_run {
                            let ym1 = (y_start + y_split - 1) as f64 / 2.0;
                            let pt1 = ((height_pt * (1.0 - ym1 / h as f64)) * 10.0).round() / 10.0;
                            line_ys_pt.push(pt1);
                        }
                        if (y - (y_split + 1)) <= max_single_run && (y_split + 1) < y {
                            let ym2 = (y_split + 1 + y - 1) as f64 / 2.0;
                            let pt2 = ((height_pt * (1.0 - ym2 / h as f64)) * 10.0).round() / 10.0;
                            line_ys_pt.push(pt2);
                        }
                    }
                }
            }
        } else {
            y += 1;
        }
    }

    let mut raw_staves: Vec<Vec<f64>> = Vec::new();
    for ly in line_ys_pt {
        if raw_staves.is_empty()
            || (*raw_staves.last().unwrap().last().unwrap() - ly) > 13.5
        {
            raw_staves.push(vec![ly]);
        } else {
            raw_staves.last_mut().unwrap().push(ly);
        }
    }

    let mut valid_staves = Vec::new();
    for raw in raw_staves {
        let cleaned = clean_single_staff_cluster(&raw);
        if !cleaned.is_empty() {
            let span = cleaned[0] - *cleaned.last().unwrap();
            if (10.0..=64.0).contains(&span) {
                valid_staves.push(cleaned);
            }
        }
    }
    valid_staves
}

/// Locate musical staff systems (pairing Treble + TAB or Grand Staves) and bottom whitespace.
pub fn detect_staff_systems_from_image(
    gray: &GrayImage,
    _width_pt: f64,
    height_pt: f64,
) -> (Vec<StaffSystem>, f64) {
    let staves = extract_staff_line_clusters(gray, height_pt);

    let mut grand_staff_alternating = false;
    if staves.len() >= 4
        && staves.len() % 2 == 0
        && staves.iter().all(|s| s.len() == 4 || s.len() == 5)
    {
        let intra_gaps: Vec<f64> = (0..staves.len())
            .step_by(2)
            .map(|k| *staves[k].last().unwrap() - staves[k + 1][0])
            .collect();
        let inter_gaps: Vec<f64> = (1..staves.len() - 1)
            .step_by(2)
            .map(|k| *staves[k].last().unwrap() - staves[k + 1][0])
            .collect();
        if !intra_gaps.is_empty() && !inter_gaps.is_empty() {
            let avg_intra = intra_gaps.iter().sum::<f64>() / intra_gaps.len() as f64;
            let avg_inter = inter_gaps.iter().sum::<f64>() / inter_gaps.len() as f64;
            if avg_intra <= 52.0 && avg_intra < avg_inter * 0.72 {
                grand_staff_alternating = true;
            }
        }
    }

    let mut systems_bounds_pt: Vec<(f64, f64, f64)> = Vec::new();
    if !staves.is_empty() {
        let mut i = 0;
        while i < staves.len() {
            let curr = &staves[i];
            let curr_top = curr[0];
            let curr_bot = *curr.last().unwrap();
            let curr_step = (curr_top - curr_bot) / ((curr.len().saturating_sub(1)).max(1) as f64);
            let curr_treble_h = curr_step * 4.0;

            if i + 1 < staves.len() {
                let nxt = &staves[i + 1];
                let nxt_top = nxt[0];
                let nxt_bot = *nxt.last().unwrap();
                let nxt_step = (nxt_top - nxt_bot) / ((nxt.len().saturating_sub(1)).max(1) as f64);
                let gap = curr_bot - nxt_top;

                let is_treble_tab = (4..=6).contains(&curr.len())
                    && nxt.len() == 6
                    && nxt_step > curr_step * 1.08
                    && gap <= 155.0;

                let is_grand_staff = grand_staff_alternating
                    && i % 2 == 0
                    && (curr.len() == 4 || curr.len() == 5)
                    && (nxt.len() == 4 || nxt.len() == 5)
                    && gap <= 52.0;

                if is_treble_tab || is_grand_staff {
                    systems_bounds_pt.push((curr_top, nxt_bot, curr_treble_h));
                    i += 2;
                    continue;
                }
            }

            systems_bounds_pt.push((curr_top, curr_bot, curr_treble_h));
            i += 1;
        }
    }

    if systems_bounds_pt.is_empty() {
        for idx in 0..4 {
            let y_top_pt = height_pt * (0.85 - idx as f64 * 0.18);
            let y_bot_pt = y_top_pt - height_pt * 0.08;
            systems_bounds_pt.push((y_top_pt, y_bot_pt, 20.0));
        }
    }

    let mut systems = Vec::with_capacity(systems_bounds_pt.len());
    for (idx0, &(y_top_pt, y_bottom_pt, treble_h_pt)) in systems_bounds_pt.iter().enumerate() {
        let idx = idx0 + 1;
        let offset = if idx > 1 {
            let prev_bot = systems_bounds_pt[idx0 - 1].1;
            let avail_above = (prev_bot - y_top_pt).max(8.0);
            (treble_h_pt * 0.85)
                .min(avail_above * 0.48)
                .max(9.5)
                .min(18.5)
        } else {
            (treble_h_pt * 0.85).max(10.5).min(18.5)
        };
        let chord_y_pt = (y_top_pt + offset).min(height_pt - 30.0);
        systems.push(StaffSystem {
            index: idx,
            y_top_pt: (y_top_pt * 10.0).round() / 10.0,
            y_bottom_pt: (y_bottom_pt * 10.0).round() / 10.0,
            chord_y_pt: (chord_y_pt * 10.0).round() / 10.0,
            treble_height_pt: (treble_h_pt * 10.0).round() / 10.0,
        });
    }

    let lowest_system_bot_pt = systems_bounds_pt
        .iter()
        .map(|&(_, b, _)| b)
        .fold(f64::INFINITY, f64::min);
    let bottom_free_pt = ((lowest_system_bot_pt - 25.0).max(0.0) * 10.0).round() / 10.0;
    (systems, bottom_free_pt)
}

/// Minimal 5x7 bitmap font for drawing ASCII guide labels (`S1 y=980`, `x=150`) directly in Rust without external font dependencies.
fn glyph_5x7(ch: char) -> [u8; 7] {
    match ch {
        '0' => [0b01110, 0b10001, 0b10011, 0b10101, 0b11001, 0b10001, 0b01110],
        '1' => [0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110],
        '2' => [0b01110, 0b10001, 0b00001, 0b00010, 0b00100, 0b01000, 0b11111],
        '3' => [0b11110, 0b00001, 0b00001, 0b01110, 0b00001, 0b00001, 0b11110],
        '4' => [0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010],
        '5' => [0b11111, 0b10000, 0b11110, 0b00001, 0b00001, 0b10001, 0b01110],
        '6' => [0b00110, 0b01000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110],
        '7' => [0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000],
        '8' => [0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110],
        '9' => [0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00010, 0b01100],
        'S' => [0b01111, 0b10000, 0b10000, 0b01110, 0b00001, 0b00001, 0b11110],
        'x' => [0b00000, 0b00000, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001],
        'y' => [0b00000, 0b00000, 0b10001, 0b10001, 0b01111, 0b00001, 0b01110],
        '=' => [0b00000, 0b00000, 0b11111, 0b00000, 0b11111, 0b00000, 0b00000],
        _ => [0; 7],
    }
}

fn draw_text_5x7(img: &mut RgbImage, x0: u32, y0: u32, text: &str, color: Rgb<u8>) {
    let (w, h) = img.dimensions();
    let mut cx = x0;
    for ch in text.chars() {
        let rows = glyph_5x7(ch);
        for (ry, &bits) in rows.iter().enumerate() {
            for rx in 0..5 {
                if (bits & (1 << (4 - rx))) != 0 {
                    let px = cx + rx;
                    let py = y0 + ry as u32;
                    if px < w && py < h {
                        img.put_pixel(px, py, color);
                    }
                }
            }
        }
        cx += 6;
    }
}

/// Create an annotated copy of the page with system labels (S1, S2...) and an X-coordinate ruler.
pub fn write_guide_image(
    gray: &GrayImage,
    systems: &[StaffSystem],
    width_pt: f64,
    height_pt: f64,
    out_path: &Path,
) -> Result<()> {
    let (img_w, img_h) = gray.dimensions();
    let mut rgb = RgbImage::new(img_w, img_h);
    for y in 0..img_h {
        for x in 0..img_w {
            let Luma([v]) = *gray.get_pixel(x, y);
            rgb.put_pixel(x, y, Rgb([v, v, v]));
        }
    }

    // Draw vertical X-coordinate ruler every 50 PDF points
    let mut x_pt = 50;
    while (x_pt as f64) < width_pt {
        let px = (((x_pt as f64) / width_pt) * img_w as f64) as u32;
        if px < img_w {
            for y in 0..img_h {
                rgb.put_pixel(px, y, Rgb([220, 230, 242]));
            }
            draw_text_5x7(
                &mut rgb,
                px.saturating_add(2),
                6,
                &format!("x={x_pt}"),
                Rgb([41, 128, 185]),
            );
        }
        x_pt += 50;
    }

    // Draw detected system markers (S1, S2...) at their chord_y_pt height
    for sys in systems {
        let py = (((1.0 - (sys.chord_y_pt / height_pt)) * img_h as f64) as u32)
            .min(img_h.saturating_sub(1));
        for dy in 0..2 {
            let ry = (py + dy).min(img_h.saturating_sub(1));
            for x in 0..img_w {
                rgb.put_pixel(x, ry, Rgb([41, 128, 185]));
            }
        }
        let box_y0 = py.saturating_sub(14);
        let box_y1 = (py + 4).min(img_h.saturating_sub(1));
        for by in box_y0..=box_y1 {
            for bx in 4..78.min(img_w) {
                rgb.put_pixel(bx, by, Rgb([26, 82, 118]));
            }
        }
        draw_text_5x7(
            &mut rgb,
            8,
            py.saturating_sub(11),
            &format!("S{} y={}", sys.index, sys.chord_y_pt as i32),
            Rgb([255, 255, 255]),
        );
    }

    rgb.save(out_path)
        .with_context(|| format!("Failed to write guide PNG to {}", out_path.display()))?;
    Ok(())
}

/// Normalize musical sharp/flat Unicode symbols to standard ASCII `#` and `b`.
pub fn normalize_music_ascii(text: &str) -> String {
    text.replace('♯', "#")
        .replace('♭', "b")
        .replace('♮', "")
        .replace('𝄪', "##")
}

/// Extract title and positioned chord tokens (`page_num`, `x_pt`, `y_pt_from_bottom`, `token`) using `pdftotext -bbox-layout`.
pub fn extract_pdf_text_tokens(
    pdf_path: &Path,
    page_heights: &[f64],
) -> (String, Vec<ExtractedTextToken>) {
    let default_stem = pdf_path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("Score")
        .to_string();

    let output = match Command::new("pdftotext")
        .arg("-bbox-layout")
        .arg(pdf_path)
        .arg("-")
        .output()
    {
        Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).to_string(),
        _ => return (default_stem, Vec::new()),
    };

    let page_re = Regex::new(r#"<page\s+width="([0-9.]+)"\s+height="([0-9.]+)">"#).unwrap();
    let word_re = Regex::new(
        r#"<word\s+xMin="([0-9.]+)"\s+yMin="([0-9.]+)"\s+xMax="([0-9.]+)"\s+yMax="([0-9.]+)">([^<]+)</word>"#,
    )
    .unwrap();
    let chord_re = Regex::new(
        r"^(?:[A-GH][#b]?)(?:m|maj|min|dim|aug|sus)?(?:2|4|5|6|7|9|11|13)?(?:b5|#5|b9|#9)?(?:/[A-GH][#b]?)?$",
    )
    .unwrap();
    let bare_root_re = Regex::new(r"^[A-GH][#b]?$").unwrap();

    let mut title_parts: Vec<String> = Vec::new();
    let mut chord_tokens: Vec<ExtractedTextToken> = Vec::new();
    let mut current_page = 0usize;
    let mut current_h = 1169.0_f64;

    for line in output.lines() {
        if let Some(cap) = page_re.captures(line) {
            current_page += 1;
            current_h = cap
                .get(2)
                .and_then(|m| m.as_str().parse::<f64>().ok())
                .or_else(|| page_heights.get(current_page.saturating_sub(1)).copied())
                .unwrap_or(1169.0);
            continue;
        }
        if current_page == 0 {
            continue;
        }
        for cap in word_re.captures_iter(line) {
            let x_min: f64 = cap[1].parse().unwrap_or(0.0);
            let y_min_top: f64 = cap[2].parse().unwrap_or(0.0);
            let raw_html = cap[5].trim();
            if raw_html.is_empty() {
                continue;
            }
            let raw = raw_html
                .replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&quot;", "\"");
            // Filter out private-use SMuFL music glyphs (U+E000..U+F8FF)
            if raw.chars().all(|c| ('\u{E000}'..='\u{F8FF}').contains(&c)) {
                continue;
            }

            let y_bot = (current_h - y_min_top).max(0.0);
            if y_min_top <= 95.0 && current_page == 1 {
                if raw.chars().any(|c| c.is_alphabetic())
                    && raw != "Moderate"
                    && raw != "Andante"
                    && raw != "cantabile"
                    && !title_parts.contains(&raw)
                {
                    title_parts.push(raw.clone());
                }
            }

            let norm = normalize_music_ascii(&raw);
            // If previous token on the same staff line was a bare root (e.g. "G") and this token is "m"/"m6"/"m7", merge them
            if matches!(norm.as_str(), "m" | "m6" | "m7" | "dim" | "7") {
                if let Some(last) = chord_tokens.last_mut() {
                    if last.page_num == current_page
                        && (last.y_pt - y_bot).abs() <= 4.0
                        && (0.0..=22.0).contains(&(x_min - last.x_pt))
                        && bare_root_re.is_match(&last.token)
                    {
                        last.token = format!("{}{}", last.token, norm);
                        continue;
                    }
                }
            }

            for part in norm.split_whitespace() {
                if chord_re.is_match(part)
                    && !matches!(part, "A" | "I" | "V" | "m" | "p" | "a" | "i")
                {
                    chord_tokens.push(ExtractedTextToken {
                        page_num: current_page,
                        x_pt: (x_min * 10.0).round() / 10.0,
                        y_pt: (y_bot * 10.0).round() / 10.0,
                        token: part.to_string(),
                    });
                } else if part == "A" && y_min_top > 105.0 {
                    // Allow 'A' major chord when positioned in staff chord lane
                    chord_tokens.push(ExtractedTextToken {
                        page_num: current_page,
                        x_pt: (x_min * 10.0).round() / 10.0,
                        y_pt: (y_bot * 10.0).round() / 10.0,
                        token: "A".to_string(),
                    });
                }
            }
        }
    }

    let detected_title = if title_parts.is_empty() {
        default_stem
    } else {
        title_parts.join(" ")
    };

    (detected_title, chord_tokens)
}

/// Extract MediaBox (width_pt, height_pt) for each page of the PDF via `lopdf`.
pub fn extract_pdf_page_dimensions(pdf_path: &Path) -> Result<Vec<(f64, f64)>> {
    let doc = lopdf::Document::load(pdf_path)
        .with_context(|| format!("Failed to load PDF {}", pdf_path.display()))?;
    let pages = doc.get_pages();
    let mut dims = Vec::with_capacity(pages.len());

    for (&_page_num, &page_id) in &pages {
        let mut w_pt = 595.28_f64;
        let mut h_pt = 841.89_f64;
        if let Ok(page_obj) = doc.get_dictionary(page_id) {
            if let Ok(mb) = page_obj.get(b"MediaBox").and_then(|o| o.as_array()) {
                if mb.len() == 4 {
                    let x0 = obj_to_f64(&mb[0]).unwrap_or(0.0);
                    let y0 = obj_to_f64(&mb[1]).unwrap_or(0.0);
                    let x1 = obj_to_f64(&mb[2]).unwrap_or(w_pt);
                    let y1 = obj_to_f64(&mb[3]).unwrap_or(h_pt);
                    w_pt = (x1 - x0).abs();
                    h_pt = (y1 - y0).abs();
                }
            }
        }
        dims.push((w_pt, h_pt));
    }

    if dims.is_empty() {
        dims.push((595.28, 841.89));
    }
    Ok(dims)
}

fn obj_to_f64(obj: &lopdf::Object) -> Option<f64> {
    match obj {
        lopdf::Object::Real(v) => Some(*v as f64),
        lopdf::Object::Integer(v) => Some(*v as f64),
        _ => None,
    }
}

/// Full layout analysis pipeline: renders pages via `pdftoppm`, detects staff systems and 2pt ink grids,
/// generates clean + guide PNGs, and extracts PDF text/chord tokens.
pub fn analyze_pdf_layout_full(pdf_path: &Path, work_dir: &Path) -> Result<LayoutExtractionResult> {
    fs::create_dir_all(work_dir)?;
    let page_dims = extract_pdf_page_dimensions(pdf_path)?;
    let max_dim = page_dims
        .iter()
        .map(|&(w, h)| w.max(h))
        .fold(842.0_f64, f64::max);
    let effective_scale = (1400.0 / max_dim).min(1.45).max(0.85);
    let dpi = ((72.0 * effective_scale).round() as u32).clamp(72, 144);

    let ppm_prefix = work_dir.join("page_render");
    let status = Command::new("pdftoppm")
        .arg("-png")
        .arg("-r")
        .arg(dpi.to_string())
        .arg(pdf_path)
        .arg(&ppm_prefix)
        .status()
        .context("Failed to execute pdftoppm")?;
    if !status.success() {
        anyhow::bail!("pdftoppm exited with non-zero status: {status}");
    }

    // Collect rendered page PNG files in page order
    let mut rendered_pngs: Vec< std::path::PathBuf> = fs::read_dir(work_dir)?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .map(|s| s.starts_with("page_render-") && s.ends_with(".png"))
                .unwrap_or(false)
        })
        .collect();
    rendered_pngs.sort();

    let mut pages = Vec::with_capacity(page_dims.len());
    let mut heights = Vec::with_capacity(page_dims.len());

    for (idx, &(width_pt, height_pt)) in page_dims.iter().enumerate() {
        let page_num = idx + 1;
        heights.push(height_pt);
        let png_path = rendered_pngs.get(idx).cloned();

        if let Some(ref p_path) = png_path {
            let dyn_img = image::open(p_path)
                .with_context(|| format!("Failed to open rendered PNG {}", p_path.display()))?;
            let gray = dyn_img.to_luma8();
            let (systems, bottom_free_pt) =
                detect_staff_systems_from_image(&gray, width_pt, height_pt);
            let (ink_grid, ink_cols, ink_rows) = build_ink_grid(&gray, width_pt, height_pt);

            let (clean_png_path, guide_png_path) = if idx < 6 {
                let clean_dest = work_dir.join(format!("clean_p{page_num}.png"));
                fs::rename(p_path, &clean_dest).unwrap_or_else(|_| {
                    let _ = fs::copy(p_path, &clean_dest);
                });
                let guide_dest = work_dir.join(format!("guide_p{page_num}.png"));
                write_guide_image(&gray, &systems, width_pt, height_pt, &guide_dest)?;
                (
                    clean_dest.to_string_lossy().to_string(),
                    guide_dest.to_string_lossy().to_string(),
                )
            } else {
                let _ = fs::remove_file(p_path);
                (String::new(), String::new())
            };

            pages.push(PageLayout {
                page_num,
                width_pt,
                height_pt,
                systems,
                bottom_free_pt,
                clean_png_path,
                guide_png_path,
                ink_grid_b64: BASE64.encode(&ink_grid),
                ink_cols,
                ink_rows,
            });
        }
    }

    let (detected_title, chord_tokens) = extract_pdf_text_tokens(pdf_path, &heights);
    Ok(LayoutExtractionResult {
        detected_title,
        chord_tokens,
        pages,
    })
}
