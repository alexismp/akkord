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
"""Synthetic music sheet PDF generator for local demos and automated testing."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas


def _draw_staff_system(
    c: canvas.Canvas,
    x_left: float,
    x_right: float,
    treble_top_y: float,
    tab_top_y: float | None = None,
    measures: int = 4,
) -> list[float]:
    """Draw a 5-line treble staff (and optional 6-line TAB staff) with barlines and notes.

    Returns the X coordinates of the measure starts.
    """
    c.setStrokeColor(HexColor("#111111"))
    c.setLineWidth(0.8)

    line_spacing = 6.5
    # 5-line treble staff
    for i in range(5):
        y = treble_top_y - i * line_spacing
        c.line(x_left, y, x_right, y)

    treble_bot_y = treble_top_y - 4 * line_spacing

    # Optional 6-line TAB staff
    tab_bot_y = treble_bot_y
    if tab_top_y is not None:
        tab_spacing = 7.5
        for i in range(6):
            y = tab_top_y - i * tab_spacing
            c.line(x_left, y, x_right, y)
        tab_bot_y = tab_top_y - 5 * tab_spacing

    # Measure barlines and simple noteheads so Gemini/human sees clear musical notation
    measure_width = (x_right - x_left) / measures
    measure_xs: list[float] = []
    pitch_offsets = [3, 2, 1, 2.5, 1.5, 3.5, 2, 0.5]

    for m in range(measures + 1):
        bx = x_left + m * measure_width
        c.line(bx, treble_top_y, bx, treble_bot_y)
        if tab_top_y is not None:
            c.line(bx, tab_top_y, bx, tab_bot_y)
        if m < measures:
            measure_xs.append(bx + 18.0)
            # Draw 4 quarter notes in each measure
            for beat in range(4):
                nx = bx + 24.0 + beat * ((measure_width - 36.0) / 4.0)
                ny = (
                    treble_top_y
                    - pitch_offsets[(m + beat) % len(pitch_offsets)] * line_spacing
                )
                c.setFillColor(HexColor("#111111"))
                c.circle(nx, ny, 3.2, fill=1, stroke=0)
                # Note stem
                c.setLineWidth(0.9)
                c.line(nx + 3.0, ny, nx + 3.0, ny + 18.0)

    return measure_xs


def create_sample_sheet_without_chords(dest_path: Path) -> Path:
    """Create a 2-page music sheet PDF WITHOUT chords (modeled on koh.pdf layout)."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(dest_path), pagesize=(827, 1169))

    # Page 1: Title + 4 Systems (Treble + TAB)
    c.setFont("Helvetica-Bold", 18)
    c.setFillColor(HexColor("#111111"))
    c.drawCentredString(413.5, 1110, "Конь (Kon') — Romance Traditionnelle")
    c.setFont("Helvetica", 10)
    c.drawString(75, 1042, "Moderate = 70")

    p1_systems = [
        (1020.5, 926.8),
        (832.0, 756.5),
        (661.8, 575.3),
        (480.6, 395.9),
    ]
    for treble_y, tab_y in p1_systems:
        _draw_staff_system(c, 70, 760, treble_y, tab_y, measures=4)

    c.showPage()

    # Page 2: 2 Systems at top, leaving bottom half (y < 600) completely blank for chord diagrams
    p2_systems = [
        (1067.7, 910.6),
        (815.9, 729.4),
    ]
    for treble_y, tab_y in p2_systems:
        _draw_staff_system(c, 70, 760, treble_y, tab_y, measures=4)

    c.save()
    return dest_path


def create_sample_sheet_with_chords(dest_path: Path) -> Path:
    """Create a 1-page music sheet PDF WITH existing chords (some accurate, some improvable, some missing)."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(dest_path), pagesize=(827, 1169))

    c.setFont("Helvetica-Bold", 18)
    c.setFillColor(HexColor("#111111"))
    c.drawCentredString(413.5, 1110, "Autumn Leaves Study (Étude en La mineur)")

    systems_y = [1000.0, 820.0, 640.0]
    existing_chords = [
        # System 1: m.1 Am, m.2 Dm, m.3 G (could be G7), m.4 Cmaj7
        [(90, "Am"), (260, "Dm"), (435, "G"), (610, "Cmaj7")],
        # System 2: m.5 F, m.6 Dm (could be Bm7b5), m.7 E (could be E7), m.8 [missing Am!]
        [(90, "F"), (260, "Dm"), (435, "E")],
        # System 3: m.9 Am, m.10 [missing Dm7], m.11 E7, m.12 Am
        [(90, "Am"), (435, "E7"), (610, "Am")],
    ]

    for sys_idx, treble_y in enumerate(systems_y):
        _draw_staff_system(c, 70, 760, treble_y, None, measures=4)
        c.setFont("Helvetica-Bold", 12)
        c.setFillColor(HexColor("#000000"))
        for cx, cname in existing_chords[sys_idx]:
            c.drawString(cx, treble_y + 12.0, cname)

    c.save()
    return dest_path


def generate_demo_folder(folder_path: Path) -> Path:
    """Populate folder_path with two sample music sheet PDFs (one without chords, one with chords)."""
    folder_path.mkdir(parents=True, exist_ok=True)
    create_sample_sheet_without_chords(folder_path / "kon-no-chords.pdf")
    create_sample_sheet_with_chords(folder_path / "autumn-study-with-chords.pdf")
    return folder_path
