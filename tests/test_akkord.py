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
"""Unit and integration tests for the Akkord system."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pypdf
import pytest

from akkord.config import DEFAULT_API_KEY, DEFAULT_MODEL, AkkordConfig
from akkord.drive import extract_folder_id, is_generated_output
from akkord.harmony import (
    ChordAnnotation,
    GuitarDiagram,
    HarmonyAnalysisResult,
    HarmonyEngine,
    _postprocess_harmony_result,
    extract_compact_chord_symbol,
)
from akkord.pdf_annotator import _format_pill_text, annotate_music_sheet_pdf
from akkord.pdf_layout import analyze_pdf_layout
from akkord.pipeline import AkkordPipeline
from akkord.sample_sheets import (
    create_sample_sheet_with_chords,
    create_sample_sheet_without_chords,
)
from akkord.server import app


def test_default_config_values(tmp_path: Path) -> None:
    cfg = AkkordConfig(output_dir=tmp_path)
    assert cfg.model == "gemini-4-argon"
    assert cfg.model == DEFAULT_MODEL
    assert cfg.vertexai is True
    assert cfg.project == "alexismp-runner"
    assert cfg.api_key == DEFAULT_API_KEY
    assert cfg.language == "fr"

    with pytest.raises(ValueError, match="Unsupported language"):
        AkkordConfig(language="de", output_dir=tmp_path)


def test_logo_declination_sizes_exist() -> None:
    icons_dir = Path("akkord/static/icons")
    for fname in [
        "logo-master-1024.png",
        "logo-512.png",
        "logo-256.png",
        "logo-192.png",
        "apple-touch-icon-180.png",
        "logo-128.png",
        "logo-64.png",
        "logo-48.png",
        "logo-32.png",
        "favicon-16.png",
        "favicon.ico",
    ]:
        assert (icons_dir / fname).is_file(), f"Missing logo size {fname}"


def test_drive_folder_id_extraction(tmp_path: Path) -> None:
    url1 = "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz123456?usp=sharing"
    url2 = "https://drive.google.com/drive/u/0/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz123456"
    raw_id = "1AbCdEfGhIjKlMnOpQrStUvWxYz123456"

    assert extract_folder_id(url1) == raw_id
    assert extract_folder_id(url2) == raw_id
    assert extract_folder_id(raw_id) == raw_id
    assert extract_folder_id(str(tmp_path)) is None

    assert is_generated_output("koh-avec-accords.pdf") is True
    assert is_generated_output("song-chord-analysis.pdf") is True
    assert is_generated_output("koh.pdf") is False


def test_real_samples_layout_detection() -> None:
    samples_dir = Path("samples")
    expected_p1_systems = {
        "koh.pdf": 4,
        "lesou.pdf": 4,
        "vetcher.pdf": 5,
        "Carcassi-Op60-No7.pdf": 9,
        "Carcassi-Op60-No3.pdf": 8,
    }
    for fname, expected_sys_count in expected_p1_systems.items():
        fpath = samples_dir / fname
        if fpath.is_file():
            layouts = analyze_pdf_layout(fpath)
            assert len(layouts) >= 1
            assert len(layouts[0].systems) == expected_sys_count, (
                f"{fname} P1 expected {expected_sys_count} systems, got {len(layouts[0].systems)}"
            )


def test_pdf_layout_detection_and_add_chords_annotation_fr_and_en(tmp_path: Path) -> None:
    sheet_pdf = create_sample_sheet_without_chords(tmp_path / "koh.pdf")
    layouts = analyze_pdf_layout(sheet_pdf)

    assert len(layouts) == 2
    assert len(layouts[0].systems) == 4
    assert len(layouts[1].systems) == 2
    assert layouts[1].bottom_free_pt >= 250.0

    sample_result = HarmonyAnalysisResult(
        is_music_sheet=True,
        has_existing_chords=False,
        title="Конь - Kon'",
        detected_key="La mineur / Am",
        overall_summary="Arrangement en La mineur avec descente chromatique de basse.",
        accuracy_score=100,
        annotations=[
            ChordAnnotation(
                page_num=1, system_index=1, x_pt=96, chord="Am", status="added"
            ),
            ChordAnnotation(
                page_num=1, system_index=1, x_pt=186, chord="Am/D", status="added"
            ),
            ChordAnnotation(
                page_num=1, system_index=2, x_pt=98, chord="C", status="added"
            ),
            ChordAnnotation(
                page_num=2, system_index=1, x_pt=79, chord="F", status="added"
            ),
            ChordAnnotation(
                page_num=2, system_index=2, x_pt=231, chord="Am", status="added"
            ),
        ],
        chord_diagrams=[
            GuitarDiagram(name="Am (La m)", frets=["x", "0", "2", "2", "1", "0"]),
            GuitarDiagram(name="Dm (Ré m)", frets=["x", "x", "0", "2", "3", "1"]),
            GuitarDiagram(name="E (Mi)", frets=["0", "2", "2", "1", "0", "0"]),
            GuitarDiagram(name="C (Do)", frets=["x", "3", "2", "0", "1", "0"]),
        ],
        slash_chord_notes=[
            "Am/D : Am avec Ré à la basse (5e corde, case 5)",
            "G/B : Sol avec Si à la basse (5e corde, case 2)",
        ],
    )

    out_fr = annotate_music_sheet_pdf(
        sheet_pdf, tmp_path / "koh-avec-accords.pdf", layouts, sample_result, language="fr"
    )
    assert out_fr.is_file()
    reader_fr = pypdf.PdfReader(str(out_fr))
    assert len(reader_fr.pages) == 2
    p1_text_fr = reader_fr.pages[0].extract_text()
    p2_text_fr = reader_fr.pages[1].extract_text()
    assert "Grille d'accords & lignes de basse" in p1_text_fr
    assert "Am/D" in p1_text_fr
    assert "Diagrammes des accords principaux" in p2_text_fr

    sample_result.detected_key = "A minor (Am)"
    out_en = annotate_music_sheet_pdf(
        sheet_pdf, tmp_path / "koh-with-chords.pdf", layouts, sample_result, language="en"
    )
    assert out_en.is_file()
    reader_en = pypdf.PdfReader(str(out_en))
    p1_text_en = reader_en.pages[0].extract_text()
    p2_text_en = reader_en.pages[1].extract_text()
    assert "Guitar Chord Chart & Bass Counterpoint (Key: A minor (Am))" in p1_text_en
    assert "Main Guitar Chord Diagrams" in p2_text_en


def test_analyze_existing_chords_annotation_fr_and_en(tmp_path: Path) -> None:
    chorded_pdf = create_sample_sheet_with_chords(tmp_path / "autumn.pdf")
    layouts = analyze_pdf_layout(chorded_pdf)
    assert len(layouts) == 1

    analysis_result = HarmonyAnalysisResult(
        is_music_sheet=True,
        has_existing_chords=True,
        title="Autumn Leaves Study",
        detected_key="La mineur (Am)",
        overall_summary="La grille existante est globalement bonne mais certains accords de septième et de résolution manquent.",
        accuracy_score=78,
        annotations=[
            ChordAnnotation(
                page_num=1,
                system_index=1,
                x_pt=90,
                chord="Am",
                status="correct",
                measure_number=1,
            ),
            ChordAnnotation(
                page_num=1,
                system_index=1,
                x_pt=435,
                chord="G",
                status="improve",
                suggested_chord="G7/B",
                measure_number=3,
                note="Ajouter la 7e de dominante et basse Si (contrepoint) vers Cmaj7",
            ),
            ChordAnnotation(
                page_num=1,
                system_index=2,
                x_pt=610,
                chord="Am",
                status="missing",
                suggested_chord="Am",
                measure_number=8,
                note="Résolution sur la tonique manquante à la mesure 8",
            ),
        ],
        review_improvements=[
            "Mesure 3 : Remplacer G par G7/B (contrepoint) pour renforcer la cadence vers Cmaj7.",
            "Mesure 6 : Remplacer Dm par Bm7b5 (accord demi-diminué).",
        ],
        review_missing=[
            "Mesure 8 : Accord de résolution Am manquant après E7.",
            "Mesure 10 : Accord Dm7 manquant sur le changement harmonique.",
        ],
        review_correct=[
            "Mesures 1, 2, 4, 5 : Am, Dm, Cmaj7 et F sont parfaitement alignés."
        ],
    )

    out_fr = annotate_music_sheet_pdf(
        chorded_pdf,
        tmp_path / "autumn-analyse-fr.pdf",
        layouts,
        analysis_result,
        language="fr",
    )
    reader_fr = pypdf.PdfReader(str(out_fr))
    full_text_fr = "\n".join(p.extract_text() for p in reader_fr.pages)
    assert "Analyse harmonique, contrepoint & revue des accords" in full_text_fr
    assert "78%" in full_text_fr
    assert "G7/B" in full_text_fr

    out_en = annotate_music_sheet_pdf(
        chorded_pdf,
        tmp_path / "autumn-analysis-en.pdf",
        layouts,
        analysis_result,
        language="en",
    )
    reader_en = pypdf.PdfReader(str(out_en))
    full_text_en = "\n".join(p.extract_text() for p in reader_en.pages)
    assert "Harmonic Analysis, Counterpoint & Chord Review" in full_text_en
    assert "Suggested Chord & Bass Improvements:" in full_text_en
    assert "Missing Chords Detected:" in full_text_en


def test_harmony_engine_uses_vertexai_and_interactions_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sheet_pdf = create_sample_sheet_without_chords(tmp_path / "test.pdf")
    layouts = analyze_pdf_layout(sheet_pdf)

    captured_kwargs: dict = {}
    captured_client_init: dict = {}

    class DummyInteractions:
        def create(self, **kwargs):
            captured_kwargs.update(kwargs)
            payload = {
                "is_music_sheet": True,
                "has_existing_chords": False,
                "title": "Test Piece",
                "detected_key": "Am",
                "overall_summary": "Simple A minor harmony with walking bass.",
                "accuracy_score": 100,
                "annotations": [
                    {
                        "page_num": 1,
                        "system_index": 1,
                        "x_pt": 100,
                        "chord": "Am/C",
                        "status": "added",
                    }
                ],
                "chord_diagrams": [{"name": "Am (La m)", "frets": ["x", "0", "2", "2", "1", "0"]}],
                "bass_line_proposals": [
                    {
                        "measure_number": 1,
                        "original_chord": "Am",
                        "proposed_slash_chord": "Am/C",
                        "melody_note": "A",
                        "technique": "counterpoint",
                        "explanation": "Avoid doubling A melody note in bass.",
                    }
                ],
                "slash_chord_notes": [],
                "review_improvements": [],
                "review_missing": [],
                "review_correct": [],
            }
            return SimpleNamespace(output_text=json.dumps(payload), steps=[])

    class DummyClient:
        def __init__(self, **kwargs):
            captured_client_init.update(kwargs)
            self.interactions = DummyInteractions()

    monkeypatch.setattr("akkord.harmony.genai.Client", DummyClient)

    cfg = AkkordConfig(output_dir=tmp_path)
    engine = HarmonyEngine(cfg)
    res = engine.analyze_sheet(layouts[:1])

    assert captured_client_init == {"vertexai": True, "project": "alexismp-runner"}
    assert res.is_music_sheet is True
    assert res.title == "Test Piece"
    assert len(res.bass_line_proposals) == 1
    assert res.bass_line_proposals[0].proposed_slash_chord == "Am/C"
    assert captured_kwargs["model"] == "gemini-4-argon"
    assert captured_kwargs["response_format"]["type"] == "text"
    assert captured_kwargs["response_format"]["mime_type"] == "application/json"


def test_pipeline_and_fastapi_upload_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf1 = create_sample_sheet_without_chords(tmp_path / "sheet1.pdf")
    create_sample_sheet_with_chords(tmp_path / "sheet2.pdf")

    mock_engine = MagicMock()
    mock_engine.analyze_sheet.side_effect = [
        HarmonyAnalysisResult(
            is_music_sheet=True,
            has_existing_chords=False,
            title="Sheet 1",
            detected_key="Am",
            overall_summary="Added chords to Sheet 1.",
            accuracy_score=100,
            annotations=[
                ChordAnnotation(
                    page_num=1, system_index=1, x_pt=100, chord="Am", status="added"
                )
            ],
            chord_diagrams=[
                GuitarDiagram(name="Am (La m)", frets=["x", "0", "2", "2", "1", "0"])
            ],
        ),
        HarmonyAnalysisResult(
            is_music_sheet=True,
            has_existing_chords=True,
            title="Sheet 2",
            detected_key="Am",
            overall_summary="Reviewed existing chords on Sheet 2.",
            accuracy_score=85,
            annotations=[
                ChordAnnotation(
                    page_num=1,
                    system_index=1,
                    x_pt=100,
                    chord="Am",
                    status="correct",
                ),
                ChordAnnotation(
                    page_num=1,
                    system_index=1,
                    x_pt=260,
                    chord="G",
                    status="improve",
                    suggested_chord="G7",
                ),
            ],
            review_improvements=["m.2: G -> G7"],
        ),
    ]

    cfg = AkkordConfig(output_dir=tmp_path / "out", language="fr")
    pipeline = AkkordPipeline(cfg, harmony_engine=mock_engine)
    reports = pipeline.process_folder(str(tmp_path))

    assert len(reports) == 2
    assert reports[0].mode == "add_chords"
    assert reports[0].output_filename == "sheet1-avec-accords.pdf"
    assert reports[1].mode == "analyze"
    assert reports[1].output_filename == "sheet2-analyse-accords.pdf"

    # Isolate server's activity_manager to tmp_path so local outputs/_daily_activity.json never causes 429
    from akkord.activity import ActivityManager
    from akkord.firestore_store import FirestoreBackend

    test_store = tmp_path / "server_store"
    monkeypatch.setattr(
        "akkord.server.activity_manager",
        ActivityManager(test_store, firestore_backend=FirestoreBackend(test_store)),
    )

    client = TestClient(app)
    r_index = client.get("/")
    assert r_index.status_code == 200
    html_text = r_index.text
    assert "Vertex" not in html_text
    assert "alexismp-runner" not in html_text
    assert "samples/" not in html_text
    assert "logo-sizes-grid" not in html_text
    assert 'id="admin-advanced-menu"' in html_text
    assert 'id="upload-drive" name="upload_to_drive" checked' in html_text
    assert "Replier / Déplier" not in html_text

    r_cfg = client.get("/api/config")
    assert r_cfg.status_code == 200
    data_cfg = r_cfg.json()
    assert data_cfg["app_name"] == "akkord"
    assert data_cfg["default_model"] == "gemini-4-argon"
    assert "vertexai" not in data_cfg
    assert "project" not in data_cfg
    assert data_cfg["auth"]["is_admin"] is False

    # Verify samples/ is not publicly exposed via web API
    r_samples = client.get("/api/samples")
    assert r_samples.status_code == 404
    r_scan_samples = client.post("/api/scan-folder", json={"folder": "samples"})
    assert r_scan_samples.status_code == 403

    # Verify OAuth is permanently configured server-side and cannot be modified via web UI
    r_oauth_status = client.get("/api/auth/status")
    assert r_oauth_status.status_code == 200
    assert r_oauth_status.json()["oauth_configured"] is True

    r_oauth_cfg = client.post(
        "/api/auth/oauth-config",
        json={"client_id": "test", "client_secret": "test"},
    )
    assert r_oauth_cfg.status_code == 404

    # Test direct PDF file upload & streaming progress endpoints with mocked HarmonyEngine
    monkeypatch.setattr(
        "akkord.pipeline.HarmonyEngine.analyze_sheet",
        lambda self, layouts, pdf_path=None: HarmonyAnalysisResult(
            is_music_sheet=True,
            has_existing_chords=False,
            title="Uploaded Piece",
            detected_key="Am",
            overall_summary="Added chords to uploaded PDF.",
            accuracy_score=100,
            annotations=[
                ChordAnnotation(
                    page_num=1, system_index=1, x_pt=100, chord="Am", status="added"
                )
            ],
            chord_diagrams=[
                GuitarDiagram(name="Am (La m)", frets=["x", "0", "2", "2", "1", "0"])
            ],
        ),
    )
    with open(pdf1, "rb") as f:
        r_up = client.post(
            "/api/process-upload",
            files=[("files", ("uploaded-score.pdf", f, "application/pdf"))],
            data={"language": "en", "model": "gemini-4-argon"},
        )
    assert r_up.status_code == 200
    up_data = r_up.json()
    assert up_data["processed_count"] == 1
    assert up_data["reports"][0]["output_filename"] == "uploaded-score-with-chords.pdf"
    assert up_data["reports"][0]["download_url"] == "/api/outputs/uploaded-score-with-chords.pdf"

    with open(pdf1, "rb") as f:
        r_stream = client.post(
            "/api/process-upload-stream",
            files=[("files", ("uploaded-score.pdf", f, "application/pdf"))],
            data={"language": "fr", "model": "gemini-4-argon"},
        )
    assert r_stream.status_code == 200
    events = [json.loads(line) for line in r_stream.text.strip().splitlines() if line.strip()]
    event_types = [e["type"] for e in events]
    assert "file_start" in event_types
    assert "step" in event_types
    assert "file_done" in event_types
    assert "batch_done" in event_types


def test_long_suggested_chord_is_compacted_for_yellow_pills(tmp_path: Path) -> None:
    """Regression test for oblaka.pdf: verbose suggested_chord must never produce full-width yellow banners."""
    raw_verbose = (
        "Bm(maj7)/A♯ (Si m maj7/La♯) [x-1-4-4-3-2] (basse La♯ c.1 sur 5e corde) "
        "— mouvement chromatique descendant de la voix intermédiaire/basse"
    )
    sym, extra = extract_compact_chord_symbol(raw_verbose)
    assert sym == "Bm(maj7)/A#"
    assert "mouvement chromatique" in extra

    ann = ChordAnnotation(
        page_num=1,
        system_index=1,
        x_pt=590,
        chord="Bm7+",
        status="improve",
        suggested_chord=raw_verbose,
    )
    pill_label = _format_pill_text(ann, has_existing_chords=True)
    assert pill_label == "* Bm7+ -> Bm(maj7)/A#"
    assert len(pill_label) <= 24
    assert "♯" not in pill_label

    res = HarmonyAnalysisResult(
        is_music_sheet=True,
        has_existing_chords=True,
        title="Там, за облаками",
        detected_key="Bm (Si mineur)",
        overall_summary="Analyse en Si mineur.",
        accuracy_score=92,
        annotations=[ann],
    )
    cleaned = _postprocess_harmony_result(res, [], "fr")
    assert cleaned.annotations[0].suggested_chord == "Bm(maj7)/A#"
    assert "La#" in (cleaned.annotations[0].note or "")


def test_stateless_oauth_cookie_and_private_drive_listing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify HMAC-signed stateless OAuth session cookies and OAuth REST listing for private Drive folders."""
    from akkord.drive import DriveConnector
    from akkord.oauth import OAuthManager, UserSession

    mgr1 = OAuthManager(tmp_path / "inst1")
    sess = UserSession(
        session_id="init",
        email="alexis.mp@gmail.com",
        name="Alexis MP",
        picture="",
        access_token="ya29.test_access_token",
        refresh_token="1//test_refresh_token",
    )
    signed_cookie = mgr1.encode_session_cookie(sess)
    assert signed_cookie.startswith("v1.")

    # Simulate a second Cloud Run container instance decoding the cookie with empty local storage
    mgr2 = OAuthManager(tmp_path / "inst2")
    restored = mgr2.get_session(signed_cookie)
    assert restored is not None
    assert restored.email == "alexis.mp@gmail.com"
    assert restored.is_admin is True
    assert restored.access_token == "ya29.test_access_token"
    assert restored.refresh_token == "1//test_refresh_token"

    # Mock Drive API v3 REST response for private folder 11ToKjU3hrsrPbe8W9AncU9nHZzIzPwkR
    def fake_drive_api_get(self, url: str, params: dict | None = None):
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "files": [
                    {
                        "id": "pdf123",
                        "name": "oblaka.pdf",
                        "mimeType": "application/pdf",
                        "webViewLink": "https://drive.google.com/file/d/pdf123/view",
                    },
                    {
                        "id": "short456",
                        "name": "koh-shortcut.pdf",
                        "mimeType": "application/vnd.google-apps.shortcut",
                        "shortcutDetails": {
                            "targetId": "target789",
                            "targetMimeType": "application/pdf",
                        },
                    },
                ]
            },
        )

    monkeypatch.setattr(DriveConnector, "_drive_api_get", fake_drive_api_get)
    connector = DriveConnector(oauth_credentials=restored.to_google_credentials())
    sheets = connector.list_pdfs(
        "https://drive.google.com/drive/folders/11ToKjU3hrsrPbe8W9AncU9nHZzIzPwkR?usp=drive_link"
    )
    assert len(sheets) == 2
    assert sheets[0].id == "pdf123"
    assert sheets[0].name == "oblaka.pdf"
    assert sheets[1].id == "target789"
    assert sheets[1].name == "koh-shortcut.pdf"

    # Also test DriveConnector.browse_drive_folder for interactive folder browsing
    def fake_browse_api_get(self, url: str, params: dict | None = None):
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "files": [
                    {
                        "id": "folder_a",
                        "name": "Partitions Russes",
                        "mimeType": "application/vnd.google-apps.folder",
                    },
                    {
                        "id": "pdf123",
                        "name": "oblaka.pdf",
                        "mimeType": "application/pdf",
                    },
                ]
            },
        )

    monkeypatch.setattr(DriveConnector, "_drive_api_get", fake_browse_api_get)
    browsed = connector.browse_drive_folder(folder_id="root")
    assert browsed["current_folder"]["id"] == "root"
    assert len(browsed["folders"]) == 1
    assert browsed["folders"][0]["name"] == "Partitions Russes"
    assert browsed["pdf_count"] == 1
    assert browsed["pdfs"][0]["name"] == "oblaka.pdf"


def test_daily_quota_limit_cancellation_and_digest_email(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the 25 files/day limit, batch cancellation, and 18:00 daily summary email."""
    from akkord.activity import DAILY_FILE_LIMIT, ActivityManager

    mgr = ActivityManager(tmp_path / "activity_state")
    assert DAILY_FILE_LIMIT == 25
    assert mgr.can_process_more_today() is True
    assert mgr.get_quota_status()["remaining"] == 25

    # When 0 analyses have been run today, send_daily_digest skips sending
    empty_res = mgr.send_daily_digest(date_str="2026-10-25")
    assert empty_res["sent"] is False
    assert "Aucune analyse" in empty_res["reason"]

    # Record 25 analyses to hit the daily limit
    for idx in range(25):
        mgr.record_analysis(
            {
                "source_name": f"score-{idx + 1}.pdf",
                "output_filename": f"score-{idx + 1}-analyse-accords.pdf",
                "mode": "analyze",
                "title": f"Morceau #{idx + 1}",
                "detected_key": "Am",
                "accuracy_score": 88,
                "overall_summary": f"Synthèse harmonique du morceau #{idx + 1}.",
                "annotations_count": 6,
                "uploaded_drive_file": {
                    "id": f"drive_id_{idx + 1}",
                    "name": f"score-{idx + 1}-analyse-accords.pdf",
                    "webViewLink": f"https://drive.google.com/file/d/drive_id_{idx + 1}/view",
                },
                "analysis_detail": {"bass_line_proposals": [{"measure_number": 1}, {"measure_number": 2}]},
                "token_usage": {
                    "model": "gemini-4-argon",
                    "input_tokens": 1200,
                    "output_tokens": 800,
                    "thinking_tokens": 400,
                    "cached_tokens": 0,
                    "total_tokens": 2400,
                    "estimated_cost_usd": 0.0135,
                    "estimated_cost_eur": 0.01242,
                    "source": "gemini_api",
                },
            },
            user_email="alexis.mp@gmail.com",
            source="upload",
        )

    quota = mgr.get_quota_status()
    assert quota["used"] == 25
    assert quota["remaining"] == 0
    assert mgr.can_process_more_today() is False

    # Verify token & cost usage aggregation
    usage = mgr.get_usage_summary()
    assert usage["today"]["files_count"] == 25
    assert usage["today"]["input_tokens"] == 25 * 1200
    assert usage["today"]["output_tokens"] == 25 * 800
    assert usage["today"]["thinking_tokens"] == 25 * 400
    assert usage["today"]["total_tokens"] == 25 * 2400
    assert round(usage["today"]["estimated_cost_usd"], 4) == round(25 * 0.0135, 4)
    assert round(usage["today"]["estimated_cost_eur"], 4) == round(25 * 0.01242, 4)
    assert usage["cumulative"]["total_tokens"] == 60000

    # Build digest content and verify it includes detailed summaries + token/cost breakdowns
    today_str = quota["date"]
    subject, plain_text, html_body = mgr.build_daily_digest_content(today_str)
    assert "25 partition(s)" in subject
    assert "60,000 tokens" in subject
    assert "Morceau #1" in plain_text
    assert "Synthèse harmonique du morceau #1." in plain_text
    assert "https://drive.google.com/file/d/drive_id_1/view" in plain_text
    assert "60,000 tokens" in plain_text
    assert "Morceau #25" in html_body
    assert 'href="https://drive.google.com/file/d/drive_id_1/view"' in html_body
    assert "Tokens &amp; Coût" in html_body

    # Verify Gmail API sending via stored admin refresh token
    mgr.save_admin_oauth_tokens(
        email="alexis.mp@gmail.com",
        access_token="ya29.admin_access_token",
        refresh_token="1//admin_refresh_token",
    )

    class FakeGmailClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"access_token": "ya29.refreshed", "id": "msg123"},
                text="OK",
            )

    monkeypatch.setattr("akkord.activity.httpx.Client", FakeGmailClient)
    sent_res = mgr.send_daily_digest(date_str=today_str)
    assert sent_res["sent"] is True
    assert sent_res["method"] == "gmail_api"
    assert sent_res["entries_count"] == 25

    # Duplicate non-forced call on the same day is skipped
    dup_res = mgr.send_daily_digest(date_str=today_str, force=False)
    assert dup_res["sent"] is False
    assert "déjà envoyé" in dup_res["reason"]

    # Verify cancellation state and FastAPI endpoints
    mgr.reset_cancel()
    assert mgr.is_cancelled() is False
    mgr.request_cancel()
    assert mgr.is_cancelled() is True

    client = TestClient(app)
    r_cancel = client.post("/api/cancel")
    assert r_cancel.status_code == 200
    assert r_cancel.json()["cancelled"] is True

    # Non-admin preview is forbidden (403), admin preview succeeds (200)
    r_preview_anon = client.get("/api/daily-report/preview")
    assert r_preview_anon.status_code == 403
    r_usage_anon = client.get("/api/admin/usage")
    assert r_usage_anon.status_code == 403
    r_cfg_anon = client.get("/api/config")
    assert r_cfg_anon.json()["admin_usage"] is None

    from akkord.oauth import UserSession
    from akkord.server import oauth_manager

    admin_cookie = oauth_manager.encode_session_cookie(
        UserSession(
            session_id="adm",
            email="alexis.mp@gmail.com",
            name="Alexis MP",
            picture="",
            access_token="ya29.admin",
            refresh_token="1//admin",
        )
    )
    client.cookies.set("akkord_session", admin_cookie)
    r_preview = client.get("/api/daily-report/preview")
    assert r_preview.status_code == 200
    assert "subject" in r_preview.json()

    r_usage_admin = client.get("/api/admin/usage")
    assert r_usage_admin.status_code == 200
    assert "today" in r_usage_admin.json()
    assert "cumulative" in r_usage_admin.json()

    r_cfg_admin = client.get("/api/config")
    assert r_cfg_admin.json()["admin_usage"] is not None


def test_memory_cleanup_after_single_pdf(tmp_path: Path) -> None:
    """Verify PageLayout PNG buffers are immediately freed after Gemini analysis."""
    sheet_pdf = create_sample_sheet_without_chords(tmp_path / "mem.pdf")
    captured_layouts: list = []

    class CapturingEngine:
        def analyze_sheet(self, layouts, pdf_path=None):
            captured_layouts.extend(layouts)
            # Inside analyze_sheet, PNG buffers must be populated
            assert len(layouts[0].clean_png_bytes) > 0
            assert len(layouts[0].guide_png_bytes) > 0
            return HarmonyAnalysisResult(
                is_music_sheet=True,
                has_existing_chords=False,
                title="Mem Test",
                detected_key="Am",
                overall_summary="Memory test.",
                accuracy_score=100,
                annotations=[
                    ChordAnnotation(
                        page_num=1, system_index=1, x_pt=100, chord="Am", status="added"
                    )
                ],
                chord_diagrams=[
                    GuitarDiagram(name="Am (La m)", frets=["x", "0", "2", "2", "1", "0"])
                ],
            )

    cfg = AkkordConfig(output_dir=tmp_path / "out", language="fr")
    pipeline = AkkordPipeline(cfg, harmony_engine=CapturingEngine())  # type: ignore[arg-type]
    from akkord.drive import SheetFile

    rep = pipeline.process_single_pdf(
        SheetFile(id="mem.pdf", name="mem.pdf", source="local", local_path=sheet_pdf)
    )
    assert rep.output_filename == "mem-avec-accords.pdf"
    assert len(captured_layouts) == 2
    for lay in captured_layouts:
        assert lay.clean_png_bytes == b""
        assert lay.guide_png_bytes == b""


def test_async_batch_job_creation_multi_day_deferral_and_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify 30+ file batch jobs process 25 today, defer the remaining 5 to tomorrow, resume on next day, and export ZIP."""
    from akkord.activity import ActivityManager
    from akkord.drive import SheetFile
    from akkord.job_queue import GCSStorageBackend, JobQueueManager

    sample_pdf = create_sample_sheet_without_chords(tmp_path / "base.pdf")

    monkeypatch.setattr(
        "akkord.pipeline.HarmonyEngine.analyze_sheet",
        lambda self, layouts, pdf_path=None: HarmonyAnalysisResult(
            is_music_sheet=True,
            has_existing_chords=False,
            title="Batch Score",
            detected_key="Am",
            overall_summary="Batch analyzed.",
            accuracy_score=100,
            annotations=[
                ChordAnnotation(
                    page_num=1, system_index=1, x_pt=100, chord="Am", status="added"
                )
            ],
            chord_diagrams=[
                GuitarDiagram(name="Am (La m)", frets=["x", "0", "2", "2", "1", "0"])
            ],
        ),
    )

    storage_dir = tmp_path / "queue_store"
    gcs = GCSStorageBackend(storage_dir)
    act_mgr = ActivityManager(storage_dir, gcs_backend=gcs)
    q_mgr = JobQueueManager(storage_dir, activity_manager=act_mgr, gcs_backend=gcs)

    # Create 30 PDF sheets (exceeds the 25 files/day limit by 5 files)
    sheets: list[SheetFile] = []
    for i in range(1, 31):
        fname = f"part-{i:02d}.pdf"
        p = tmp_path / fname
        if not p.exists():
            p.write_bytes(sample_pdf.read_bytes())
        sheets.append(SheetFile(id=fname, name=fname, source="local", local_path=p))

    job = q_mgr.create_batch_job(
        sheets=sheets,
        folder="test-folder",
        language="fr",
        model="gemini-4-argon",
        upload_to_drive=False,
        user_email="alexis.mp@gmail.com",
        is_admin=True,
        run_async=False,
    )

    assert job.total_files == 30
    assert job.queued_today_files == 25
    assert job.deferred_files == 5
    assert job.items[0].status == "queued"
    assert job.items[24].status == "queued"
    assert job.items[25].status == "deferred_next_day"
    assert job.items[29].status == "deferred_next_day"

    # Process the first 25 queued items synchronously via worker method
    for idx in range(25):
        res = q_mgr.process_job_item(job.job_id, job.items[idx].item_id)
        assert res["processed"] is True

    updated_job = q_mgr.get_job(job.job_id)
    assert updated_job is not None
    assert updated_job.completed_files == 25
    assert updated_job.deferred_files == 5
    assert updated_job.status == "partially_deferred"
    assert act_mgr.get_quota_status()["remaining"] == 0

    # Trying to process item #26 today when quota is 0 keeps it in deferred_next_day
    res_26_today = q_mgr.process_job_item(job.job_id, job.items[25].item_id)
    assert res_26_today["processed"] is False
    assert res_26_today["reason"] == "deferred_next_day"

    # Verify ZIP archive creation for the 25 completed PDFs
    zip_res = q_mgr.build_job_zip_bytes(job.job_id)
    assert zip_res is not None
    zip_bytes, zip_name = zip_res
    assert zip_name.endswith(".zip")
    assert len(zip_bytes) > 1000

    # Simulate the next calendar day (00:05 Europe/Paris) and run resume_deferred_jobs
    monkeypatch.setattr(act_mgr, "today_str", lambda: "2099-01-02")
    assert act_mgr.get_quota_status()["remaining"] == 25

    resumed = q_mgr.resume_deferred_jobs(process_immediately_if_local=True)
    assert resumed["resumed_count"] == 5

    final_job = q_mgr.get_job(job.job_id)
    assert final_job is not None
    assert final_job.completed_files == 30
    assert final_job.deferred_files == 0
    assert final_job.status == "completed"


def test_job_cancellation_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify creating an upload job via FastAPI and cancelling it via /api/jobs/{job_id}/cancel."""
    sample_pdf = create_sample_sheet_without_chords(tmp_path / "cancel_me.pdf")
    # Prevent background thread from racing before cancel in this test
    monkeypatch.setattr(
        "akkord.server.job_queue_manager._dispatch_job_items", lambda job: None
    )

    client = TestClient(app)
    with open(sample_pdf, "rb") as f:
        r_create = client.post(
            "/api/jobs/upload",
            files=[("files", ("cancel_me.pdf", f, "application/pdf"))],
            data={"language": "fr", "model": "gemini-4-argon"},
        )
    assert r_create.status_code == 202
    job_data = r_create.json()
    job_id = job_data["job_id"]
    assert job_data["total_files"] == 1

    r_status = client.get(f"/api/jobs/{job_id}")
    assert r_status.status_code == 200

    r_cancel = client.post(f"/api/jobs/{job_id}/cancel")
    assert r_cancel.status_code == 200
    assert r_cancel.json()["status"] == "cancelled"
    assert r_cancel.json()["cancelled_files"] == 1


def test_firestore_persistence_across_deployments_and_sessions(tmp_path: Path) -> None:
    """Verify cost/token tracking and 25-file daily quota persist in Firestore across new deployments and user sessions."""
    from akkord.activity import ActivityManager
    from akkord.firestore_store import (
        FirestoreBackend,
        from_firestore_document,
        to_firestore_fields,
    )
    from akkord.oauth import OAuthManager, UserSession

    # 1. Verify native Firestore Value conversion round-trip
    sample_doc = {
        "date": "2026-10-25",
        "processed_count": 7,
        "daily_limit": 25,
        "digest_sent": False,
        "estimated_cost_usd": 0.08925,
        "estimated_cost_eur": 0.08211,
        "entries": [
            {
                "filename": "partition1.pdf",
                "total_tokens": 14800,
                "estimated_cost_usd": 0.08925,
            }
        ],
    }
    fs_fields = to_firestore_fields(sample_doc)
    assert fs_fields["processed_count"] == {"integerValue": "7"}
    assert fs_fields["digest_sent"] == {"booleanValue": False}
    assert fs_fields["estimated_cost_usd"] == {"doubleValue": 0.08925}
    restored_doc = from_firestore_document({"fields": fs_fields})
    assert restored_doc == sample_doc

    # 2. Simulate Deployment #1 recording analyses into shared Firestore store
    shared_fs_dir = tmp_path / "shared_firestore"
    fs_deploy_1 = FirestoreBackend(shared_fs_dir)
    fs_deploy_1.enabled = True  # Enable Firestore sync cycle

    container_1_tmp = tmp_path / "container_1_ephemeral_tmp"
    mgr_1 = ActivityManager(container_1_tmp, firestore_backend=fs_deploy_1)
    for i in range(4):
        mgr_1.record_analysis(
            {
                "source_name": f"piece-{i + 1}.pdf",
                "output_filename": f"piece-{i + 1}-analyse-accords.pdf",
                "mode": "analyze",
                "title": f"Pièce #{i + 1}",
                "detected_key": "Dm",
                "accuracy_score": 92,
                "annotations_count": 5,
                "token_usage": {
                    "model": "gemini-4-argon",
                    "input_tokens": 2000,
                    "output_tokens": 1000,
                    "thinking_tokens": 500,
                    "cached_tokens": 0,
                    "total_tokens": 3500,
                    "estimated_cost_usd": 0.02,
                    "estimated_cost_eur": 0.0184,
                    "source": "api_metadata",
                },
            },
            user_email="alexis.mp@gmail.com",
            source="drive",
        )

    assert mgr_1.get_quota_status()["used"] == 4
    assert mgr_1.get_quota_status()["remaining"] == 21

    # 3. Simulate Deployment #2 (brand-new ephemeral /tmp directory, wiped local disk)
    container_2_tmp = tmp_path / "container_2_ephemeral_tmp"
    fs_deploy_2 = FirestoreBackend(shared_fs_dir)
    fs_deploy_2.enabled = True
    mgr_2 = ActivityManager(container_2_tmp, firestore_backend=fs_deploy_2)

    # Quota and cost data are preserved in Firestore independently of deployment or user sign-in
    quota_2 = mgr_2.get_quota_status()
    assert quota_2["used"] == 4
    assert quota_2["remaining"] == 21

    usage_2 = mgr_2.get_usage_summary()
    assert usage_2["today"]["files_count"] == 4
    assert usage_2["today"]["total_tokens"] == 14000
    assert usage_2["today"]["estimated_cost_usd"] == pytest.approx(0.08)
    assert usage_2["cumulative"]["files_count"] == 4
    assert usage_2["cumulative"]["estimated_cost_eur"] == pytest.approx(0.0736)

    # Verify global summary document in Firestore
    global_doc = fs_deploy_2.get_document("akkord_usage_summary", "global")
    assert global_doc is not None
    assert global_doc["files_count"] == 4
    assert global_doc["processed_quota_count"] == 4
    assert global_doc["total_tokens"] == 14000

    # 4. Verify OAuth session persistence in Firestore across deployments
    oauth_1 = OAuthManager(container_1_tmp, firestore_backend=fs_deploy_1)
    s = UserSession(
        session_id="custom-session-token",
        email="alexis.mp@gmail.com",
        name="Alexis",
        picture="",
        access_token="tok-123",
        refresh_token="ref-456",
    )
    oauth_1._sessions[s.session_id] = s
    oauth_1._save_sessions()

    oauth_2 = OAuthManager(container_2_tmp, firestore_backend=fs_deploy_2)
    restored_session = oauth_2.get_session("custom-session-token")
    assert restored_session is not None
    assert restored_session.email == "alexis.mp@gmail.com"
    assert restored_session.refresh_token == "ref-456"


def test_unicode_cyrillic_pdf_preview_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify /api/originals and /api/outputs reject non-owners (403) and serve Cyrillic/Unicode PDFs to the owner without UnicodeEncodeError."""
    from urllib.parse import quote

    cyrillic_orig = "Чубчик.pdf"
    cyrillic_out = "Чубчик-analyse-accords.pdf"

    monkeypatch.setattr(
        "akkord.server.job_queue_manager.read_original_pdf",
        lambda name, job_id=None: b"%PDF-1.4 fake orig" if name == cyrillic_orig else None,
    )
    monkeypatch.setattr(
        "akkord.server.job_queue_manager.read_output_pdf",
        lambda name, job_id=None: b"%PDF-1.4 fake out" if name == cyrillic_out else None,
    )

    # 1. Unauthenticated visitor who does not own the file gets 403 Forbidden
    anon_client = TestClient(app)
    assert anon_client.get(f"/api/originals/{quote(cyrillic_orig)}").status_code == 403
    assert anon_client.get(f"/api/outputs/{quote(cyrillic_out)}").status_code == 403

    # 2. Authorized owner gets 200 OK with RFC 5987 UTF-8 Content-Disposition header
    monkeypatch.setattr(
        "akkord.server.job_queue_manager.user_owns_filename",
        lambda owner_id, filename, is_original=False: filename in (cyrillic_orig, cyrillic_out),
    )
    client = TestClient(app)
    r_orig = client.get(f"/api/originals/{quote(cyrillic_orig)}")
    assert r_orig.status_code == 200
    assert "filename*=utf-8''" in r_orig.headers.get("content-disposition", "")

    r_out = client.get(f"/api/outputs/{quote(cyrillic_out)}")
    assert r_out.status_code == 200
    assert "filename*=utf-8''" in r_out.headers.get("content-disposition", "")


def test_multirow_diagrams_system_completeness_and_adaptive_ink_avoidance(
    tmp_path: Path,
) -> None:
    """Verify multi-row chord diagrams, complete staff coverage when a system is skipped, and adaptive pill sizing."""
    from reportlab.pdfgen import canvas as rl_canvas
    from akkord.harmony import _ensure_all_systems_covered
    from akkord.pdf_annotator import (
        _compute_adaptive_pill_metrics,
        _fretboard_diagram_rows_count,
    )
    from akkord.pdf_layout import PageLayout, StaffSystem

    # 1. 8 diagrams on a 595pt-wide portrait page must split across 2 rows of 4 diagrams
    diagrams_8 = [
        GuitarDiagram(name=ch, frets=["x", "0", "2", "2", "1", "0"])
        for ch in ["Am", "Dm", "E7", "C", "G7", "F", "A7", "Bm"]
    ]
    rows, cols = _fretboard_diagram_rows_count(diagrams_8, available_width=470.0)
    assert rows == 2
    assert cols == 4

    # 2. _ensure_all_systems_covered populates a skipped system (e.g. System 5 out of 6)
    p_layout = PageLayout(
        page_num=1,
        width_pt=597.6,
        height_pt=840.5,
        systems=[
            StaffSystem(
                index=i,
                y_top_pt=700.0 - (i - 1) * 110.0,
                y_bottom_pt=678.0 - (i - 1) * 110.0,
                chord_y_pt=715.0 - (i - 1) * 110.0,
                treble_height_pt=15.5,
            )
            for i in range(1, 7)
        ],
    )
    partial_result = HarmonyAnalysisResult(
        is_music_sheet=True,
        has_existing_chords=False,
        title="The Entertainer",
        detected_key="C major",
        overall_summary="Ragtime theme.",
        accuracy_score=100,
        annotations=[
            ChordAnnotation(page_num=1, system_index=s_idx, x_pt=100.0, chord="C", status="added")
            for s_idx in [1, 2, 3, 4, 6]  # System 5 intentionally missing
        ],
        chord_diagrams=diagrams_8,
    )
    _ensure_all_systems_covered(partial_result, [p_layout])
    covered_systems = {a.system_index for a in partial_result.annotations}
    assert covered_systems == {1, 2, 3, 4, 5, 6}

    # 3. Adaptive pill metrics scale down font size on dense 6-system scores with small notes
    dummy_c = rl_canvas.Canvas(str(tmp_path / "dummy.pdf"), pagesize=(597.6, 840.5))
    dense_labels = ["B7", "Em", "Em/B", "Em/G", "Am", "Am/C", "F#m7b5", "B7"]
    f_size, pad_x, pad_y = _compute_adaptive_pill_metrics(
        dummy_c, "Helvetica-Bold", p_layout, 2, dense_labels, has_existing_chords=False
    )
    assert f_size <= 8.5
    assert pad_x <= 2.2
    assert pad_y <= 1.5


def test_gmail_digest_refreshes_expired_cookie_token_and_handles_reauth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify send_daily_digest refreshes expired access tokens first and returns needs_reauth on 401/403."""
    from types import SimpleNamespace
    from akkord.activity import ActivityManager
    from akkord.oauth import OAuthManager

    mgr = ActivityManager(tmp_path)
    mgr.record_analysis(
        {
            "source_name": "test_digest.pdf",
            "output_filename": "test_digest-with-chords.pdf",
            "mode": "add_chords",
            "title": "Test Digest",
            "detected_key": "Am",
            "accuracy_score": 100,
            "annotations_count": 8,
        },
        user_email="alexis.mp@gmail.com",
        source="upload",
    )

    mgr.save_admin_oauth_tokens(
        email="alexis.mp@gmail.com",
        access_token="ya29.expired_stored_token",
        refresh_token="1//valid_refresh_token",
    )

    called_headers: list[str] = []

    class RefreshThenSendClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            if "oauth2.googleapis.com/token" in url:
                return SimpleNamespace(
                    status_code=200,
                    json=lambda: {"access_token": "ya29.freshly_refreshed_token"},
                    text="OK",
                )
            auth_hdr = (kwargs.get("headers") or {}).get("Authorization", "")
            called_headers.append(auth_hdr)
            if "ya29.freshly_refreshed_token" in auth_hdr:
                return SimpleNamespace(
                    status_code=200,
                    json=lambda: {"id": "gmail-msg-001"},
                    text="OK",
                )
            return SimpleNamespace(
                status_code=401,
                json=lambda: {"error": {"code": 401, "message": "Invalid Credentials"}},
                text='{"error": {"code": 401, "message": "Invalid Credentials"}}',
            )

    monkeypatch.setattr("akkord.activity.httpx.Client", RefreshThenSendClient)

    # Even if an expired cookie access token is passed in oauth_access_token,
    # send_daily_digest refreshes via refresh_token first and succeeds!
    res = mgr.send_daily_digest(
        force=True,
        oauth_access_token="ya29.expired_cookie_token",
        oauth_refresh_token="1//valid_refresh_token",
    )
    assert res["sent"] is True
    assert called_headers[0] == "Bearer ya29.freshly_refreshed_token"

    # Now simulate a refresh token that lacks gmail.send scope (403)
    class InsufficientScopeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            if "oauth2.googleapis.com/token" in url:
                return SimpleNamespace(
                    status_code=200,
                    json=lambda: {"access_token": "ya29.no_gmail_scope"},
                    text="OK",
                )
            return SimpleNamespace(
                status_code=403,
                json=lambda: {"error": {"code": 403, "message": "Insufficient Permission"}},
                text='{"error": {"code": 403, "message": "Request had insufficient authentication scopes."}}',
            )

    monkeypatch.setattr("akkord.activity.httpx.Client", InsufficientScopeClient)
    res_403 = mgr.send_daily_digest(force=True)
    assert res_403["sent"] is False
    assert res_403["needs_reauth"] is True
    assert res_403["reauth_url"] == "/auth/login?intent=send_digest"

    # Verify OAuthManager intent encoding in state
    oauth_mgr = OAuthManager(tmp_path)
    auth_url = oauth_mgr.build_authorization_url(
        redirect_uri="https://akkord-2500276981.europe-west1.run.app/auth/callback",
        intent="send_digest",
    )
    assert "send_digest" in auth_url
    state_val = [
        p.split("=", 1)[1]
        for p in auth_url.split("?", 1)[1].split("&")
        if p.startswith("state=")
    ][0]
    from urllib.parse import unquote

    assert OAuthManager.extract_state_intent(unquote(state_val)) == "send_digest"


def test_recent_history_restored_on_page_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify GET /api/jobs returns completed jobs and unified history_items so refreshing the page restores history."""
    from akkord.activity import ActivityManager
    from akkord.drive import SheetFile
    from akkord.job_queue import GCSStorageBackend, JobQueueManager

    sample_pdf = create_sample_sheet_without_chords(tmp_path / "hist.pdf")
    monkeypatch.setattr(
        "akkord.pipeline.HarmonyEngine.analyze_sheet",
        lambda self, layouts, pdf_path=None: HarmonyAnalysisResult(
            is_music_sheet=True,
            has_existing_chords=False,
            title="History Piece",
            detected_key="Dm",
            overall_summary="Restored on refresh.",
            accuracy_score=100,
            annotations=[
                ChordAnnotation(
                    page_num=1, system_index=1, x_pt=100, chord="Dm", status="added"
                )
            ],
            chord_diagrams=[
                GuitarDiagram(name="Dm (Ré m)", frets=["x", "x", "0", "2", "3", "1"])
            ],
        ),
    )

    storage_dir = tmp_path / "hist_store"
    gcs = GCSStorageBackend(storage_dir)
    act_mgr = ActivityManager(storage_dir, gcs_backend=gcs)
    q_mgr = JobQueueManager(storage_dir, activity_manager=act_mgr, gcs_backend=gcs)

    job = q_mgr.create_batch_job(
        sheets=[SheetFile(id="hist.pdf", name="hist.pdf", source="local", local_path=sample_pdf)],
        folder="upload",
        language="fr",
        model="gemini-4-argon",
        upload_to_drive=False,
        run_async=False,
    )
    q_mgr.process_job_item(job.job_id, job.items[0].item_id)

    # Also record a standalone analysis in ActivityManager
    act_mgr.record_analysis(
        {
            "source_name": "standalone.pdf",
            "output_filename": "standalone-analyse-accords.pdf",
            "mode": "analyze",
            "title": "Standalone Piece",
            "detected_key": "Gm",
            "accuracy_score": 90,
            "annotations_count": 7,
            "overall_summary": "Standalone analysis entry.",
        },
        user_email="alexis.mp@gmail.com",
        source="drive",
    )

    history = q_mgr.get_recent_history(limit=25, is_admin=True)
    filenames = [it["filename"] for it in history]
    assert "hist.pdf" in filenames
    assert "standalone.pdf" in filenames


def test_dynamic_harmony_accuracy_score_reflects_findings() -> None:
    """Verify accuracy_score is never stuck at 82% and reflects suggestions, missing chords, and chord errors."""
    from akkord.harmony import (
         _postprocess_harmony_result,
        compute_harmony_accuracy_score,
    )

    # Case 1: Almost all chords are accurate, only 1 minor bass inversion suggestion, 0 missing, 0 errors -> High score (>= 95%)
    res_high = HarmonyAnalysisResult(
        is_music_sheet=True,
        has_existing_chords=True,
        title="Clean Chart",
        detected_key="Am",
        overall_summary="Almost perfect.",
        accuracy_score=82,  # Even if Gemini returned a stale 82, postprocess overrides it!
        annotations=[
            *[
                ChordAnnotation(
                    page_num=1, system_index=1, x_pt=80 + i * 40, chord="Am", status="correct"
                )
                for i in range(15)
            ],
            ChordAnnotation(
                page_num=1,
                system_index=2,
                x_pt=120,
                chord="Am",
                status="improve",
                suggested_chord="Am/C",
            ),
        ],
    )
    _postprocess_harmony_result(res_high, [], "fr")
    assert res_high.accuracy_score >= 95
    assert res_high.accuracy_score != 82

    # Case 2: Moderate bass counterpoint suggestions, 1 missing chord, no wrong chord roots -> Medium-good score (72% - 86%)
    res_medium = HarmonyAnalysisResult(
        is_music_sheet=True,
        has_existing_chords=True,
        title="Moderate Chart",
        detected_key="Dm",
        overall_summary="Some bass improvements and 1 missing chord.",
        accuracy_score=82,
        annotations=[
            *[
                ChordAnnotation(
                    page_num=1, system_index=1, x_pt=80 + i * 45, chord="Dm", status="correct"
                )
                for i in range(8)
            ],
            *[
                ChordAnnotation(
                    page_num=1,
                    system_index=2,
                    x_pt=80 + i * 50,
                    chord="Gm",
                    status="improve",
                    suggested_chord="Gm/Bb",
                )
                for i in range(6)
            ],
            ChordAnnotation(
                page_num=1,
                system_index=3,
                x_pt=200,
                chord="A7/C#",
                status="missing",
                suggested_chord="A7/C#",
            ),
        ],
    )
    score_medium = compute_harmony_accuracy_score(res_medium)
    assert 72 <= score_medium <= 86
    assert score_medium < res_high.accuracy_score

    # Case 3: Several missing chords AND wrong chord roots/qualities -> Low score (<= 65%)
    res_low = HarmonyAnalysisResult(
        is_music_sheet=True,
        has_existing_chords=True,
        title="Flawed Chart",
        detected_key="Em",
        overall_summary="Multiple missing chords and wrong harmonies.",
        accuracy_score=82,
        annotations=[
            *[
                ChordAnnotation(
                    page_num=1, system_index=1, x_pt=80 + i * 60, chord="Em", status="correct"
                )
                for i in range(4)
            ],
            *[
                ChordAnnotation(
                    page_num=1,
                    system_index=2,
                    x_pt=80 + i * 60,
                    chord="Em",
                    status="improve",
                    suggested_chord="G/B",  # Different root & quality!
                )
                for i in range(5)
            ],
            *[
                ChordAnnotation(
                    page_num=1,
                    system_index=3,
                    x_pt=80 + i * 60,
                    chord="Am",
                    status="improve",
                    suggested_chord="Am/C",
                )
                for i in range(6)
            ],
            *[
                ChordAnnotation(
                    page_num=1,
                    system_index=4,
                    x_pt=80 + i * 80,
                    chord="B7",
                    status="missing",
                    suggested_chord="B7",
                )
                for i in range(4)
            ],
        ],
    )
    score_low = compute_harmony_accuracy_score(res_low)
    assert score_low <= 65
    assert score_low < score_medium


def test_admin_reset_daily_quota(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify only admin can force-reset the 25-file daily quota while preserving cost/token entries."""
    from akkord.activity import ActivityManager
    from akkord.oauth import UserSession
    import akkord.server as srv

    act_mgr = ActivityManager(tmp_path / "reset_quota_store")
    monkeypatch.setattr(srv, "activity_manager", act_mgr)

    for i in range(5):
        act_mgr.record_analysis(
            {
                "source_name": f"sheet-{i}.pdf",
                "title": f"Sheet {i}",
                "detected_key": "Am",
                "mode": "analyze",
                "accuracy_score": 90,
                "annotations_count": 4,
                "language": "fr",
                "model": "gemini-4-argon",
                "token_usage": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "total_tokens": 1500,
                    "estimated_cost_usd": 0.01,
                    "estimated_cost_eur": 0.009,
                },
            },
            user_email="alexis.mp@gmail.com",
            source="upload",
        )

    assert act_mgr.get_quota_status()["used"] == 5
    assert act_mgr.get_quota_status()["remaining"] == 20

    client = TestClient(app)

    # Unauthenticated -> 403
    r_unauth = client.post("/api/admin/reset-quota")
    assert r_unauth.status_code == 403

    # Non-admin -> 403
    guest_cookie = srv.oauth_manager.encode_session_cookie(
        UserSession(
            session_id="user-sess",
            email="guest@example.com",
            name="Guest",
            picture="",
            access_token="tok",
            refresh_token="ref",
        )
    )
    client.cookies.set("akkord_session", guest_cookie)
    r_guest = client.post("/api/admin/reset-quota")
    assert r_guest.status_code == 403

    # Admin -> 200 and quota reset to 0 while entries remain preserved
    admin_cookie = srv.oauth_manager.encode_session_cookie(
        UserSession(
            session_id="admin-sess",
            email="alexis.mp@gmail.com",
            name="Alexis",
            picture="",
            access_token="tok",
            refresh_token="ref",
        )
    )
    client.cookies.set("akkord_session", admin_cookie)
    r_admin = client.post("/api/admin/reset-quota")
    assert r_admin.status_code == 200
    payload = r_admin.json()
    assert payload["reset"] is True
    assert payload["daily_quota"]["used"] == 0
    assert payload["daily_quota"]["remaining"] == 25
    assert payload["daily_quota"]["previous_used"] == 5
    assert payload["admin_usage"]["today"]["files_count"] == 5
    assert payload["admin_usage"]["today"]["total_tokens"] == 7500


def test_truncation_detection_and_multi_slash_chord_sanitization() -> None:
    """Verify multi-slash repetition loops are compacted and truncated system coverage is detected."""
    from akkord.harmony import (
        _ensure_all_systems_covered,
        _is_analysis_truncated,
        extract_compact_chord_symbol,
    )
    from akkord.pdf_layout import PageLayout, StaffSystem

    # Multi-slash repetition loop like Smuglyanka's A7/Cdim7/C#7/C#5/...
    rep_chord = "A7/Cdim7/" + "/".join(["C#7/C#5"] * 50)
    assert extract_compact_chord_symbol(rep_chord)[0] == "A7/C#"

    # Pipe table hallucination like Danube Waves
    pipe_chord = "|Am7/G |F#7/A# |Bm |E7"
    assert extract_compact_chord_symbol(pipe_chord)[0] == "Am7/G"

    layout_6 = PageLayout(
        page_num=1,
        width_pt=595.0,
        height_pt=842.0,
        systems=[
            StaffSystem(
                index=i,
                y_top_pt=700.0 - (i - 1) * 95.0,
                y_bottom_pt=680.0 - (i - 1) * 95.0,
                chord_y_pt=714.0 - (i - 1) * 95.0,
            )
            for i in range(1, 7)
        ],
    )
    truncated_res = HarmonyAnalysisResult(
        is_music_sheet=True,
        has_existing_chords=True,
        title="Смуглянка",
        detected_key="Dm",
        overall_summary="Truncated after S1.",
        accuracy_score=76,
        annotations=[
            ChordAnnotation(page_num=1, system_index=1, x_pt=135.0, chord="Gm", status="correct"),
            ChordAnnotation(page_num=1, system_index=1, x_pt=255.0, chord="Dm", status="correct"),
            ChordAnnotation(page_num=1, system_index=1, x_pt=385.0, chord="Gm", status="improve", suggested_chord="Edim7"),
            ChordAnnotation(page_num=1, system_index=1, x_pt=430.0, chord="A7", status="improve", suggested_chord=rep_chord),
        ],
    )
    assert _is_analysis_truncated(truncated_res, [layout_6]) is True

    _ensure_all_systems_covered(truncated_res, [layout_6])
    covered = {a.system_index for a in truncated_res.annotations}
    assert covered == {1, 2, 3, 4, 5, 6}


def test_spaced_minor_chord_token_and_d_minor_analysis(tmp_path: Path) -> None:
    """Verify spaced minor chord tokens like 'G m' are extracted as 'Gm' (not 'G') and analyzed in D minor as Gm -> Gm/Bb."""
    from reportlab.pdfgen import canvas as rl_canvas
    from akkord.harmony import _extract_pdf_text_tokens, _fallback_analyze_sheet_from_pdf

    pdf_path = tmp_path / "zasidelas_odna.pdf"
    c = rl_canvas.Canvas(str(pdf_path), pagesize=(595.0, 842.0))
    c.setFont("Helvetica-Bold", 16)
    c.drawString(220, 780, "Zasidelas odna")
    # Draw 5-line staff for System 1
    c.setLineWidth(0.8)
    for i in range(5):
        y = 680 + i * 6
        c.line(60, y, 535, y)
    # Insert spaced 'G m' chord token as found in printed Russian songbooks
    c.setFont("Helvetica", 11)
    c.drawString(100, 712, "Dm")
    c.drawString(220, 712, "G m")
    c.drawString(340, 712, "A7")
    c.drawString(460, 712, "Dm")
    c.showPage()
    c.save()

    layouts = analyze_pdf_layout(pdf_path)
    _, chord_tokens = _extract_pdf_text_tokens(pdf_path, layouts)
    extracted_chords = [t[3] for t in chord_tokens]
    assert "Gm" in extracted_chords
    assert "G" not in extracted_chords

    res = _fallback_analyze_sheet_from_pdf(pdf_path, layouts, "fr")
    assert "Dm" in res.detected_key
    gm_anns = [a for a in res.annotations if a.chord == "Gm"]
    assert len(gm_anns) == 1
    assert gm_anns[0].suggested_chord == "Gm/Bb"
    assert all(a.suggested_chord != "G7/B" for a in res.annotations)


def test_greensleeves_guitar_easy_chord_analysis() -> None:
    """Verify Greensleeves-Guitar-Easy.pdf (with printed chords) extracts its 19 chords and generates 4 review badges."""
    from akkord.harmony import _extract_pdf_text_tokens, _fallback_analyze_sheet_from_pdf

    sample_pdf = Path(__file__).resolve().parent.parent / "samples" / "Greensleeves-Guitar-Easy.pdf"
    assert sample_pdf.exists()
    layouts = analyze_pdf_layout(sample_pdf)
    _, chord_tokens = _extract_pdf_text_tokens(sample_pdf, layouts)
    assert len(chord_tokens) == 24
    assert [t[3] for t in chord_tokens[:6]] == ["Am", "G", "Em", "Am", "F", "E"]

    res_en = _fallback_analyze_sheet_from_pdf(sample_pdf, layouts, "en")
    assert res_en.has_existing_chords is True
    assert "Am" in res_en.detected_key
    badge_chords = [
        (a.suggested_chord or a.chord, a.status, a.measure_number)
        for a in res_en.annotations
        if a.status in ("improve", "missing", "wrong")
    ]
    assert badge_chords == [
        ("D/F#", "improve", 4),
        ("E7/G#", "improve", 8),
        ("Am", "missing", 10),
        ("G/B", "improve", 16),
    ]


def test_beat1_snapping_within_each_measure_without_crossing_measures() -> None:
    """Verify chords floating in the middle of Measure 2 or 3 snap to Beat 1 of their own measure, never to Measure 1."""
    from akkord.harmony import _postprocess_harmony_result
    from akkord.pdf_layout import PageLayout, StaffSystem

    # Barlines for a 4-measure system: M1=[53..150], M2=[150..270], M3=[270..390], M4=[390..520]
    layout = PageLayout(
        page_num=1,
        width_pt=595.0,
        height_pt=842.0,
        systems=[
            StaffSystem(
                index=1,
                y_top_pt=700.0,
                y_bottom_pt=640.0,
                chord_y_pt=714.0,
                barlines_x_pt=[53.0, 150.0, 270.0, 390.0, 520.0],
            )
        ],
    )
    raw = HarmonyAnalysisResult(
        is_music_sheet=True,
        has_existing_chords=True,
        title="La Partida",
        detected_key="Am",
        overall_summary="Beat-1 alignment test.",
        accuracy_score=80,
        annotations=[
            # No chord in Measure 1 (anacrusis)
            # Chord in Measure 2 placed in the middle of Measure 2 (x=210.0)
            ChordAnnotation(page_num=1, system_index=1, x_pt=210.0, chord="Am", status="correct", measure_number=2),
            # Chord in Measure 3 placed in the middle of Measure 3 (x=335.0)
            ChordAnnotation(
                page_num=1,
                system_index=1,
                x_pt=335.0,
                chord="Am/C",
                status="missing",
                suggested_chord="Am/C",
                measure_number=3,
            ),
            # Two chords in Measure 4 (Beat 1 at 398.0 and Beat 3 at 475.0) -> must NOT collapse onto Beat 1
            ChordAnnotation(page_num=1, system_index=1, x_pt=398.0, chord="E", status="improve", suggested_chord="E7", measure_number=4),
            ChordAnnotation(page_num=1, system_index=1, x_pt=475.0, chord="E7/G#", status="missing", suggested_chord="E7/G#", measure_number=4),
        ],
    )

    processed = _postprocess_harmony_result(raw, [layout], lang="fr")
    xs = [a.x_pt for a in processed.annotations]
    # Measure 2 chord snapped to Beat 1 of Measure 2 (150 + 8 = 158.0), NOT shifted to Measure 1
    assert xs[0] == 158.0
    # Measure 3 chord snapped to Beat 1 of Measure 3 (270 + 8 = 278.0), NOT shifted to Measure 1 or 2
    assert xs[1] == 278.0
    # Measure 4's two chords remain distinct at 398.0 and 475.0
    assert xs[2] == 398.0
    assert xs[3] == 475.0


def test_strict_user_and_anonymous_privacy_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that documents, jobs, and analyses are strictly private to their owner and never leaked across users or anonymous visitors."""
    from akkord.activity import ActivityManager
    from akkord.drive import SheetFile
    from akkord.firestore_store import FirestoreBackend
    from akkord.job_queue import GCSStorageBackend, JobQueueManager
    from akkord.oauth import UserSession
    import akkord.server as srv

    sample_pdf = create_sample_sheet_without_chords(tmp_path / "private_score.pdf")
    monkeypatch.setattr(
        "akkord.pipeline.HarmonyEngine.analyze_sheet",
        lambda self, layouts, pdf_path=None: HarmonyAnalysisResult(
            is_music_sheet=True,
            has_existing_chords=False,
            title="Private Score",
            detected_key="Am",
            overall_summary="Strictly private analysis.",
            accuracy_score=100,
            annotations=[
                ChordAnnotation(
                    page_num=1, system_index=1, x_pt=100, chord="Am", status="added"
                )
            ],
            chord_diagrams=[
                GuitarDiagram(name="Am (La m)", frets=["x", "0", "2", "2", "1", "0"])
            ],
        ),
    )

    store_dir = tmp_path / "privacy_store"
    fs = FirestoreBackend(store_dir)
    gcs = GCSStorageBackend(store_dir)
    act_mgr = ActivityManager(store_dir, gcs_backend=gcs, firestore_backend=fs)
    q_mgr = JobQueueManager(store_dir, activity_manager=act_mgr, gcs_backend=gcs)

    monkeypatch.setattr(srv, "activity_manager", act_mgr)
    monkeypatch.setattr(srv, "job_queue_manager", q_mgr)
    monkeypatch.setattr(srv, "OUTPUTS_DIR", store_dir)
    monkeypatch.setattr(srv, "UPLOADS_DIR", store_dir / "_uploads")

    # 1. Create a job owned by alexis.mp@gmail.com and a legacy job with empty user_email/owner_id
    admin_job = q_mgr.create_batch_job(
        sheets=[
            SheetFile(
                id="alexis-secret.pdf",
                name="alexis-secret.pdf",
                source="upload",
                local_path=sample_pdf,
            )
        ],
        folder="upload",
        language="fr",
        model="gemini-4-argon",
        upload_to_drive=False,
        user_email="alexis.mp@gmail.com",
        is_admin=True,
        run_async=False,
        owner_id="user:alexis.mp@gmail.com",
    )
    q_mgr.process_job_item(admin_job.job_id, admin_job.items[0].item_id)

    legacy_job = q_mgr.create_batch_job(
        sheets=[
            SheetFile(
                id="legacy-untagged.pdf",
                name="legacy-untagged.pdf",
                source="upload",
                local_path=sample_pdf,
            )
        ],
        folder="upload",
        language="fr",
        model="gemini-4-argon",
        upload_to_drive=False,
        user_email="",
        is_admin=False,
        run_async=False,
        owner_id="",
    )
    q_mgr.process_job_item(legacy_job.job_id, legacy_job.items[0].item_id)

    # 2. Unauthenticated visitor visits the app -> MUST see 0 jobs and 0 history_items!
    anon_visitor = TestClient(app)
    r_jobs_anon = anon_visitor.get("/api/jobs")
    assert r_jobs_anon.status_code == 200
    assert r_jobs_anon.json()["jobs"] == []
    assert r_jobs_anon.json()["history_items"] == []
    assert "akkord_anon" in anon_visitor.cookies

    # Unauthenticated visitor attempting to access alexis.mp@gmail.com's job, ZIP, or PDFs gets 403 Forbidden
    assert anon_visitor.get(f"/api/jobs/{admin_job.job_id}").status_code == 403
    assert anon_visitor.post(f"/api/jobs/{admin_job.job_id}/cancel").status_code == 403
    assert anon_visitor.get(f"/api/jobs/{admin_job.job_id}/download-zip").status_code == 403
    assert (
        anon_visitor.get(
            f"/api/jobs/{admin_job.job_id}/outputs/alexis-secret-avec-accords.pdf"
        ).status_code
        == 403
    )
    assert (
        anon_visitor.get(
            f"/api/jobs/{admin_job.job_id}/originals/alexis-secret.pdf"
        ).status_code
        == 403
    )
    assert (
        anon_visitor.get("/api/outputs/alexis-secret-avec-accords.pdf").status_code
        == 403
    )
    assert anon_visitor.get("/api/originals/alexis-secret.pdf").status_code == 403

    # 3. Authenticated user B (other@example.com) also cannot see or download alexis.mp@gmail.com's jobs/files
    other_cookie = srv.oauth_manager.encode_session_cookie(
        UserSession(
            session_id="other-sess",
            email="other@example.com",
            name="Other User",
            picture="",
            access_token="tok-other",
            refresh_token="ref-other",
        )
    )
    other_client = TestClient(app)
    other_client.cookies.set("akkord_session", other_cookie)
    r_jobs_other = other_client.get("/api/jobs")
    assert r_jobs_other.status_code == 200
    assert r_jobs_other.json()["jobs"] == []
    assert r_jobs_other.json()["history_items"] == []
    assert other_client.get(f"/api/jobs/{admin_job.job_id}").status_code == 403

    # 4. Anonymous visitor A uploads a PDF -> only Anonymous visitor A can see & download it; Anonymous visitor B cannot
    monkeypatch.setattr(q_mgr, "_dispatch_job_items", lambda job: None)
    with open(sample_pdf, "rb") as f:
        r_anon_up = anon_visitor.post(
            "/api/jobs/upload",
            files=[("files", ("anon-a-sheet.pdf", f, "application/pdf"))],
            data={"language": "fr", "model": "gemini-4-argon"},
        )
    assert r_anon_up.status_code == 202
    anon_job_id = r_anon_up.json()["job_id"]
    q_mgr.process_job_item(anon_job_id, "item-0001")

    # Anonymous visitor A sees their own job and can download their annotated PDF
    r_anon_a_list = anon_visitor.get("/api/jobs")
    assert len(r_anon_a_list.json()["jobs"]) == 1
    assert r_anon_a_list.json()["jobs"][0]["job_id"] == anon_job_id
    r_anon_a_pdf = anon_visitor.get(
        f"/api/jobs/{anon_job_id}/outputs/anon-a-sheet-avec-accords.pdf"
    )
    assert r_anon_a_pdf.status_code == 200

    # Anonymous visitor B (different browser) sees nothing and gets 403 on Anonymous visitor A's job/PDF
    anon_visitor_b = TestClient(app)
    assert anon_visitor_b.get("/api/jobs").json()["jobs"] == []
    assert anon_visitor_b.get(f"/api/jobs/{anon_job_id}").status_code == 403
    assert (
        anon_visitor_b.get(
            f"/api/jobs/{anon_job_id}/outputs/anon-a-sheet-avec-accords.pdf"
        ).status_code
        == 403
    )

    # 5. Even when alexis.mp@gmail.com logs in, their main workspace (/api/jobs) only shows their own jobs (not anon_visitor's job),
    # while the Admin Token/Cost summary (/api/admin/usage) tracks all 3 processed files!
    admin_cookie = srv.oauth_manager.encode_session_cookie(
        UserSession(
            session_id="adm-sess",
            email="alexis.mp@gmail.com",
            name="Alexis MP",
            picture="",
            access_token="tok-adm",
            refresh_token="ref-adm",
        )
    )
    admin_client = TestClient(app)
    admin_client.cookies.set("akkord_session", admin_cookie)
    r_admin_jobs = admin_client.get("/api/jobs").json()
    admin_job_ids = {j["job_id"] for j in r_admin_jobs["jobs"]}
    assert admin_job.job_id in admin_job_ids
    assert legacy_job.job_id in admin_job_ids
    assert anon_job_id not in admin_job_ids
    assert (
        admin_client.get(
            f"/api/jobs/{admin_job.job_id}/outputs/alexis-secret-avec-accords.pdf"
        ).status_code
        == 200
    )

    r_admin_usage = admin_client.get("/api/admin/usage").json()
    assert r_admin_usage["today"]["files_count"] == 3

    # 6. Logging out clears the session and rotates akkord_anon so /api/jobs immediately returns empty
    r_logout = admin_client.post("/api/auth/logout")
    assert r_logout.status_code == 200
    assert admin_client.get("/api/jobs").json()["jobs"] == []
    assert admin_client.get("/api/jobs").json()["history_items"] == []
    assert admin_client.get(f"/api/jobs/{admin_job.job_id}").status_code == 403

    # 7. Claiming anonymous jobs upon OAuth login transfers ownership to the authenticated user
    anon_id_a = srv.oauth_manager.decode_anon_cookie(anon_visitor.cookies.get("akkord_anon"))
    assert anon_id_a is not None
    claimed = q_mgr.claim_anonymous_jobs(f"anon:{anon_id_a}", "other@example.com")
    assert claimed == 1
    assert other_client.get(f"/api/jobs/{anon_job_id}").status_code == 200


def test_per_user_anonymous_and_global_200_quota_enforcement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify 5 PDF/day anonymous quota, 25 PDF/day per-user quota, OAuth login deduction, admin-only personal reset, and 200 PDF/day global ceiling."""
    from akkord.activity import (
        ANON_DAILY_FILE_LIMIT,
        DAILY_FILE_LIMIT,
        GLOBAL_DAILY_FILE_LIMIT,
        ActivityManager,
    )
    from akkord.job_queue import GCSStorageBackend, JobQueueManager
    from akkord.oauth import UserSession
    import akkord.server as srv

    assert ANON_DAILY_FILE_LIMIT == 5
    assert DAILY_FILE_LIMIT == 25
    assert GLOBAL_DAILY_FILE_LIMIT == 200

    store_dir = tmp_path / "quota_isolation_store"
    act_mgr = ActivityManager(store_dir)
    gcs_mgr = GCSStorageBackend(store_dir)
    q_mgr = JobQueueManager(store_dir, act_mgr, gcs_mgr)
    monkeypatch.setattr(srv, "activity_manager", act_mgr)
    monkeypatch.setattr(srv, "job_queue_manager", q_mgr)

    anon_owner = "anon:visitor_1"
    user_alice = "user:alice@example.com"
    user_bob = "user:bob@example.com"
    user_admin = "user:alexis.mp@gmail.com"

    # 1. Anonymous visitor starts with 5/day limit
    q_anon_0 = act_mgr.get_quota_status(owner_id=anon_owner)
    assert q_anon_0["limit"] == 5
    assert q_anon_0["used"] == 0
    assert q_anon_0["remaining"] == 5
    assert q_anon_0["global_limit"] == 200

    # Record 5 analyses for anonymous visitor -> hits 5/day cap
    for i in range(5):
        act_mgr.record_analysis(
            {
                "source_name": f"anon-{i + 1}.pdf",
                "output_filename": f"anon-{i + 1}-avec-accords.pdf",
                "mode": "add_chords",
                "title": f"Anon {i + 1}",
                "detected_key": "C",
                "accuracy_score": 100,
                "annotations_count": 4,
            },
            user_email="",
            source="upload",
            owner_id=anon_owner,
        )

    q_anon_5 = act_mgr.get_quota_status(owner_id=anon_owner)
    assert q_anon_5["used"] == 5
    assert q_anon_5["remaining"] == 0
    assert act_mgr.can_process_more_today(owner_id=anon_owner) is False

    # Other users still have their full 25/day quota
    q_bob_0 = act_mgr.get_quota_status(owner_id=user_bob)
    assert q_bob_0["limit"] == 25
    assert q_bob_0["used"] == 0
    assert q_bob_0["remaining"] == 25
    assert q_bob_0["global_used"] == 5
    assert q_bob_0["global_remaining"] == 195

    # 2. Anonymous visitor signs in as Alice -> 5 PDFs are attached to Alice and deducted from her 25/day quota (20 remaining)
    act_mgr.claim_anonymous_entries(anon_owner, "alice@example.com")
    q_alice = act_mgr.get_quota_status(owner_id=user_alice)
    assert q_alice["limit"] == 25
    assert q_alice["used"] == 5
    assert q_alice["remaining"] == 20
    assert act_mgr.can_process_more_today(owner_id=user_alice) is True

    # 3. Admin records 10 PDFs, then resets quota via /api/admin/reset-quota -> resets ONLY Admin's personal quota (0/25), NOT Alice's or global_used
    for i in range(10):
        act_mgr.record_analysis(
            {
                "source_name": f"admin-{i + 1}.pdf",
                "output_filename": f"admin-{i + 1}-avec-accords.pdf",
                "mode": "analyze",
                "title": f"Admin {i + 1}",
                "detected_key": "Am",
                "accuracy_score": 90,
                "annotations_count": 6,
            },
            user_email="alexis.mp@gmail.com",
            source="drive",
            owner_id=user_admin,
        )

    assert act_mgr.get_quota_status(owner_id=user_admin)["used"] == 10
    assert act_mgr.get_quota_status(owner_id=user_admin)["global_used"] == 15

    admin_cookie = srv.oauth_manager.encode_session_cookie(
        UserSession(
            session_id="adm-quota-sess",
            email="alexis.mp@gmail.com",
            name="Alexis",
            picture="",
            access_token="tok",
            refresh_token="ref",
        )
    )
    client = TestClient(app)
    client.cookies.set("akkord_session", admin_cookie)
    r_reset = client.post("/api/admin/reset-quota")
    assert r_reset.status_code == 200
    reset_data = r_reset.json()["daily_quota"]
    assert reset_data["used"] == 0
    assert reset_data["remaining"] == 25
    assert reset_data["previous_used"] == 10
    # Global counter (15/200) and Alice's counter (5/25) are untouched!
    assert reset_data["global_used"] == 15
    assert reset_data["global_remaining"] == 185
    assert act_mgr.get_quota_status(owner_id=user_alice)["used"] == 5
    assert act_mgr.get_quota_status(owner_id=user_alice)["remaining"] == 20

    # 4. Global 200 PDF/day cap blocks everyone once 200 total PDFs have been processed today
    for i in range(185):
        act_mgr.record_analysis(
            {
                "source_name": f"bulk-{i + 1}.pdf",
                "output_filename": f"bulk-{i + 1}-avec-accords.pdf",
                "mode": "add_chords",
                "title": f"Bulk {i + 1}",
                "detected_key": "G",
                "accuracy_score": 100,
                "annotations_count": 4,
            },
            user_email=f"user{i // 20}@example.com",
            source="upload",
            owner_id=f"user:user{i // 20}@example.com",
        )

    q_bob_at_cap = act_mgr.get_quota_status(owner_id=user_bob)
    assert q_bob_at_cap["used"] == 0
    assert q_bob_at_cap["owner_remaining"] == 25
    assert q_bob_at_cap["global_used"] == 200
    assert q_bob_at_cap["global_remaining"] == 0
    assert q_bob_at_cap["remaining"] == 0
    assert act_mgr.can_process_more_today(owner_id=user_bob) is False















