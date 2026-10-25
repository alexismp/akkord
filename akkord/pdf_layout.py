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
"""PDF page rendering, staff system Y-coordinate detection, and visual guide generation."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import pypdf
import pypdfium2 as pdfium


@dataclass
class StaffSystem:
    """Detected staff system on a music sheet page (in PDF points, origin at bottom-left)."""

    index: int  # 1-based system index on the page (1 = topmost system)
    y_top_pt: float  # Top of the upper staff (PDF points from bottom)
    y_bottom_pt: float  # Bottom of the system (PDF points from bottom)
    chord_y_pt: float  # Recommended Y coordinate in PDF points to place chord pills
    treble_height_pt: float = 20.0  # Height of the upper staff in PDF points (reflects note/staff scale)


@dataclass
class PageLayout:
    """Layout metadata and rendered images for a single PDF page."""

    page_num: int  # 1-based page number
    width_pt: float
    height_pt: float
    systems: list[StaffSystem] = field(default_factory=list)
    bottom_free_pt: float = 0.0  # Blank space at the bottom of the page in PDF points
    clean_png_bytes: bytes = b""
    guide_png_bytes: bytes = b""
    ink_grid: bytes = b""  # Downsampled occupancy map (0..255 dark density per cell)
    ink_cols: int = 0
    ink_rows: int = 0

    def clear_image_buffers(self) -> None:
        """Free the in-memory PNG byte buffers as soon as Gemini analysis is complete."""
        self.clean_png_bytes = b""
        self.guide_png_bytes = b""

    def ink_density_in_rect(
        self,
        x_pt: float,
        y_pt: float,
        w_pt: float,
        h_pt: float,
        pad_pt: float = 1.0,
    ) -> float:
        """Return average dark-pixel occupancy (0.0 = blank paper, 1.0 = solid ink) in a PDF rect."""
        if not self.ink_grid or self.ink_cols <= 0 or self.ink_rows <= 0:
            return 0.0
        x0 = max(0.0, x_pt - pad_pt)
        x1 = min(self.width_pt, x_pt + w_pt + pad_pt)
        y0 = max(0.0, y_pt - pad_pt)
        y1 = min(self.height_pt, y_pt + h_pt + pad_pt)
        if x1 <= x0 or y1 <= y0:
            return 0.0

        c0 = max(0, min(self.ink_cols - 1, int((x0 / self.width_pt) * self.ink_cols)))
        c1 = max(0, min(self.ink_cols - 1, int((x1 / self.width_pt) * self.ink_cols)))
        # PDF Y=0 is bottom, image row 0 is top
        r0 = max(
            0,
            min(
                self.ink_rows - 1,
                int(((self.height_pt - y1) / self.height_pt) * self.ink_rows),
            ),
        )
        r1 = max(
            0,
            min(
                self.ink_rows - 1,
                int(((self.height_pt - y0) / self.height_pt) * self.ink_rows),
            ),
        )
        total = 0
        ink_cells = 0
        max_val = 0
        count = 0
        cols = self.ink_cols
        grid = self.ink_grid
        for r in range(r0, r1 + 1):
            row_off = r * cols
            for c in range(c0, c1 + 1):
                val = grid[row_off + c]
                total += val
                if val >= 12:
                    ink_cells += 1
                if val > max_val:
                    max_val = val
                count += 1
        if count <= 0 or max_val < 12:
            return 0.0
        return (ink_cells / count) + (total / (255.0 * count)) + (max_val / 255.0) * 0.35

    def find_clear_rect(
        self,
        x_pt: float,
        y_pt: float,
        w_pt: float,
        h_pt: float,
        x_min_pt: float,
        x_max_pt: float,
        y_min_pt: float,
        y_max_pt: float,
        placed_rects: list[tuple[float, float, float, float]] | None = None,
        pad_pt: float = 1.2,
    ) -> tuple[float, float]:
        """Find a position (x, y) near (x_pt, y_pt) within bounds that minimizes overlap with ink and placed rects."""
        placed = placed_rects or []
        eff_x_max = max(x_min_pt, x_max_pt - w_pt)
        eff_y_max = max(y_min_pt, y_max_pt - h_pt)
        base_x = max(x_min_pt, min(eff_x_max, x_pt))
        base_y = max(y_min_pt, min(eff_y_max, y_pt))

        def _overlaps_placed(cx: float, cy: float) -> bool:
            for px, py, pw, ph in placed:
                if (
                    cx < px + pw + 2.5
                    and cx + w_pt + 2.5 > px
                    and cy < py + ph + 1.5
                    and cy + h_pt + 1.5 > py
                ):
                    return True
            return False

        # Candidate offsets: explore vertical and horizontal nudges to dodge stems, beams, tuplets, and text
        dy_steps = [
            0.0,
            2.0,
            -2.0,
            4.0,
            -4.0,
            6.0,
            -6.0,
            8.0,
            -8.0,
            10.0,
            12.0,
            14.0,
            16.5,
            19.0,
        ]
        dx_steps = [
            0.0,
            4.0,
            -4.0,
            8.0,
            -8.0,
            13.0,
            -12.0,
            18.0,
            -17.0,
            24.0,
            -22.0,
            30.0,
            -28.0,
            38.0,
            -34.0,
        ]

        best_pos = (base_x, base_y)
        best_score = float("inf")

        for dy in dy_steps:
            cy = base_y + dy
            if cy < y_min_pt - 0.1 or cy > eff_y_max + 0.1:
                continue
            cy = max(y_min_pt, min(eff_y_max, cy))
            for dx in dx_steps:
                cx = base_x + dx
                if cx < x_min_pt - 0.1 or cx > eff_x_max + 0.1:
                    continue
                cx = max(x_min_pt, min(eff_x_max, cx))
                if _overlaps_placed(cx, cy):
                    continue
                ink = self.ink_density_in_rect(cx, cy, w_pt, h_pt, pad_pt=pad_pt)
                # Score combines ink density (heavily weighted) + small distance penalty from target
                dist_penalty = (abs(dx) * 0.0012) + (abs(dy) * 0.0018)
                score = ink + dist_penalty
                if score < best_score:
                    best_score = score
                    best_pos = (cx, cy)
                    if ink == 0.0 and dist_penalty <= 0.006:
                        return (cx, cy)

        return best_pos


def _build_ink_grid(
    gray_img: Image.Image, width_pt: float, height_pt: float
) -> tuple[bytes, int, int]:
    """Downsample the grayscale page image to ~2pt cells recording dark pixel density (0..255)."""
    cols = max(60, min(360, int(round(width_pt / 2.0))))
    rows = max(80, min(480, int(round(height_pt / 2.0))))
    # Use BOX resampling on inverted binary ink mask so even thin note stems / text strokes register
    inv = gray_img.point(lambda p: 255 if p < 212 else 0)
    small = inv.resize((cols, rows), resample=Image.Resampling.BOX)
    data = small.tobytes()
    small.close()
    inv.close()
    return data, cols, rows


def _clean_single_staff_cluster(cluster: list[float]) -> list[float]:
    """Remove non-staff outlier lines (e.g. volta brackets or text underlines) from a line cluster."""
    if len(cluster) < 4:
        return []
    lines = sorted(cluster, reverse=True)  # top to bottom in PDF points

    # Iteratively strip top or bottom outlier lines whose spacing to their neighbor
    # is much larger than the median spacing of the staff lines.
    while len(lines) > 5:
        diffs = [lines[j] - lines[j + 1] for j in range(len(lines) - 1)]
        sorted_diffs = sorted(diffs)
        med = sorted_diffs[len(sorted_diffs) // 2]
        if med <= 0:
            break
        # If top gap or bottom gap is > 1.45x median spacing, strip that outer line
        if diffs[0] > med * 1.45 and diffs[0] >= diffs[-1]:
            lines.pop(0)
        elif diffs[-1] > med * 1.45:
            lines.pop(-1)
        else:
            break

    if len(lines) < 4 or len(lines) > 6:
        return []

    diffs = [lines[j] - lines[j + 1] for j in range(len(lines) - 1)]
    sorted_diffs = sorted(diffs)
    med = sorted_diffs[len(sorted_diffs) // 2]
    if med < 2.2 or med > 13.0:
        return []
    # Verify internal uniformity: no internal gap should exceed 2.2x median step
    if max(diffs) > med * 2.25:
        return []

    return lines


def _extract_staff_line_clusters(
    gray_img: Image.Image, height_pt: float
) -> list[list[float]]:
    """Detect horizontal staff lines directly and group them into staves (5-line or 6-line).

    Checks both the main staff span (12%..88%) and the left segment (10%..42%) so half-width
    final systems (e.g. codas / endings) are also captured accurately.
    """
    img_w, img_h = gray_img.size
    px = gray_img.load()

    x_full_0, x_full_1 = int(img_w * 0.12), int(img_w * 0.88)
    span_full = max(1, (x_full_1 - x_full_0) // 2)

    x_mid_0, x_mid_1 = int(img_w * 0.22), int(img_w * 0.78)
    span_mid = max(1, (x_mid_1 - x_mid_0) // 2)

    x_left_0, x_left_1 = int(img_w * 0.10), int(img_w * 0.42)
    span_left = max(1, (x_left_1 - x_left_0) // 2)

    top_limit = int(img_h * 0.05)
    bot_limit = int(img_h * 0.96)

    def row_scores(y: int) -> tuple[float, float, float]:
        dark_full = sum(1 for x in range(x_full_0, x_full_1, 2) if px[x, y] < 205) / span_full
        dark_mid = sum(1 for x in range(x_mid_0, x_mid_1, 2) if px[x, y] < 205) / span_mid
        dark_left = sum(1 for x in range(x_left_0, x_left_1, 2) if px[x, y] < 205) / span_left
        return dark_full, dark_mid, dark_left

    def row_is_staff_line(y: int, threshold: float) -> bool:
        df, dm, dl = row_scores(y)
        return (
            df >= threshold
            or dm >= (threshold + 0.04)
            or dl >= (threshold + 0.08)
        )

    max_single_run = max(6, int(img_h * 0.004))
    line_ys_pt: list[float] = []
    y = top_limit
    while y < bot_limit:
        if row_is_staff_line(y, 0.51):
            y_start = y
            while y < bot_limit and row_is_staff_line(y, 0.42):
                y += 1
            run_len = y - y_start
            # Normal single staff line
            if run_len <= max_single_run:
                y_mid = (y_start + y - 1) / 2.0
                line_ys_pt.append(round(height_pt * (1.0 - y_mid / img_h), 1))
            elif run_len <= max_single_run * 3:
                # Check if two tilted/bridged staff lines merged into one run with an internal valley
                mid_vals = [row_scores(ry)[1] for ry in range(y_start, y)]
                if len(mid_vals) >= 5:
                    v_idx = min(
                        range(1, len(mid_vals) - 1),
                        key=lambda k: mid_vals[k],
                    )
                    max_top = max(mid_vals[:v_idx])
                    max_bot = max(mid_vals[v_idx + 1 :])
                    if (
                        max_top >= 0.48
                        and max_bot >= 0.48
                        and mid_vals[v_idx] < min(max_top, max_bot) * 0.78
                    ):
                        y_split = y_start + v_idx
                        if (y_split - y_start) <= max_single_run:
                            ym1 = (y_start + y_split - 1) / 2.0
                            line_ys_pt.append(round(height_pt * (1.0 - ym1 / img_h), 1))
                        if (y - (y_split + 1)) <= max_single_run and (y_split + 1) < y:
                            ym2 = (y_split + 1 + y - 1) / 2.0
                            line_ys_pt.append(round(height_pt * (1.0 - ym2 / img_h), 1))
        else:
            y += 1

    # Cluster horizontal lines that are within 13.5 pt of each other into individual staves
    raw_staves: list[list[float]] = []
    for ly in line_ys_pt:
        if not raw_staves or (raw_staves[-1][-1] - ly) > 13.5:
            raw_staves.append([ly])
        else:
            raw_staves[-1].append(ly)

    valid_staves: list[list[float]] = []
    for raw in raw_staves:
        cleaned = _clean_single_staff_cluster(raw)
        if cleaned and 10.0 <= (cleaned[0] - cleaned[-1]) <= 64.0:
            valid_staves.append(cleaned)
    return valid_staves


def _detect_staff_systems_from_image(
    gray_img: Image.Image, width_pt: float, height_pt: float
) -> tuple[list[StaffSystem], float]:
    """Locate musical staff systems (pairing Treble + TAB or Grand Staves) and bottom whitespace."""
    staves = _extract_staff_line_clusters(gray_img, height_pt)

    # Pre-check whether an even number of 5-line staves actually has alternating small/large gaps
    # (characteristic of a Piano Grand Staff) vs uniform gaps (characteristic of single-staff guitar/lead sheets).
    grand_staff_alternating = False
    if len(staves) >= 4 and len(staves) % 2 == 0 and all(len(s) in (4, 5) for s in staves):
        intra_gaps = [staves[k][-1] - staves[k + 1][0] for k in range(0, len(staves), 2)]
        inter_gaps = [staves[k][-1] - staves[k + 1][0] for k in range(1, len(staves) - 1, 2)]
        if intra_gaps and inter_gaps:
            avg_intra = sum(intra_gaps) / len(intra_gaps)
            avg_inter = sum(inter_gaps) / len(inter_gaps)
            if avg_intra <= 52.0 and avg_intra < avg_inter * 0.72:
                grand_staff_alternating = True

    systems_bounds_pt: list[tuple[float, float, float]] = []
    if staves:
        i = 0
        while i < len(staves):
            curr = staves[i]
            curr_top, curr_bot = curr[0], curr[-1]
            curr_step = (curr_top - curr_bot) / max(1, len(curr) - 1)
            curr_treble_h = curr_step * 4.0

            if i + 1 < len(staves):
                nxt = staves[i + 1]
                nxt_top, nxt_bot = nxt[0], nxt[-1]
                nxt_step = (nxt_top - nxt_bot) / max(1, len(nxt) - 1)
                gap = curr_bot - nxt_top

                # Case 1: 5-line Treble staff followed by wider 6-line TAB staff.
                # Require nxt to be a 6-line staff whose line spacing is wider than the treble staff.
                is_treble_tab = (
                    len(curr) in (4, 5, 6)
                    and len(nxt) == 6
                    and nxt_step > curr_step * 1.08
                    and gap <= 155.0
                )

                # Case 2: Piano Grand Staff (two 5-line staves with alternating intra < inter gaps)
                is_grand_staff = (
                    grand_staff_alternating
                    and i % 2 == 0
                    and len(curr) in (4, 5)
                    and len(nxt) in (4, 5)
                    and gap <= 52.0
                )

                if is_treble_tab or is_grand_staff:
                    systems_bounds_pt.append((curr_top, nxt_bot, curr_treble_h))
                    i += 2
                    continue

            systems_bounds_pt.append((curr_top, curr_bot, curr_treble_h))
            i += 1

    # Fallback if no crisp staff line clusters were found
    if not systems_bounds_pt:
        for idx in range(4):
            y_top_pt = height_pt * (0.85 - idx * 0.18)
            y_bot_pt = y_top_pt - height_pt * 0.08
            systems_bounds_pt.append((y_top_pt, y_bot_pt, 20.0))

    systems: list[StaffSystem] = []
    for idx, (y_top_pt, y_bottom_pt, treble_h_pt) in enumerate(systems_bounds_pt, start=1):
        # Scale default chord_y offset with staff height and available gap above
        if idx > 1:
            prev_bot = systems_bounds_pt[idx - 2][1]
            avail_above = max(8.0, prev_bot - y_top_pt)
            offset = min(18.5, max(9.5, min(treble_h_pt * 0.85, avail_above * 0.48)))
        else:
            offset = min(18.5, max(10.5, treble_h_pt * 0.85))
        chord_y_pt = min(height_pt - 30.0, y_top_pt + offset)
        systems.append(
            StaffSystem(
                index=idx,
                y_top_pt=round(y_top_pt, 1),
                y_bottom_pt=round(y_bottom_pt, 1),
                chord_y_pt=round(chord_y_pt, 1),
                treble_height_pt=round(treble_h_pt, 1),
            )
        )

    lowest_system_bot_pt = min(b for _, b, _ in systems_bounds_pt)
    # Leave ~25pt below the lowest staff line for low TAB numbers / pedal markings
    bottom_free_pt = max(0.0, lowest_system_bot_pt - 25.0)
    return systems, round(bottom_free_pt, 1)


def _create_guide_image(
    base_img: Image.Image,
    systems: list[StaffSystem],
    width_pt: float,
    height_pt: float,
) -> bytes:
    """Create an annotated copy of the page with system labels (S1, S2...) and an X-coordinate ruler."""
    annotated = base_img.convert("RGB")
    draw = ImageDraw.Draw(annotated)
    img_w, img_h = annotated.size
    font = ImageFont.load_default()

    # Draw horizontal X-coordinate ruler in PDF points at the top and bottom
    for x_pt in range(50, int(width_pt), 50):
        px = int((x_pt / width_pt) * img_w)
        draw.line([(px, 0), (px, img_h)], fill=(220, 230, 242), width=1)
        draw.text((px + 2, 6), f"x={x_pt}", fill=(41, 128, 185), font=font)

    # Draw detected system markers (S1, S2...) at their chord_y_pt height
    for sys in systems:
        py = int((1.0 - (sys.chord_y_pt / height_pt)) * img_h)
        draw.line([(0, py), (img_w, py)], fill=(41, 128, 185), width=2)
        badge_box = [4, max(0, py - 14), 78, py + 4]
        draw.rectangle(badge_box, fill=(26, 82, 118))
        draw.text(
            (8, max(0, py - 12)),
            f"S{sys.index} y={int(sys.chord_y_pt)}",
            fill=(255, 255, 255),
            font=font,
        )

    buf = io.BytesIO()
    try:
        annotated.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    finally:
        buf.close()
        annotated.close()


def analyze_pdf_layout(pdf_path: Path, scale: float = 1.45) -> list[PageLayout]:
    """Render each page of a PDF and extract staff system coordinates and guide images."""
    reader = pypdf.PdfReader(str(pdf_path))
    pdf_doc = pdfium.PdfDocument(str(pdf_path))
    layouts: list[PageLayout] = []

    try:
        for idx, page in enumerate(reader.pages):
            box = page.mediabox
            width_pt = float(box.width)
            height_pt = float(box.height)

            effective_scale = min(scale, 1400.0 / max(1.0, max(width_pt, height_pt)))
            pdfium_page = pdf_doc[idx]
            bitmap = pdfium_page.render(scale=effective_scale)
            pil_img = bitmap.to_pil()
            bitmap.close()
            pdfium_page.close()

            gray = pil_img.convert("L")
            systems, bottom_free_pt = _detect_staff_systems_from_image(
                gray, width_pt, height_pt
            )
            ink_grid, ink_cols, ink_rows = _build_ink_grid(gray, width_pt, height_pt)
            gray.close()

            if idx < 6:
                clean_buf = io.BytesIO()
                try:
                    pil_img.save(clean_buf, format="PNG", optimize=True)
                    clean_bytes = clean_buf.getvalue()
                finally:
                    clean_buf.close()
                guide_bytes = _create_guide_image(pil_img, systems, width_pt, height_pt)
            else:
                clean_bytes = b""
                guide_bytes = b""

            pil_img.close()

            layouts.append(
                PageLayout(
                    page_num=idx + 1,
                    width_pt=width_pt,
                    height_pt=height_pt,
                    systems=systems,
                    bottom_free_pt=bottom_free_pt,
                    clean_png_bytes=clean_bytes,
                    guide_png_bytes=guide_bytes,
                    ink_grid=ink_grid,
                    ink_cols=ink_cols,
                    ink_rows=ink_rows,
                )
            )
    finally:
        pdf_doc.close()

    return layouts
