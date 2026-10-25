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
"""End-to-end orchestration pipeline for scanning folders and annotating music sheet PDFs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
import gc
from pathlib import Path
from typing import Any

from akkord.config import AkkordConfig
from akkord.drive import DriveConnector, SheetFile
from akkord.harmony import HarmonyAnalysisResult, HarmonyEngine
from akkord.i18n import t
from akkord.pdf_annotator import annotate_music_sheet_pdf
from akkord.pdf_layout import analyze_pdf_layout


@dataclass
class ProcessedSheetReport:
    """Result report for a single processed PDF file."""

    source_name: str
    source_id: str
    is_music_sheet: bool
    has_existing_chords: bool
    mode: str  # "analyze" | "add_chords" | "skipped"
    language: str
    model: str
    title: str
    detected_key: str
    overall_summary: str
    accuracy_score: int
    annotations_count: int
    output_filename: str | None = None
    output_pdf_path: str | None = None
    uploaded_drive_file: dict[str, str] | None = None
    analysis_detail: dict[str, Any] | None = None
    token_usage: dict[str, Any] | None = None


class AkkordPipeline:
    """Orchestrates Google Drive / local PDF discovery, Gemini analysis, and PDF annotation."""

    def __init__(
        self,
        config: AkkordConfig,
        drive_connector: DriveConnector | None = None,
        harmony_engine: HarmonyEngine | None = None,
        oauth_credentials: Any = None,
    ) -> None:
        self.config = config
        self.drive = drive_connector or DriveConnector(
            credentials_path=config.google_credentials_path,
            oauth_credentials=oauth_credentials,
        )
        self.engine = harmony_engine or HarmonyEngine(config)

    def scan_folder(self, folder_or_path: str) -> list[SheetFile]:
        """Return all candidate PDF files in a Google Drive folder or local path."""
        return self.drive.list_pdfs(folder_or_path)

    def process_single_pdf(
        self,
        sheet: SheetFile,
        work_dir: Path | None = None,
        progress_callback: Callable[[str, str], None] | None = None,
    ) -> ProcessedSheetReport:
        """Download (if remote), analyze with Gemini, annotate PDF, and optionally upload back."""
        def _notify(stage: str, message: str) -> None:
            if progress_callback is not None:
                progress_callback(stage, message)

        _notify("download", f"Lecture / téléchargement de {sheet.name}…")
        download_dir = work_dir or (self.config.output_dir / "_downloads")
        local_pdf = self.drive.download_pdf(sheet, download_dir)

        _notify("layout", f"Détection des portées et systèmes ({sheet.name})…")
        layouts = analyze_pdf_layout(local_pdf)

        _notify("harmony", f"Analyse harmonique & lignes de basse ({sheet.name})…")
        try:
            try:
                result: HarmonyAnalysisResult = self.engine.analyze_sheet(
                    layouts, pdf_path=local_pdf
                )
            except TypeError:
                result = self.engine.analyze_sheet(layouts)
        finally:
            # Immediately release multi-MB PNG buffers right after Gemini analysis
            for lay in layouts:
                lay.clear_image_buffers()

        if not result.is_music_sheet:
            gc.collect()
            _notify("done", f"{sheet.name} ignoré (non détecté comme partition).")
            return ProcessedSheetReport(
                source_name=sheet.name,
                source_id=sheet.id,
                is_music_sheet=False,
                has_existing_chords=False,
                mode="skipped",
                language=self.config.language,
                model=self.config.model,
                title=result.title or sheet.name,
                detected_key="",
                overall_summary=result.overall_summary
                or "Not detected as a music sheet.",
                accuracy_score=0,
                annotations_count=0,
                analysis_detail=result.model_dump(),
                token_usage=result.token_usage.model_dump() if result.token_usage else None,
            )

        stem = Path(sheet.name).stem
        suffix = (
            t(self.config.language, "file_suffix_analyzed")
            if result.has_existing_chords
            else t(self.config.language, "file_suffix_added")
        )
        output_filename = f"{stem}{suffix}"
        output_pdf_path = self.config.output_dir / output_filename

        _notify("annotate", f"Génération du PDF annoté ({output_filename})…")
        annotate_music_sheet_pdf(
            input_pdf_path=local_pdf,
            output_pdf_path=output_pdf_path,
            layouts=layouts,
            result=result,
            language=self.config.language,
        )

        uploaded_info: dict[str, str] | None = None
        if self.config.upload_to_drive and sheet.drive_folder_id:
            _notify("upload", f"Envoi de {output_filename} vers Google Drive…")
            uploaded_info = self.drive.upload_pdf(
                local_pdf_path=output_pdf_path,
                folder_id=sheet.drive_folder_id,
                remote_name=output_filename,
            )

        gc.collect()
        _notify("done", f"Terminé : {output_filename}")
        return ProcessedSheetReport(
            source_name=sheet.name,
            source_id=sheet.id,
            is_music_sheet=True,
            has_existing_chords=result.has_existing_chords,
            mode="analyze" if result.has_existing_chords else "add_chords",
            language=self.config.language,
            model=self.config.model,
            title=result.title or stem,
            detected_key=result.detected_key,
            overall_summary=result.overall_summary,
            accuracy_score=result.accuracy_score,
            annotations_count=len(result.annotations),
            output_filename=output_filename,
            output_pdf_path=str(output_pdf_path.resolve()),
            uploaded_drive_file=uploaded_info,
            analysis_detail=result.model_dump(),
            token_usage=result.token_usage.model_dump() if result.token_usage else None,
        )

    def process_folder(self, folder_or_path: str) -> list[ProcessedSheetReport]:
        """Scan a Google Drive folder (or local path) and process all discovered PDFs."""
        sheets = self.scan_folder(folder_or_path)
        reports: list[ProcessedSheetReport] = []
        for sheet in sheets:
            report = self.process_single_pdf(sheet)
            reports.append(report)
        return reports

    @staticmethod
    def report_to_dict(report: ProcessedSheetReport) -> dict[str, Any]:
        return asdict(report)
