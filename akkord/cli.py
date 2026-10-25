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
"""Command-line interface for Akkord."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from akkord.config import (
    DEFAULT_API_KEY,
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    SUPPORTED_LANGUAGES,
    AkkordConfig,
)
from akkord.pipeline import AkkordPipeline
from akkord.sample_sheets import generate_demo_folder


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="akkord",
        description=(
            "Scan a Google Drive folder (or local directory / PDF) for music sheet PDFs, "
            "analyze existing chords or add missing chords using Gemini, and output annotated PDFs."
        ),
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default=None,
        help="Google Drive folder URL / ID, or local folder / PDF path.",
    )
    parser.add_argument(
        "--folder",
        dest="folder_flag",
        default=None,
        help="Google Drive folder URL / ID, or local folder / PDF path.",
    )
    parser.add_argument(
        "--lang",
        "-l",
        choices=SUPPORTED_LANGUAGES,
        default=DEFAULT_LANGUAGE,
        help=f"Output language for the annotated PDF ({', '.join(SUPPORTED_LANGUAGES)}). Default: {DEFAULT_LANGUAGE}.",
    )
    parser.add_argument(
        "--model",
        "-m",
        default=DEFAULT_MODEL,
        help=f"Gemini model to use for harmony and chord analysis. Default: {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--api-key",
        "-k",
        default=DEFAULT_API_KEY,
        help="Gemini API key (defaults to configured Akkord key or GEMINI_API_KEY).",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default="outputs",
        help="Local directory where annotated PDFs will be saved. Default: ./outputs.",
    )
    parser.add_argument(
        "--upload-to-drive",
        action="store_true",
        help="Upload annotated PDFs back to the source Google Drive folder (requires Drive credentials).",
    )
    parser.add_argument(
        "--credentials",
        default=None,
        help="Optional path to Google Drive OAuth credentials.json / service_account.json.",
    )
    parser.add_argument(
        "--generate-samples",
        metavar="DIR",
        default=None,
        help="Generate sample music sheet PDFs (one with chords, one without chords) in DIR and exit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON processing reports to stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.generate_samples:
        sample_dir = generate_demo_folder(Path(args.generate_samples))
        print(f"Generated sample music sheets in: {sample_dir}")
        return 0

    target_folder = args.folder_flag or args.folder
    if not target_folder:
        parser.error(
            "Please provide a Google Drive folder URL/ID or local folder path (or use --generate-samples)."
        )

    config = AkkordConfig(
        model=args.model,
        api_key=args.api_key,
        language=args.lang,
        output_dir=Path(args.output_dir),
        upload_to_drive=bool(args.upload_to_drive),
        google_credentials_path=args.credentials,
    )

    pipeline = AkkordPipeline(config)
    sheets = pipeline.scan_folder(target_folder)
    if not sheets:
        print(f"No music sheet PDFs found in: {target_folder}", file=sys.stderr)
        return 1

    print(
        f"Found {len(sheets)} PDF file(s) | Model: {config.model} | Language: {config.language.upper()}"
    )
    reports = []
    for idx, sheet in enumerate(sheets, start=1):
        print(f"[{idx}/{len(sheets)}] Processing '{sheet.name}'...")
        report = pipeline.process_single_pdf(sheet)
        reports.append(pipeline.report_to_dict(report))
        if report.mode == "skipped":
            print(f"   -> Skipped (not a music sheet): {report.overall_summary}")
        else:
            mode_label = (
                "Analyzed existing chords"
                if report.has_existing_chords
                else "Added missing chords"
            )
            print(
                f"   -> {mode_label} | Key: {report.detected_key} | "
                f"Annotations: {report.annotations_count} | Saved: {report.output_pdf_path}"
            )
            if report.uploaded_drive_file:
                print(
                    f"   -> Uploaded to Google Drive: {report.uploaded_drive_file.get('name')}"
                )

    if args.json:
        print(json.dumps(reports, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
