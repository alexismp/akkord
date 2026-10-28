# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""PDF overlay and annotation engine using ReportLab and PyPDF."""

from __future__ import annotations

import io
import math
from pathlib import Path
from textwrap import wrap

import pypdf
from reportlab.lib.colors import HexColor, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from akkord.harmony import (
    ChordAnnotation,
    GuitarDiagram,
    HarmonyAnalysisResult,
    _ensure_all_systems_covered,
    extract_compact_chord_symbol,
    normalize_diagram_frets,
)
from akkord.i18n import t
from akkord.pdf_layout import PageLayout


# Register a Unicode TrueType font family (Arial on macOS, DejaVuSans on Linux/Cloud Run)
# so Cyrillic titles (Конь, Я в весеннем лесу, Ой то не вечер) and symbols render cleanly.
_FONTS_INITIALIZED = False
_FONT_REGULAR = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_FONT_ITALIC = "Helvetica-Oblique"
_UNICODE_FONT_ACTIVE = False


def _ensure_fonts() -> tuple[str, str, str, bool]:
    global _FONTS_INITIALIZED, _FONT_REGULAR, _FONT_BOLD, _FONT_ITALIC, _UNICODE_FONT_ACTIVE
    if _FONTS_INITIALIZED:
        return _FONT_REGULAR, _FONT_BOLD, _FONT_ITALIC, _UNICODE_FONT_ACTIVE

    _FONTS_INITIALIZED = True
    candidates = [
        (
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
        ),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        ),
        (
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
        ),
    ]
    for reg_path, bold_path, ital_path in candidates:
        if Path(reg_path).is_file() and Path(bold_path).is_file():
            try:
                pdfmetrics.registerFont(TTFont("AkkordSans", reg_path))
                pdfmetrics.registerFont(TTFont("AkkordSans-Bold", bold_path))
                if Path(ital_path).is_file():
                    pdfmetrics.registerFont(TTFont("AkkordSans-Italic", ital_path))
                else:
                    pdfmetrics.registerFont(TTFont("AkkordSans-Italic", reg_path))
                _FONT_REGULAR = "AkkordSans"
                _FONT_BOLD = "AkkordSans-Bold"
                _FONT_ITALIC = "AkkordSans-Italic"
                _UNICODE_FONT_ACTIVE = True
                break
            except Exception:
                continue

    return _FONT_REGULAR, _FONT_BOLD, _FONT_ITALIC, _UNICODE_FONT_ACTIVE


PILL_STYLES = {
    "added": {
        "fill": "#eef6fb",
        "stroke": "#2980b9",
        "text": "#0b3c5d",
    },
    "correct": {
        "fill": "#eafaf1",
        "stroke": "#27ae60",
        "text": "#145a32",
    },
    "improve": {
        "fill": "#fff3cd",
        "stroke": "#b45309",
        "text": "#451a03",
    },
    "missing": {
        "fill": "#fdedec",
        "stroke": "#c0392b",
        "text": "#78281f",
    },
}


def _sanitize_pdf_text(text: str) -> str:
    """Ensure text only contains glyphs supported by the active PDF font."""
    _, _, _, is_unicode = _ensure_fonts()
    text = (
        text.replace("↻", "*")
        .replace("✓", "OK ")
        .replace("♯", "#")
        .replace("♭", "b")
        .replace("♮", "")
        .replace("𝄪", "##")
    )
    if is_unicode:
        return text.strip()
    replacements = {
        "→": "->",
        "ø": "m7b5",
        "—": "-",
        "–": "-",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    cleaned = text.encode("cp1252", errors="ignore").decode("cp1252").strip()
    return cleaned or "Score"


def _format_pill_text(ann: ChordAnnotation, has_existing_chords: bool) -> str:
    """Format the text shown inside a chord pill, strictly keeping only compact chord symbols."""
    base_chord, _ = extract_compact_chord_symbol(ann.chord)
    base_chord = base_chord or ann.chord.strip()[:14]

    if not has_existing_chords or ann.status == "added":
        return _sanitize_pdf_text(base_chord)
    if ann.status == "correct":
        return _sanitize_pdf_text(f"OK {base_chord}")
    if ann.status == "improve":
        target, _ = extract_compact_chord_symbol(ann.suggested_chord)
        if target and target != base_chord:
            return _sanitize_pdf_text(f"* {base_chord} -> {target}")
        return _sanitize_pdf_text(f"* {base_chord}")
    if ann.status == "missing":
        target, _ = extract_compact_chord_symbol(ann.suggested_chord or ann.chord)
        target = target or base_chord
        return _sanitize_pdf_text(f"+ {target}")
    return _sanitize_pdf_text(base_chord)


def _resolve_system_y(
    page_layout: PageLayout, ann: ChordAnnotation, has_existing_chords: bool = False
) -> float:
    """Resolve the PDF Y coordinate for an annotation based on its system_index."""
    if ann.y_pt is not None and 20.0 <= ann.y_pt <= page_layout.height_pt - 20.0:
        return float(ann.y_pt)
    if page_layout.systems:
        idx = max(1, min(len(page_layout.systems), ann.system_index))
        base_y = page_layout.systems[idx - 1].chord_y_pt
        return min(
            page_layout.height_pt - 36.0,
            base_y + (7.5 if has_existing_chords else 0.0),
        )
    return page_layout.height_pt - 120.0 * max(1, ann.system_index)


def _system_vertical_bounds(
    page_layout: PageLayout, sys_idx: int, pill_h: float
) -> tuple[float, float]:
    """Return safe (y_min_pt, y_max_pt) above a staff system so pills never overlap the system above."""
    if not page_layout.systems:
        return (40.0, page_layout.height_pt - 28.0)
    idx0 = min(len(page_layout.systems) - 1, max(0, sys_idx - 1))
    sys_obj = page_layout.systems[idx0]
    y_min = sys_obj.y_top_pt + 3.0
    if idx0 > 0:
        prev_bot = page_layout.systems[idx0 - 1].y_bottom_pt
        y_max = max(y_min + pill_h + 1.0, prev_bot - 2.5)
    else:
        y_max = max(
            y_min + pill_h + 1.0,
            min(page_layout.height_pt - 22.0, sys_obj.y_top_pt + 44.0),
        )
    return (y_min, y_max)


def _get_suggested_chord_for_badge(ann: ChordAnnotation) -> str:
    """Return the compact suggested chord symbol to display inside an analysis footnote badge."""
    sugg, _ = extract_compact_chord_symbol(ann.suggested_chord)
    if sugg:
        return _sanitize_pdf_text(sugg)
    base, _ = extract_compact_chord_symbol(ann.chord)
    return _sanitize_pdf_text(base or ann.chord.strip()[:12])


def _measure_and_draw_chord_ref_badge(
    c: canvas.Canvas,
    font_bold: str,
    chord_label: str,
    note_num: int,
    style: dict[str, str],
    base_font_size: float = 7.4,
    pill_w: float = 28.5,
    pill_h: float = 11.2,
    rect_x: float | None = None,
    rect_y: float | None = None,
) -> tuple[float, float]:
    """Draw a uniform-sized badge containing the chord and (when note_num > 0) a bracketed superscript ref number."""
    ref_str = f"[{note_num}]" if note_num > 0 else ""
    chord_fs = base_font_size
    sup_fs = round(chord_fs * 0.54, 2)
    min_pad_x = 1.6
    gap_x = 1.0 if ref_str else 0.0
    max_content_w = pill_w - 2 * min_pad_x

    while chord_fs > 5.0:
        cw = c.stringWidth(chord_label, font_bold, chord_fs)
        sw = c.stringWidth(ref_str, font_bold, sup_fs) if ref_str else 0.0
        if (cw + gap_x + sw) <= max_content_w:
            break
        chord_fs = round(chord_fs - 0.3, 2)
        sup_fs = round(chord_fs * 0.54, 2)

    cw = c.stringWidth(chord_label, font_bold, chord_fs)
    sw = c.stringWidth(ref_str, font_bold, sup_fs) if ref_str else 0.0
    content_w = cw + gap_x + sw

    if rect_x is not None and rect_y is not None:
        c.setFillColor(HexColor(style["fill"]))
        c.setStrokeColor(HexColor(style["stroke"]))
        c.setLineWidth(0.75)
        c.roundRect(rect_x, rect_y, pill_w, pill_h, 2.5, fill=1, stroke=1)

        start_x = rect_x + max(min_pad_x, (pill_w - content_w) / 2.0)
        base_y = rect_y + (pill_h - chord_fs) * 0.42 + 0.6
        sup_y = base_y + chord_fs * 0.38

        c.setFillColor(HexColor(style["text"]))
        c.setFont(font_bold, chord_fs)
        c.drawString(start_x, base_y, chord_label)

        if ref_str:
            c.setFont(font_bold, sup_fs)
            c.drawString(start_x + cw + gap_x, sup_y, ref_str)

    return pill_w, pill_h


def _measure_barline_bounds_for_x(
    page_layout: PageLayout, sys_idx: int, x_pt: float
) -> tuple[float | None, float | None]:
    """Return (b_left, b_right) of the measure containing x_pt on system sys_idx, if barlines exist."""
    if not page_layout.systems:
        return None, None
    idx0 = min(len(page_layout.systems) - 1, max(0, sys_idx - 1))
    bars = page_layout.systems[idx0].barlines_x_pt
    if len(bars) < 2:
        return None, None
    for m_i in range(len(bars) - 1):
        b_l, b_r = bars[m_i], bars[m_i + 1]
        if (b_l - 4.0) <= x_pt < (b_r - 3.0):
            return b_l, b_r
    return None, None


def _draw_minimal_footnote_markers(
    c: canvas.Canvas,
    page_layout: PageLayout,
    numbered_page_anns: list[tuple[int, ChordAnnotation]],
) -> None:
    """Draw uniform-sized badges showing confirmed chords and suggested chords + bracketed reference numbers."""
    _, font_bold, _, _ = _ensure_fonts()
    by_system: dict[int, list[tuple[int, ChordAnnotation]]] = {}
    for note_num, ann in numbered_page_anns:
        by_system.setdefault(ann.system_index, []).append((note_num, ann))

    base_font_size = 7.2 if len(page_layout.systems) >= 6 else 7.5
    uniform_pill_w = 27.0 if len(page_layout.systems) >= 6 else 29.0
    uniform_pill_h = 10.8 if len(page_layout.systems) >= 6 else 11.4
    correct_pill_w = 20.0 if len(page_layout.systems) >= 6 else 21.5
    pad_x = 1.8
    pad_y = 1.5
    placed_rects: list[tuple[float, float, float, float]] = []

    for sys_idx, sys_items in by_system.items():
        sys_items.sort(key=lambda item: item[1].x_pt)
        last_right_edge = -1000.0

        max_raw_x = max((float(a.x_pt) for _, a in sys_items), default=0.0)
        min_raw_x = min((float(a.x_pt) for _, a in sys_items), default=80.0)
        usable_right = page_layout.width_pt - 58.0
        usable_left = min(96.0, max(45.0, min_raw_x))
        rescale_x = max_raw_x > (page_layout.width_pt - 32.0) and max_raw_x > min_raw_x

        for note_num, ann in sys_items:
            chord_label = _get_suggested_chord_for_badge(ann)
            if ann.status == "correct" or note_num <= 0:
                style_key = "correct"
                pill_w = correct_pill_w
            elif ann.status == "missing":
                style_key = "missing"
                pill_w = uniform_pill_w
            else:
                style_key = "improve"
                pill_w = uniform_pill_w
            style = PILL_STYLES[style_key]
            pill_h = uniform_pill_h

            raw_x = float(ann.x_pt)
            if rescale_x:
                raw_x = usable_left + ((raw_x - min_raw_x) / (max_raw_x - min_raw_x)) * (
                    usable_right - usable_left
                )

            y = _resolve_system_y(page_layout, ann, has_existing_chords=True)

            b_left, b_right = _measure_barline_bounds_for_x(page_layout, sys_idx, raw_x)
            measure_min_x = (b_left + 1.5) if b_left is not None else 32.0
            measure_max_x = (
                max(measure_min_x + pill_w + 1.0, b_right - 1.5)
                if b_right is not None
                else (page_layout.width_pt - 14.0)
            )

            x = max(measure_min_x + pad_x, min(page_layout.width_pt - pill_w - 20.0, raw_x))

            if x - pad_x < last_right_edge + 2.5:
                x = min(page_layout.width_pt - pill_w - 18.0, last_right_edge + 2.5 + pad_x)

            y_min, y_max = _system_vertical_bounds(page_layout, sys_idx, pill_h)
            rect_x, rect_y = page_layout.find_clear_rect(
                x_pt=x - pad_x,
                y_pt=y - pad_y,
                w_pt=pill_w,
                h_pt=pill_h,
                x_min_pt=max(32.0, measure_min_x, last_right_edge + 2.0, x - pad_x - 6.0),
                x_max_pt=min(page_layout.width_pt - 14.0, measure_max_x, x - pad_x + pill_w + 10.0),
                y_min_pt=y_min,
                y_max_pt=y_max,
                placed_rects=placed_rects,
                pad_pt=1.0,
            )
            placed_rects.append((rect_x, rect_y, pill_w, pill_h))

            _measure_and_draw_chord_ref_badge(
                c,
                font_bold,
                chord_label,
                note_num,
                style,
                base_font_size=base_font_size,
                pill_w=pill_w,
                pill_h=pill_h,
                rect_x=rect_x,
                rect_y=rect_y,
            )
            last_right_edge = rect_x + pill_w


def _condense_dense_system_annotations(
    sys_anns: list[ChordAnnotation], has_existing_chords: bool, page_width_pt: float
) -> list[ChordAnnotation]:
    """Deduplicate consecutive identical chords or overly dense bass alternations on a single system."""
    if has_existing_chords or len(sys_anns) <= 6:
        return sys_anns

    # Step 1: Collapse immediately adjacent identical chord labels if close horizontally
    deduped: list[ChordAnnotation] = []
    for ann in sys_anns:
        lbl = _format_pill_text(ann, has_existing_chords)
        if not lbl:
            continue
        if deduped:
            prev_lbl = _format_pill_text(deduped[-1], has_existing_chords)
            if lbl == prev_lbl and abs(float(ann.x_pt) - float(deduped[-1].x_pt)) < 110.0:
                continue
        deduped.append(ann)

    # Step 2: If still > 7 chords on a standard/narrow page, collapse rapid A -> A/B -> A -> A/B repeats
    max_per_sys = 7 if page_width_pt <= 640.0 else 8
    if len(deduped) > max_per_sys:
        compact: list[ChordAnnotation] = []
        i = 0
        while i < len(deduped):
            curr = deduped[i]
            compact.append(curr)
            if (
                i + 2 < len(deduped)
                and len(deduped) - len(compact) + (len(deduped) - i) > max_per_sys
            ):
                c0 = curr.chord.split("/")[0].strip()
                c1 = deduped[i + 1].chord.split("/")[0].strip()
                c2 = deduped[i + 2].chord.split("/")[0].strip()
                if c0 and c0 == c1 == c2 and (float(deduped[i + 2].x_pt) - float(curr.x_pt)) < 125.0:
                    # Keep the root chord and the slash inversion, skip the immediate return
                    compact.append(deduped[i + 1])
                    i += 3
                    continue
            i += 1
        deduped = compact

    return deduped


def _compute_adaptive_pill_metrics(
    c: canvas.Canvas,
    font_bold: str,
    page_layout: PageLayout,
    sys_idx: int,
    labels: list[str],
    has_existing_chords: bool,
) -> tuple[float, float, float]:
    """Compute (font_size, pad_x, pad_y) scaled to the score's staff height, system density, and chord count."""
    n_sys = len(page_layout.systems)
    idx0 = min(max(0, sys_idx - 1), max(0, n_sys - 1)) if n_sys else 0
    treble_h = page_layout.systems[idx0].treble_height_pt if n_sys else 20.0

    if n_sys and idx0 > 0:
        inter_gap = page_layout.systems[idx0 - 1].y_bottom_pt - page_layout.systems[idx0].y_top_pt
    else:
        inter_gap = 48.0

    # Base font size adapts to staff height (note size) and system density
    if treble_h <= 16.8 or inter_gap <= 34.0 or n_sys >= 7:
        font_size = 7.4
    elif treble_h <= 19.5 or inter_gap <= 42.0 or n_sys >= 6:
        font_size = 8.4
    elif n_sys == 5 or page_layout.width_pt < 620.0:
        font_size = 9.4
    else:
        font_size = 10.2 if has_existing_chords else 10.6

    pad_x = round(max(1.6, font_size * 0.24), 2)
    pad_y = round(max(1.0, font_size * 0.15), 2)

    # Ensure all pills on this system fit comfortably in a single horizontal line
    usable_span = max(220.0, page_layout.width_pt - 76.0)
    while font_size > 6.4 and labels:
        total_w = sum(
            c.stringWidth(lbl, font_bold, font_size) + 2 * pad_x + 4.0
            for lbl in labels
        )
        if total_w <= usable_span * 0.90:
            break
        font_size = round(font_size - 0.4, 2)
        pad_x = round(max(1.4, font_size * 0.22), 2)
        pad_y = round(max(0.9, font_size * 0.14), 2)

    return font_size, pad_x, pad_y


def _draw_chord_pills(
    c: canvas.Canvas,
    page_layout: PageLayout,
    annotations: list[ChordAnnotation],
    has_existing_chords: bool,
) -> None:
    """Draw adaptive, ink-aware, non-overlapping chord pills for a single page."""
    _, font_bold, _, _ = _ensure_fonts()
    by_system: dict[int, list[ChordAnnotation]] = {}
    for ann in annotations:
        by_system.setdefault(ann.system_index, []).append(ann)

    placed_rects: list[tuple[float, float, float, float]] = []

    for sys_idx, raw_sys_anns in by_system.items():
        raw_sys_anns.sort(key=lambda a: a.x_pt)
        sys_anns = _condense_dense_system_annotations(
            raw_sys_anns, has_existing_chords, page_layout.width_pt
        )
        labels = [
            lbl
            for lbl in (_format_pill_text(a, has_existing_chords) for a in sys_anns)
            if lbl
        ]
        if not labels:
            continue

        font_size, pad_x, pad_y = _compute_adaptive_pill_metrics(
            c, font_bold, page_layout, sys_idx, labels, has_existing_chords
        )
        pill_h = font_size + 2 * pad_y
        y_min, y_max = _system_vertical_bounds(page_layout, sys_idx, pill_h)

        # If the model returned 0..1000 normalized X coordinates exceeding the PDF page width,
        # linearly rescale the system's X coordinates to fit within the staff width.
        max_raw_x = max((float(a.x_pt) for a in sys_anns), default=0.0)
        min_raw_x = min((float(a.x_pt) for a in sys_anns), default=80.0)
        usable_right = page_layout.width_pt - 54.0
        usable_left = min(92.0, max(42.0, min_raw_x))
        rescale_x = max_raw_x > (page_layout.width_pt - 32.0) and max_raw_x > min_raw_x

        last_right_edge = -1000.0

        for ann in sys_anns:
            label = _format_pill_text(ann, has_existing_chords)
            if not label:
                continue

            c.setFont(font_bold, font_size)
            w = c.stringWidth(label, font_bold, font_size)
            pill_w = w + 2 * pad_x

            raw_x = float(ann.x_pt)
            if rescale_x:
                raw_x = usable_left + ((raw_x - min_raw_x) / (max_raw_x - min_raw_x)) * (
                    usable_right - usable_left
                )

            y = _resolve_system_y(page_layout, ann, has_existing_chords)

            b_left, b_right = _measure_barline_bounds_for_x(page_layout, sys_idx, raw_x)
            measure_min_x = (b_left + 1.5) if b_left is not None else 32.0
            measure_max_x = (
                max(measure_min_x + pill_w + 1.0, b_right - 1.5)
                if b_right is not None
                else (page_layout.width_pt - 14.0)
            )

            x = max(measure_min_x + pad_x, min(page_layout.width_pt - pill_w - 20.0, raw_x))

            # Enforce left-to-right monotonic ordering on the system
            if x - pad_x < last_right_edge + 3.0:
                x = min(
                    page_layout.width_pt - pill_w - 16.0,
                    last_right_edge + 3.0 + pad_x,
                )

            # Find a clear spot near (x, y) that avoids existing ink while staying anchored on Beat 1
            rect_x, rect_y = page_layout.find_clear_rect(
                x_pt=x - pad_x,
                y_pt=y - pad_y,
                w_pt=pill_w,
                h_pt=pill_h,
                x_min_pt=max(32.0, measure_min_x, last_right_edge + 2.5, x - pad_x - 6.0),
                x_max_pt=min(page_layout.width_pt - 14.0, measure_max_x, x - pad_x + pill_w + 10.0),
                y_min_pt=y_min,
                y_max_pt=y_max,
                placed_rects=placed_rects,
                pad_pt=1.2,
            )
            placed_rects.append((rect_x, rect_y, pill_w, pill_h))
            draw_x = rect_x + pad_x
            draw_y = rect_y + pad_y

            style_key = ann.status if has_existing_chords else "added"
            style = PILL_STYLES.get(style_key, PILL_STYLES["added"])

            c.setFillColor(HexColor(style["fill"]))
            c.setStrokeColor(HexColor(style["stroke"]))
            c.setLineWidth(0.6)
            c.roundRect(
                rect_x,
                rect_y,
                pill_w,
                pill_h,
                2.2,
                fill=1,
                stroke=1,
            )

            c.setFillColor(HexColor(style["text"]))
            c.drawString(draw_x, draw_y + (font_size * 0.09), label)

            last_right_edge = rect_x + pill_w


def _fretboard_diagram_rows_count(
    diagrams: list[GuitarDiagram], available_width: float
) -> tuple[int, int]:
    """Return (num_rows, cols_per_row) so guitar chord diagrams never overflow available_width."""
    shown = diagrams[:8]
    count = len(shown)
    if count == 0:
        return (0, 1)
    # Place at most 4 diagrams per row whenever there are >= 5 diagrams or on standard portrait pages
    max_cols = min(4, max(1, int((available_width + 10.0) // 105.0)))
    if count <= max_cols:
        return (1, count)
    cols = min(max_cols, math.ceil(count / 2))
    rows = math.ceil(count / cols)
    return (rows, cols)


def _draw_fretboard_diagrams(
    c: canvas.Canvas,
    diagrams: list[GuitarDiagram],
    start_x: float,
    top_y: float,
    available_width: float,
) -> float:
    """Draw up to 8 6-string guitar chord fretboard diagrams across multiple rows and return total height used."""
    _, font_bold, _, _ = _ensure_fonts()
    shown = diagrams[:8]
    if not shown:
        return 0.0

    rows, cols = _fretboard_diagram_rows_count(shown, available_width)
    str_space = 10.0
    fret_space = 15.0
    grid_w = 5 * str_space
    row_stride_y = 94.0

    # Distribute columns evenly across available_width without ever exceeding the frame
    if cols > 1:
        spacing_x = min(118.0, (available_width - grid_w - 12.0) / (cols - 1))
    else:
        spacing_x = 0.0

    for idx, diag in enumerate(shown):
        r = idx // cols
        col = idx % cols
        dx = start_x + col * spacing_x
        row_top_y = top_y - r * row_stride_y
        frets = normalize_diagram_frets(diag.name, diag.frets)

        raw_label = _sanitize_pdf_text(diag.name[:20])
        lbl_font = 9.2
        max_lbl_w = max(64.0, spacing_x - 6.0) if cols > 1 else available_width
        while lbl_font > 7.2 and c.stringWidth(raw_label, font_bold, lbl_font) > max_lbl_w:
            lbl_font -= 0.4
        c.setFont(font_bold, lbl_font)
        c.setFillColor(HexColor("#0b3c5d"))
        c.drawCentredString(
            dx + 2.5 * str_space, row_top_y + 20.0, raw_label
        )

        numeric_frets = [f for f in frets if isinstance(f, int) and f > 0]
        max_fret = max(numeric_frets) if numeric_frets else 0
        min_fret = min(numeric_frets) if numeric_frets else 1
        base_fret = 1 if max_fret <= 4 else min_fret

        c.setStrokeColor(HexColor("#2c3e50"))
        c.setLineWidth(2.4 if base_fret == 1 else 1.0)
        c.line(dx, row_top_y, dx + 5 * str_space, row_top_y)

        if base_fret > 1:
            c.setFont(font_bold, 7.2)
            c.setFillColor(HexColor("#2c3e50"))
            c.drawRightString(dx - 3.0, row_top_y - 10.0, f"{base_fret}fr")

        c.setLineWidth(0.7)
        for f in range(1, 5):
            fy = row_top_y - f * fret_space
            c.line(dx, fy, dx + 5 * str_space, fy)

        for s in range(6):
            sx = dx + s * str_space
            c.line(sx, row_top_y, sx, row_top_y - 4 * fret_space)

        for s, val in enumerate(frets):
            sx = dx + s * str_space
            if val == "x":
                c.setFont(font_bold, 8.5)
                c.setFillColor(HexColor("#c0392b"))
                c.drawCentredString(sx, row_top_y + 5.5, "x")
            elif val == 0:
                c.setStrokeColor(HexColor("#27ae60"))
                c.setLineWidth(1.2)
                c.circle(sx, row_top_y + 8.5, 3.0, fill=0, stroke=1)
            elif isinstance(val, int) and val > 0:
                rel_fret = max(1, min(4, val - base_fret + 1))
                fy = row_top_y - (rel_fret - 0.5) * fret_space
                c.setFillColor(HexColor("#1a5276"))
                c.circle(sx, fy, 4.0, fill=1, stroke=0)
                c.setFillColor(white)
                c.setFont(font_bold, 6.8)
                c.drawCentredString(sx, fy - 2.3, str(val))

    return rows * row_stride_y


def _compute_add_chords_summary_box_height(
    width_pt: float,
    result: HarmonyAnalysisResult,
    language: str,
) -> float:
    """Compute the required height for the guitar chord diagrams & counterpoint summary box."""
    margin_x = 39.4
    box_w = width_pt - 2 * margin_x
    avail_diag_w = box_w - 45.0
    rows, _ = _fretboard_diagram_rows_count(result.chord_diagrams, avail_diag_w)
    diag_h = rows * 94.0 if rows > 0 else 20.0
    notes_count = len(result.slash_chord_notes[:2]) + len(result.bass_line_proposals[:3])
    notes_h = (22.0 + notes_count * 22.0) if notes_count > 0 else 44.0
    return max(250.0, 56.0 + diag_h + notes_h + 28.0)


def _draw_add_chords_summary_box(
    c: canvas.Canvas,
    width_pt: float,
    box_bottom_y: float,
    box_height: float,
    result: HarmonyAnalysisResult,
    language: str,
) -> None:
    """Draw the guitar chord diagrams & slash-chord guide box with multi-row diagrams and strict text wrapping."""
    font_reg, font_bold, font_ital, _ = _ensure_fonts()
    margin_x = 39.4
    box_w = width_pt - 2 * margin_x
    inner_w = box_w - 31.2

    c.setStrokeColor(HexColor("#2c3e50"))
    c.setFillColor(HexColor("#f8f9fa"))
    c.setLineWidth(1.0)
    c.roundRect(margin_x, box_bottom_y, box_w, box_height, 6.0, fill=1, stroke=1)

    cursor_y = box_bottom_y + box_height - 22.0
    c.setFillColor(HexColor("#1a5276"))
    c.setFont(font_bold, 11.5)
    safe_title = _sanitize_pdf_text(result.title or "Score")
    title_str = t(language, "diagrams_title", title=safe_title)
    for t_line in _wrap_pdf_line(c, title_str, font_bold, 11.5, inner_w)[:2]:
        c.drawString(margin_x + 15.6, cursor_y, t_line)
        cursor_y -= 14.0

    diag_top_y = cursor_y - 28.0
    diag_used_h = _draw_fretboard_diagrams(
        c,
        result.chord_diagrams,
        start_x=margin_x + 22.6,
        top_y=diag_top_y,
        available_width=box_w - 45.0,
    )

    text_y = (diag_top_y - diag_used_h + 14.0) if diag_used_h > 0 else (cursor_y - 10.0)
    footer_ceil_y = box_bottom_y + 26.0

    if result.slash_chord_notes or result.bass_line_proposals:
        c.setFillColor(HexColor("#1a5276"))
        c.setFont(font_bold, 9.0)
        for st_line in _wrap_pdf_line(
            c, t(language, "slash_chords_title"), font_bold, 9.0, inner_w
        )[:1]:
            if text_y > footer_ceil_y:
                c.drawString(margin_x + 15.6, text_y, st_line)
                text_y -= 12.5
        c.setFillColor(HexColor("#2c3e50"))
        c.setFont(font_reg, 8.2)
        for note_item in result.slash_chord_notes[:2]:
            clean_note = _sanitize_pdf_text(note_item.lstrip("•- "))
            for line in _wrap_pdf_line(c, f"• {clean_note}", font_reg, 8.2, inner_w)[:2]:
                if text_y > footer_ceil_y:
                    c.drawString(margin_x + 15.6, text_y, line)
                    text_y -= 11.0
        for bp in result.bass_line_proposals[:3]:
            tag = (
                "Walking Bass"
                if bp.technique == "walking_bass"
                else ("Contrepoint" if language == "fr" else "Counterpoint")
            )
            m_lbl = f"m.{bp.measure_number} " if bp.measure_number else ""
            bp_line = f"• [{tag}] {m_lbl}{bp.original_chord} -> {bp.proposed_slash_chord} : {bp.explanation}"
            for line in _wrap_pdf_line(c, bp_line, font_reg, 8.2, inner_w)[:2]:
                if text_y > footer_ceil_y:
                    c.drawString(margin_x + 15.6, text_y, line)
                    text_y -= 11.0
    elif result.overall_summary:
        c.setFillColor(HexColor("#2c3e50"))
        c.setFont(font_reg, 8.5)
        for line in _wrap_pdf_line(c, result.overall_summary, font_reg, 8.5, inner_w)[:3]:
            if text_y > footer_ceil_y:
                c.drawString(margin_x + 15.6, text_y, line)
                text_y -= 12.0

    c.setFillColor(HexColor("#2c3e50"))
    c.setFont(font_ital, 8.0)
    footer_lines = _wrap_pdf_line(
        c, t(language, "add_chords_footer_note"), font_ital, 8.0, inner_w
    )
    if footer_lines:
        c.drawString(margin_x + 15.6, box_bottom_y + 11.0, footer_lines[0])


def _draw_analysis_summary_box(
    c: canvas.Canvas,
    width_pt: float,
    box_bottom_y: float,
    box_height: float,
    result: HarmonyAnalysisResult,
    language: str,
) -> None:
    """Draw the Harmonic Analysis & Chord Review summary box when existing chords were evaluated."""
    font_reg, font_bold, _, _ = _ensure_fonts()
    margin_x = 39.4
    box_w = width_pt - 2 * margin_x

    c.setStrokeColor(HexColor("#2c3e50"))
    c.setFillColor(HexColor("#f8f9fa"))
    c.setLineWidth(1.0)
    c.roundRect(margin_x, box_bottom_y, box_w, box_height, 6.0, fill=1, stroke=1)

    cursor_y = box_bottom_y + box_height - 20.0

    c.setFillColor(HexColor("#1a5276"))
    c.setFont(font_bold, 11.0)
    safe_title = _sanitize_pdf_text(result.title or "Score")
    if len(safe_title) > 32 and "(" in safe_title:
        safe_title = safe_title.split("(")[0].strip()
    if len(safe_title) > 36:
        safe_title = safe_title[:34].rstrip() + "…"
    c.drawString(
        margin_x + 15.0,
        cursor_y,
        _sanitize_pdf_text(t(language, "analysis_box_title", title=safe_title)),
    )

    cursor_y -= 14.5
    acc_text = _sanitize_pdf_text(
        t(language, "analysis_accuracy_label", score=result.accuracy_score)
    )
    c.setFont(font_bold, 9.8)
    c.setFillColor(
        HexColor("#145a32")
        if result.accuracy_score >= 80
        else HexColor("#7e5109")
        if result.accuracy_score >= 50
        else HexColor("#78281f")
    )
    c.drawString(margin_x + 15.0, cursor_y, acc_text)

    cursor_y -= 16.0
    c.setFont(font_bold, 8.5)
    c.setFillColor(HexColor("#34495e"))
    c.drawString(margin_x + 15.0, cursor_y, t(language, "analysis_legend"))

    cursor_y -= 16.0
    c.setFont(font_reg, 9.0)
    c.setFillColor(HexColor("#2c3e50"))
    for line in wrap(_sanitize_pdf_text(result.overall_summary), width=112)[:3]:
        c.drawString(margin_x + 15.0, cursor_y, line)
        cursor_y -= 12.5

    cursor_y -= 4.0
    col_left_x = margin_x + 15.0
    col_right_x = margin_x + box_w * 0.52

    def _wrap_bullet(text_item: str, width: int, max_lines: int = 4) -> list[str]:
        clean = _sanitize_pdf_text(text_item.lstrip("•- "))
        lines = wrap(f"• {clean}", width=width)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip(" ,;:-") + "…"
        return lines

    left_y = cursor_y
    c.setFont(font_bold, 9.5)
    c.setFillColor(HexColor("#b45309"))
    c.drawString(col_left_x, left_y, t(language, "section_improvements"))
    left_y -= 13.0
    c.setFont(font_reg, 8.4)
    c.setFillColor(HexColor("#2c3e50"))
    improvements = result.review_improvements or [
        f"m.{a.measure_number or '?'}: {a.chord} -> {a.suggested_chord} ({a.note or ''})"
        for a in result.annotations
        if a.status == "improve"
    ]
    if improvements:
        for item in improvements[:6]:
            for line in _wrap_bullet(item, width=56, max_lines=4):
                if left_y > box_bottom_y + 12.0:
                    c.drawString(col_left_x, left_y, line)
                    left_y -= 11.2
            left_y -= 2.0
    else:
        c.drawString(col_left_x, left_y, f"• {t(language, 'no_issues')}")

    right_y = cursor_y
    c.setFont(font_bold, 9.5)
    c.setFillColor(HexColor("#78281f"))
    c.drawString(col_right_x, right_y, t(language, "section_missing"))
    right_y -= 13.0
    c.setFont(font_reg, 8.4)
    c.setFillColor(HexColor("#2c3e50"))
    missing = result.review_missing or [
        f"m.{a.measure_number or '?'}: + {a.suggested_chord or a.chord} ({a.note or ''})"
        for a in result.annotations
        if a.status == "missing"
    ]
    if missing:
        for item in missing[:4]:
            for line in _wrap_bullet(item, width=54, max_lines=3):
                if right_y > box_bottom_y + 45.0:
                    c.drawString(col_right_x, right_y, line)
                    right_y -= 11.2
            right_y -= 2.0
    else:
        c.drawString(col_right_x, right_y, f"• {t(language, 'no_issues')}")
        right_y -= 13.0

    if result.bass_line_proposals and right_y > box_bottom_y + 28.0:
        right_y -= 4.0
        c.setFont(font_bold, 9.2)
        c.setFillColor(HexColor("#1a5276"))
        c.drawString(col_right_x, right_y, t(language, "section_bass_proposals"))
        right_y -= 12.5
        c.setFont(font_reg, 8.2)
        c.setFillColor(HexColor("#2c3e50"))
        for bp in result.bass_line_proposals[:4]:
            tag = (
                "Walking"
                if bp.technique == "walking_bass"
                else ("Contrep." if language == "fr" else "Counterp.")
            )
            m_lbl = f"m.{bp.measure_number} " if bp.measure_number else ""
            bp_str = f"[{tag}] {m_lbl}({bp.proposed_slash_chord}) : {bp.explanation}"
            for line in _wrap_bullet(bp_str, width=55, max_lines=4):
                if right_y > box_bottom_y + 10.0:
                    c.drawString(col_right_x, right_y, line)
                    right_y -= 10.8
            right_y -= 2.0
    elif result.review_correct and right_y > box_bottom_y + 30.0:
        right_y -= 4.0
        c.setFont(font_bold, 9.0)
        c.setFillColor(HexColor("#145a32"))
        c.drawString(col_right_x, right_y, t(language, "section_correct"))
        right_y -= 12.0
        c.setFont(font_reg, 8.3)
        c.setFillColor(HexColor("#2c3e50"))
        for item in result.review_correct[:3]:
            for line in _wrap_bullet(item, width=54, max_lines=3):
                if right_y > box_bottom_y + 10.0:
                    c.drawString(col_right_x, right_y, line)
                    right_y -= 11.0


def _wrap_pdf_line(
    c: canvas.Canvas,
    text: str,
    font_name: str,
    font_size: float,
    max_width_pt: float,
) -> list[str]:
    """Wrap text into lines guaranteed not to exceed `max_width_pt` in points using actual font metrics."""
    cleaned = _sanitize_pdf_text(text)
    if not cleaned:
        return []
    words = cleaned.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        if c.stringWidth(candidate, font_name, font_size) <= max_width_pt:
            current = candidate
        else:
            if current:
                lines.append(current)
            # If a single word is wider than max_width_pt, split it
            if c.stringWidth(word, font_name, font_size) <= max_width_pt:
                current = word
            else:
                chunk = ""
                for ch in word:
                    if c.stringWidth(chunk + ch, font_name, font_size) <= max_width_pt:
                        chunk += ch
                    else:
                        if chunk:
                            lines.append(chunk)
                        chunk = ch
                current = chunk
    if current:
        lines.append(current)
    return lines


def _append_analysis_notes_pages(
    writer: pypdf.PdfWriter,
    page_w: float,
    page_h: float,
    result: HarmonyAnalysisResult,
    numbered_notes: list[tuple[int, ChordAnnotation]],
    language: str,
) -> None:
    """Append one or more dedicated pages at the end of the PDF with the full harmonic review and footnote explanations."""
    font_reg, font_bold, _, _ = _ensure_fonts()
    margin_x = 38.0
    content_w = page_w - 2 * margin_x
    inner_pad_x = 14.0
    inner_w = content_w - 2 * inner_pad_x
    top_margin = 46.0
    bottom_margin = 44.0

    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(page_w, page_h))
    cursor_y = page_h - top_margin

    raw_subtitle = _sanitize_pdf_text(
        t(language, "analyze_chords_subtitle", key=result.detected_key or "Am")
    )

    def start_new_page() -> None:
        nonlocal cursor_y
        c.showPage()
        cursor_y = page_h - top_margin
        sub_lines = _wrap_pdf_line(c, raw_subtitle, font_bold, 10.0, content_w)
        c.setFont(font_bold, 10.0)
        c.setFillColor(HexColor("#1a5276"))
        for sline in sub_lines:
            c.drawString(margin_x, cursor_y, sline)
            cursor_y -= 13.5
        cursor_y -= 8.0

    def ensure_space(needed_h: float) -> None:
        if cursor_y - needed_h < bottom_margin:
            start_new_page()

    # Prepare wrapped lines for the header card so nothing ever overlaps or overflows horizontally
    title_lines = _wrap_pdf_line(c, raw_subtitle, font_bold, 11.5, inner_w)

    safe_title = _sanitize_pdf_text(result.title or "Score")
    if len(safe_title) > 38 and "(" in safe_title:
        safe_title = safe_title.split("(")[0].strip()
    if len(safe_title) > 44:
        safe_title = safe_title[:42].rstrip() + "…"
    box_title_str = _sanitize_pdf_text(t(language, "analysis_box_title", title=safe_title))
    box_title_lines = _wrap_pdf_line(c, box_title_str, font_bold, 10.0, inner_w)

    acc_text = _sanitize_pdf_text(
        t(language, "analysis_accuracy_label", score=result.accuracy_score)
    )
    legend_note = _sanitize_pdf_text(
        "Badges sur la partition : Accord suggere + n° de renvoi en exposant (Orange = Amelioration / Basse, Rouge = Accord manquant)"
        if language == "fr"
        else "Score badges: Suggested chord + superscript ref # (Amber = Chord / Bass improvement, Red = Missing chord)"
    )
    legend_lines = _wrap_pdf_line(c, legend_note, font_bold, 8.2, inner_w)

    card_h = (
        14.0
        + len(title_lines) * 14.5
        + 4.0
        + len(box_title_lines) * 13.0
        + 14.5  # dedicated row for accuracy score (never shares Y with box_title_str!)
        + 3.0
        + len(legend_lines) * 11.5
        + 10.0
    )

    c.setFillColor(HexColor("#f0f7fc"))
    c.setStrokeColor(HexColor("#2980b9"))
    c.setLineWidth(1.0)
    c.roundRect(margin_x, cursor_y - card_h, content_w, card_h, 6.0, fill=1, stroke=1)

    header_y = cursor_y - 16.0
    c.setFont(font_bold, 11.5)
    c.setFillColor(HexColor("#0b3c5d"))
    for tline in title_lines:
        c.drawString(margin_x + inner_pad_x, header_y, tline)
        header_y -= 14.5

    header_y -= 2.0
    c.setFont(font_bold, 10.0)
    c.setFillColor(HexColor("#1a5276"))
    for btline in box_title_lines:
        c.drawString(margin_x + inner_pad_x, header_y, btline)
        header_y -= 13.0

    # Dedicated line for the accuracy score badge/text so it never collides with Russian/French titles
    c.setFont(font_bold, 9.8)
    c.setFillColor(
        HexColor("#145a32")
        if result.accuracy_score >= 80
        else HexColor("#7e5109")
        if result.accuracy_score >= 50
        else HexColor("#78281f")
    )
    c.drawString(margin_x + inner_pad_x, header_y, acc_text)
    header_y -= 14.5

    c.setFont(font_bold, 8.2)
    c.setFillColor(HexColor("#34495e"))
    for lline in legend_lines:
        c.drawString(margin_x + inner_pad_x, header_y, lline)
        header_y -= 11.5

    cursor_y -= card_h + 16.0

    # Overall summary paragraph
    if result.overall_summary:
        summary_lines = _wrap_pdf_line(
            c, result.overall_summary, font_reg, 9.5, content_w
        )
        ensure_space(len(summary_lines) * 13.5 + 12.0)
        c.setFont(font_reg, 9.5)
        c.setFillColor(HexColor("#1e293b"))
        for line in summary_lines:
            c.drawString(margin_x, cursor_y, line)
            cursor_y -= 13.5
        cursor_y -= 10.0

    # Section 1: Numbered Footnotes referenced from the score ([1], [2], ...)
    if numbered_notes:
        ensure_space(36.0)
        c.setFont(font_bold, 10.8)
        c.setFillColor(HexColor("#1a5276"))
        notes_heading = (
            f"Notes detaillees renvoyees depuis la partition ([1] a [{len(numbered_notes)}]) :"
            if language == "fr"
            else f"Detailed Score Footnotes ([1] to [{len(numbered_notes)}]):"
        )
        c.drawString(margin_x, cursor_y, _sanitize_pdf_text(notes_heading))
        cursor_y -= 16.0

        for note_num, ann in numbered_notes:
            base_chord, _ = extract_compact_chord_symbol(ann.chord)
            base_chord = base_chord or ann.chord.strip()[:14]
            sugg_chord, _ = extract_compact_chord_symbol(ann.suggested_chord)
            if ann.status == "missing":
                chord_change = f"+ {sugg_chord or base_chord}"
                style = PILL_STYLES["missing"]
            else:
                chord_change = (
                    f"* {base_chord} -> {sugg_chord}"
                    if sugg_chord and sugg_chord != base_chord
                    else f"* {base_chord}"
                )
                style = PILL_STYLES["improve"]

            sys_lbl = (
                f"Systeme {ann.system_index}"
                if language == "fr"
                else f"System {ann.system_index}"
            )
            meas_lbl = (
                f", Mesure {ann.measure_number}"
                if (ann.measure_number and language == "fr")
                else (f", Measure {ann.measure_number}" if ann.measure_number else "")
            )
            header_line = _sanitize_pdf_text(
                f"{sys_lbl}{meas_lbl} : {chord_change}"
            )

            chord_badge_lbl = _get_suggested_chord_for_badge(ann)
            bw = 29.0
            bh = 12.2
            note_indent = bw + 8.0
            note_avail_w = content_w - note_indent

            note_body = _sanitize_pdf_text(ann.note or "")
            wrapped_body = (
                _wrap_pdf_line(c, note_body, font_reg, 9.0, note_avail_w)
                if note_body
                else []
            )
            block_h = 18.0 + len(wrapped_body) * 12.8 + 6.0
            ensure_space(block_h)

            # Draw uniform badge (suggested chord + superscript ref number)
            _measure_and_draw_chord_ref_badge(
                c,
                font_bold,
                chord_badge_lbl,
                note_num,
                style,
                base_font_size=7.8,
                pill_w=bw,
                pill_h=bh,
                rect_x=margin_x,
                rect_y=cursor_y - 2.6,
            )

            # Draw header next to badge
            c.setFont(font_bold, 9.4)
            c.setFillColor(HexColor(style["text"]))
            c.drawString(margin_x + note_indent, cursor_y, header_line)
            cursor_y -= 14.0

            if wrapped_body:
                c.setFont(font_reg, 9.0)
                c.setFillColor(HexColor("#2c3e50"))
                for bline in wrapped_body:
                    c.drawString(margin_x + note_indent, cursor_y, bline)
                    cursor_y -= 12.8
            cursor_y -= 5.0

        cursor_y -= 6.0

    def draw_bullet_section(heading: str, color_hex: str, items: list[str]) -> None:
        nonlocal cursor_y
        if not items:
            return
        ensure_space(32.0)
        c.setFont(font_bold, 10.5)
        c.setFillColor(HexColor(color_hex))
        c.drawString(margin_x, cursor_y, _sanitize_pdf_text(heading))
        cursor_y -= 15.0

        for item in items:
            clean = _sanitize_pdf_text(item.lstrip("•- "))
            lines = _wrap_pdf_line(
                c, f"• {clean}", font_reg, 9.0, content_w - 10.0
            )
            ensure_space(len(lines) * 12.8 + 4.0)
            c.setFont(font_reg, 9.0)
            c.setFillColor(HexColor("#2c3e50"))
            for l_idx, line in enumerate(lines):
                c.drawString(margin_x + (10.0 if l_idx > 0 else 0.0), cursor_y, line)
                cursor_y -= 12.8
            cursor_y -= 3.0
        cursor_y -= 6.0

    # Section 2: Suggested Chord & Bass Improvements
    improvements = result.review_improvements or [
        f"m.{a.measure_number or '?'}: {a.chord} -> {a.suggested_chord} ({a.note or ''})"
        for a in result.annotations
        if a.status == "improve"
    ]
    draw_bullet_section(
        t(language, "section_improvements"),
        "#b45309",
        improvements or [t(language, "no_issues")],
    )

    # Section 3: Missing Chords Detected
    missing = result.review_missing or [
        f"m.{a.measure_number or '?'}: + {a.suggested_chord or a.chord} ({a.note or ''})"
        for a in result.annotations
        if a.status == "missing"
    ]
    draw_bullet_section(
        t(language, "section_missing"),
        "#78281f",
        missing or [t(language, "no_issues")],
    )

    # Section 4: Counterpoint & Walking Bass Proposals
    if result.bass_line_proposals:
        bass_items: list[str] = []
        for bp in result.bass_line_proposals:
            tag = (
                "Walking Bass"
                if bp.technique == "walking_bass"
                else ("Contrepoint" if language == "fr" else "Counterpoint")
            )
            m_lbl = f"m.{bp.measure_number} " if bp.measure_number else ""
            bass_items.append(
                f"[{tag}] {m_lbl}({bp.original_chord} -> {bp.proposed_slash_chord}) : {bp.explanation}"
            )
        draw_bullet_section(
            t(language, "section_bass_proposals"),
            "#1a5276",
            bass_items,
        )

    # Section 5: Confirmed Accurate Chords
    if result.review_correct:
        draw_bullet_section(
            t(language, "section_correct"),
            "#145a32",
            result.review_correct,
        )

    # Section 6: Guitar Chord Diagrams (if available)
    if result.chord_diagrams:
        diag_title_str = _sanitize_pdf_text(
            t(language, "diagrams_title", title=safe_title)
        )
        diag_title_lines = _wrap_pdf_line(
            c, diag_title_str, font_bold, 10.5, content_w
        )
        diag_rows, _ = _fretboard_diagram_rows_count(
            result.chord_diagrams, content_w - 24.0
        )
        needed_diag_h = diag_rows * 94.0 + 34.0 + len(diag_title_lines) * 14.0
        ensure_space(needed_diag_h)
        cursor_y -= 6.0
        c.setFont(font_bold, 10.5)
        c.setFillColor(HexColor("#1a5276"))
        for dt_line in diag_title_lines:
            c.drawString(margin_x, cursor_y, dt_line)
            cursor_y -= 14.0
        used_h = _draw_fretboard_diagrams(
            c,
            result.chord_diagrams,
            start_x=margin_x + 12.0,
            top_y=cursor_y - 26.0,
            available_width=content_w - 24.0,
        )
        cursor_y -= used_h + 26.0

    c.save()
    packet.seek(0)
    notes_reader = pypdf.PdfReader(packet)
    for npage in notes_reader.pages:
        writer.add_page(npage)


def annotate_music_sheet_pdf(
    input_pdf_path: Path,
    output_pdf_path: Path,
    layouts: list[PageLayout],
    result: HarmonyAnalysisResult,
    language: str = "fr",
) -> Path:
    """Create the annotated PDF.

    - In `analyze` mode (`result.has_existing_chords == True`): draws only minimal numbered
      footnote badges (`[1]`, `[2]`, ...) on the score and appends dedicated new page(s) at
      the end of the PDF with all detailed harmonic analysis notes, bass counterpoint proposals,
      and chord diagrams.
    - In `add_chords` mode (`result.has_existing_chords == False`): overlays chord pills above
      each staff system and adds the guitar chord diagrams box.
    """
    _, font_bold, _, _ = _ensure_fonts()
    reader = pypdf.PdfReader(str(input_pdf_path))
    writer = pypdf.PdfWriter()

    num_pages = len(reader.pages)
    last_layout = layouts[-1]

    if result.has_existing_chords:
        # Build ordered footnote list ([1], [2], ...) for all improve/missing annotations
        actionable_anns = sorted(
            [a for a in result.annotations if a.status in ("improve", "missing")],
            key=lambda a: (a.page_num, a.system_index, a.x_pt),
        )
        numbered_notes: list[tuple[int, ChordAnnotation]] = [
            (idx + 1, ann) for idx, ann in enumerate(actionable_anns)
        ]

        for idx, page in enumerate(reader.pages):
            page_num = idx + 1
            layout = layouts[idx]
            page_numbered = [
                (num, ann) for num, ann in numbered_notes if ann.page_num == page_num
            ] + [
                (0, ann)
                for ann in result.annotations
                if ann.page_num == page_num and ann.status == "correct"
            ]

            packet = io.BytesIO()
            c = canvas.Canvas(packet, pagesize=(layout.width_pt, layout.height_pt))

            if page_num == 1:
                c.setFont(font_bold, 8.2)
                c.setFillColor(HexColor("#1a5276"))
                ref_label = _sanitize_pdf_text(
                    f"Notes d'analyse [1..{len(numbered_notes)}] -> voir pages ajoutees"
                    if language == "fr"
                    else f"Analysis notes [1..{len(numbered_notes)}] -> see appended pages"
                )
                lbl_w = c.stringWidth(ref_label, font_bold, 8.2) + 8.0
                lbl_h = 11.5
                rx, ry = layout.find_clear_rect(
                    x_pt=layout.width_pt - 36.0 - lbl_w,
                    y_pt=layout.height_pt - 18.5,
                    w_pt=lbl_w,
                    h_pt=lbl_h,
                    x_min_pt=32.0,
                    x_max_pt=layout.width_pt - 24.0,
                    y_min_pt=layout.height_pt - 26.0,
                    y_max_pt=layout.height_pt - 4.0,
                )
                c.setFillColor(HexColor("#f8f9fa"))
                c.roundRect(rx, ry, lbl_w, lbl_h, 2.0, fill=1, stroke=0)
                c.setFillColor(HexColor("#1a5276"))
                c.drawString(rx + 4.0, ry + 2.2, ref_label)

            _draw_minimal_footnote_markers(c, layout, page_numbered)
            c.save()
            packet.seek(0)
            overlay_reader = pypdf.PdfReader(packet)
            added_page = writer.add_page(page)
            if overlay_reader.pages:
                added_page.merge_page(overlay_reader.pages[0])

        _append_analysis_notes_pages(
            writer=writer,
            page_w=last_layout.width_pt,
            page_h=last_layout.height_pt,
            result=result,
            numbered_notes=numbered_notes,
            language=language,
        )
    else:
        if layouts and result.annotations:
            _ensure_all_systems_covered(result, layouts)

        required_box_h = _compute_add_chords_summary_box_height(
            last_layout.width_pt, result, language
        )
        margin_x = 39.4
        box_w = last_layout.width_pt - 2 * margin_x
        bottom_ink = last_layout.ink_density_in_rect(
            margin_x, 20.0, box_w, required_box_h, pad_pt=2.0
        )
        summary_fits_on_last_page = (
            last_layout.bottom_free_pt >= (required_box_h + 24.0)
            and bottom_ink <= 0.005
        )

        for idx, page in enumerate(reader.pages):
            page_num = idx + 1
            layout = layouts[idx]
            page_anns = [a for a in result.annotations if a.page_num == page_num]

            packet = io.BytesIO()
            c = canvas.Canvas(packet, pagesize=(layout.width_pt, layout.height_pt))

            if page_num == 1:
                sub_font_size = 8.2
                c.setFont(font_bold, sub_font_size)
                sub_text = _sanitize_pdf_text(
                    t(language, "add_chords_subtitle", key=result.detected_key or "Am")
                )
                sub_w = c.stringWidth(sub_text, font_bold, sub_font_size) + 10.0
                sub_h = sub_font_size + 4.0
                # Place the subtitle in the top margin strip, avoiding any existing title ink
                rx, ry = layout.find_clear_rect(
                    x_pt=(layout.width_pt - sub_w) / 2.0,
                    y_pt=layout.height_pt - 16.5,
                    w_pt=sub_w,
                    h_pt=sub_h,
                    x_min_pt=24.0,
                    x_max_pt=layout.width_pt - 24.0,
                    y_min_pt=max(
                        (
                            layout.systems[0].chord_y_pt + 18.0
                            if layout.systems
                            else layout.height_pt - 48.0
                        ),
                        layout.height_pt - 36.0,
                    ),
                    y_max_pt=layout.height_pt - 3.0,
                )
                c.setFillColor(HexColor("#f8f9fa"))
                c.setStrokeColor(HexColor("#d6eaf8"))
                c.setLineWidth(0.5)
                c.roundRect(rx, ry, sub_w, sub_h, 2.5, fill=1, stroke=1)
                c.setFillColor(HexColor("#1a5276"))
                c.drawString(rx + 5.0, ry + 2.5, sub_text)

            _draw_chord_pills(c, layout, page_anns, has_existing_chords=False)

            if page_num == num_pages and summary_fits_on_last_page:
                box_height = min(required_box_h, layout.bottom_free_pt - 20.0)
                box_bottom_y = max(
                    20.0, (layout.bottom_free_pt - box_height) / 2.0 + 8.0
                )
                _draw_add_chords_summary_box(
                    c, layout.width_pt, box_bottom_y, box_height, result, language
                )

            c.save()
            packet.seek(0)
            overlay_reader = pypdf.PdfReader(packet)
            added_page = writer.add_page(page)
            if overlay_reader.pages:
                added_page.merge_page(overlay_reader.pages[0])

        if not summary_fits_on_last_page:
            packet = io.BytesIO()
            c = canvas.Canvas(
                packet, pagesize=(last_layout.width_pt, last_layout.height_pt)
            )
            box_h = min(last_layout.height_pt - 56.0, required_box_h)
            box_bottom_y = max(28.0, last_layout.height_pt - box_h - 36.0)
            _draw_add_chords_summary_box(
                c,
                last_layout.width_pt,
                box_bottom_y,
                box_h,
                result,
                language,
            )
            c.save()
            packet.seek(0)
            extra_reader = pypdf.PdfReader(packet)
            if extra_reader.pages:
                writer.add_page(extra_reader.pages[0])

    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_pdf_path, "wb") as f:
        writer.write(f)

    return output_pdf_path
