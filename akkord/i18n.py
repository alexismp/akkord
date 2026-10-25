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
"""Localization (i18n) strings and prompt directives for French and English output."""

from typing import Any

LOCALES: dict[str, dict[str, Any]] = {
    "fr": {
        "language_name": "French (Français)",
        "add_chords_subtitle": "Grille d'accords & lignes de basse (Tonalité : {key})",
        "analyze_chords_subtitle": "Analyse harmonique, contrepoint & revue des accords (Tonalité : {key})",
        "diagrams_title": "Diagrammes des accords principaux ({title})",
        "slash_chords_title": "Propositions de basses — Contrepoint & Walking Bass (anti-fondamentale / anti-doublage) :",
        "bass_proposals_title": "Propositions de basses (Contrepoint & Walking Bass) :",
        "add_chords_footer_note": (
            "Note : Chaque étiquette bleue au-dessus de la portée indique l'accord ou le renversement de basse "
            "(walking bass / mouvement contraire) aligné sur le temps correspondant."
        ),
        "analysis_box_title": "Bilan harmonique & contrepoint de basse ({title})",
        "analysis_accuracy_label": "Précision globale des accords existants : {score}%",
        "analysis_summary_label": "Synthèse :",
        "analysis_legend": (
            "Légende :  [OK Vert] Accord exact   "
            "[* Orange] Amélioration / Basse contrepoint   [+ Rouge] Accord manquant"
        ),
        "section_improvements": "Améliorations & basses contrepoint suggérées :",
        "section_missing": "Accords manquants détectés :",
        "section_correct": "Accords existants validés :",
        "section_bass_proposals": "Ligne de basse — Contrepoint & Walking Bass :",
        "no_issues": "Aucun accord manquant ou erroné détecté.",
        "file_suffix_added": "-avec-accords.pdf",
        "file_suffix_analyzed": "-analyse-accords.pdf",
        "prompt_directive": (
            "Respond strictly in French (Français). "
            "For guitar chord diagram titles, include both standard international notation "
            "and French Solfège in parentheses, e.g., 'Am (La m)', 'Dm (Ré m)', 'E (Mi)', "
            "'C (Do)', 'G (Sol)', 'F (Fa)', 'A7 (La 7)'. "
            "For inline staff chord symbols, keep standard international symbols (e.g., 'Am', 'Dm/F', 'G/B', 'E7/G#') "
            "so they stay compact above the staff. "
            "CRITICAL COUNTERPOINT & WALKING BASS RULE: "
            "Avoid the trap of systematically using the root note (fondamentale) in the bass or doubling the melody note! "
            "Apply strict counterpoint rules (contrary motion / mouvement contraire against the melody, using the 3rd, 5th, or 7th in the bass when the melody plays the root or moves in parallel) "
            "and walking bass principles (conjoint diatonic or chromatic bass lines connecting chords across measures, e.g. Am -> Am/G -> Dm/F -> E7 or Em -> D/F# -> G -> E7/G# -> Am). "
            "Populate `bass_line_proposals` with specific measure-by-measure bass proposals explaining how each slash chord avoids melody doubling or root monotony. "
            "Write all harmonic explanations, counterpoint/walking-bass notes, and review comments in French."
        ),
    },
    "en": {
        "language_name": "English",
        "add_chords_subtitle": "Guitar Chord Chart & Bass Counterpoint (Key: {key})",
        "analyze_chords_subtitle": "Harmonic Analysis, Counterpoint & Chord Review (Key: {key})",
        "diagrams_title": "Main Guitar Chord Diagrams ({title})",
        "slash_chords_title": "Bass Line Proposals — Counterpoint & Walking Bass (anti-root / anti-melody-doubling):",
        "bass_proposals_title": "Bass Line Proposals (Counterpoint & Walking Bass):",
        "add_chords_footer_note": (
            "Note: Each blue pill above the staff marks the chord or inverted bass note "
            "(walking bass / contrary motion) aligned directly with its beat."
        ),
        "analysis_box_title": "Harmonic & Bass Counterpoint Review ({title})",
        "analysis_accuracy_label": "Overall accuracy of existing chords: {score}%",
        "analysis_summary_label": "Summary:",
        "analysis_legend": (
            "Score Legend:  [OK Green] Accurate chord   "
            "[* Amber] Suggested improvement / Bass counterpoint   [+ Red] Missing chord"
        ),
        "section_improvements": "Suggested Chord & Bass Improvements:",
        "section_missing": "Missing Chords Detected:",
        "section_correct": "Confirmed Existing Chords:",
        "section_bass_proposals": "Bass Line — Counterpoint & Walking Bass:",
        "no_issues": "No missing or inaccurate chords detected.",
        "file_suffix_added": "-with-chords.pdf",
        "file_suffix_analyzed": "-chord-analysis.pdf",
        "prompt_directive": (
            "Respond strictly in English. "
            "Use standard international chord notation (e.g., 'Am', 'Dm/F', 'E7/G#', 'G/B'). "
            "CRITICAL COUNTERPOINT & WALKING BASS RULE: "
            "Avoid systematically placing the chord root in the bass or doubling the melody note! "
            "Use counterpoint rules (contrary motion against the melody, placing the 3rd, 5th, or 7th in the bass when the melody plays the root) "
            "and walking bass movement (stepwise diatonic or chromatic bass lines across measures, e.g., Am -> Am/G -> Dm/F -> E7). "
            "Populate `bass_line_proposals` with specific measure-by-measure bass proposals explaining how each slash chord avoids melody doubling or root monotony. "
            "Write all harmonic explanations, counterpoint/walking-bass notes, and review comments in clear English."
        ),
    },
}


def get_locale(lang: str) -> dict[str, Any]:
    """Return locale dictionary for 'fr' or 'en'."""
    key = (lang or "fr").lower().strip()
    if key not in LOCALES:
        raise ValueError(f"Unsupported language '{lang}'. Supported: {list(LOCALES.keys())}")
    return LOCALES[key]


def t(lang: str, msg_id: str, **kwargs: Any) -> str:
    """Format a localized string by msg_id."""
    loc = get_locale(lang)
    template = str(loc.get(msg_id, msg_id))
    return template.format(**kwargs) if kwargs else template
