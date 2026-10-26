/*
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
(() => {
  const I18N = {
    fr: {
      doc_title: "Akkord — Analyse harmonique, Contrepoint & Walking Bass",
      header_eyebrow: "Music Harmony & Counterpoint Studio",
      header_subtitle_html:
        "Importez une partition PDF ou connectez un dossier Google Drive. Akkord vérifie ou génère la grille d'accords, propose des <strong>lignes de basse en contrepoint &amp; walking bass</strong>, et produit un PDF annoté en Français ou en Anglais.",
      ui_lang_switcher_aria: "Langue de l'interface",
      quota_badge_title: "Limite quotidienne de 25 partitions PDF par jour",
      quota_badge_text: "Quota : {used} / {limit} PDF",
      header_login_btn: "🔐 Connexion Google Drive",
      header_admin_badge: "Administrateur",
      header_logout_btn: "Déconnexion",
      auth_google_prefix: "Google : {email}",

      card1_heading: "1. Langue du PDF annoté",
      card1_legend: "Langue du PDF annoté",
      lang_fr_title: "Français (FR)",
      lang_fr_desc:
        "Grille d'accords, Solfège (Am / La m) & propositions de basses (contrepoint / walking bass)",
      lang_en_title: "English (EN)",
      lang_en_desc:
        "Standard chord symbols (Am, Dm/F, G/B) & counterpoint / walking-bass review",

      admin_menu_summary: "Menu avancé (Modèle, Suivi des tokens & coûts, Actions)",
      admin_model_label: "Modèle d'analyse harmonique",
      admin_badge_paren: "(Admin)",
      admin_model_hint_html: "Réservé à l'administrateur (<code>alexis.mp@gmail.com</code>).",
      admin_usage_heading: "Suivi des tokens & Coûts estimés (Admin)",
      admin_kpi_today_tokens: "Aujourd'hui (Tokens)",
      admin_kpi_today_cost: "Aujourd'hui (Coût estimé)",
      admin_kpi_cum_cost: "Cumul global (Tokens & Coût)",
      admin_today_files_count: "{count} partition(s) aujourd'hui",
      admin_cum_tokens_sub: "{tokens} tok au total ({files} fichiers)",
      admin_usage_details_summary: "Historique détaillé des partitions du jour (tokens & coûts)",
      admin_usage_table_caption:
        "Détail de la consommation de tokens et des coûts par partition analysée aujourd'hui",
      admin_th_sheet: "Partition",
      admin_th_time_model: "Heure & Modèle",
      admin_th_in_out_think: "Entrée / Sortie / Think",
      admin_th_total_tokens: "Total Tokens",
      admin_th_cost: "Coût ($ / €)",
      admin_no_analysis_today: "Aucune analyse aujourd'hui",
      admin_digest_hint:
        "Récapitulatif quotidien automatique envoyé à 18h00 (si des PDFs ont été analysés).",
      admin_btn_send_digest: "Envoyer le récapitulatif du jour maintenant",
      admin_btn_resume_deferred: "Relancer les partitions reportées (Quota J+1)",
      admin_btn_reset_quota: "Remettre à zéro le quota du jour (0 / 25)",

      card2_heading: "2. Importer une partition PDF",
      upload_label: "Sélectionnez ou glissez-déposez un fichier PDF",
      required_badge: "(Requis)",
      upload_hint:
        "Importez une ou plusieurs partitions PDF pour obtenir la version annotée avec accords, contrepoint et walking bass.",
      upload_drop_title: "Choisir un PDF ou glisser-déposer ici",
      upload_drop_selected: "{count} fichier(s) sélectionné(s) : {names}",
      upload_drop_sub: "Partitions classiques, tablatures guitare et lead sheets (.pdf)",
      upload_error_msg: "Veuillez sélectionner au moins un fichier PDF.",
      upload_submit_btn: "Annoter la partition PDF",

      card3_heading: "3. Scanner un dossier Google Drive",
      drive_badge_public: "Public / Non connecté",
      drive_badge_connected: "Connecté OAuth",
      drive_oauth_callout_html:
        "Pour analyser un <strong>dossier Google Drive privé</strong> (ou activer le mode administrateur), connectez votre compte Google.",
      drive_oauth_login_btn: "🔐 Se connecter avec Google",
      drive_folder_label: "URL ou ID du dossier Google Drive",
      drive_browse_btn: "Parcourir mon Google Drive…",
      drive_folder_hint_html:
        "Naviguez dans votre Google Drive ou collez l'URL d'un dossier (<code>https://drive.google.com/drive/folders/...</code>).",
      drive_folder_error: "Veuillez saisir ou sélectionner un dossier Google Drive.",
      drive_reupload_label: "Ré-envoyer les PDFs annotés dans le dossier Google Drive",
      drive_scan_btn: "Scanner le dossier",
      drive_submit_btn: "Analyser les PDFs du dossier",
      drive_discovered_heading: "PDFs détectés dans le dossier",
      drive_discovered_empty:
        "Aucun PDF trouvé (s'il s'agit d'un dossier privé, cliquez sur « Se connecter avec Google »).",

      results_heading: "Partitions annotées & Analyse harmonique",
      status_ready: "Prêt — importez un PDF ou scannez un dossier Google Drive.",
      progress_processing: "Traitement en cours…",
      progress_cancel_btn: "Interrompre l'analyse",
      progress_initializing: "Initialisation…",
      progress_steps_aria: "Étapes du traitement",
      step_1_download: "1. Lecture PDF",
      step_2_layout: "2. Détection des portées",
      step_3_harmony: "3. Analyse harmonique",
      step_4_annotate: "4. Annotation PDF",

      job_counter_done: "Terminées :",
      job_counter_queued: "En file aujourd'hui :",
      job_counter_deferred: "Reportées (quota 25/j) :",
      btn_collapse_all: "Tout replier",
      btn_expand_all: "Tout déplier",
      btn_download_zip: "Tout télécharger (.zip)",

      empty_state_intro:
        "Vos partitions annotées s'afficheront ici au fur et à mesure de leur génération avec :",
      empty_bullet_1_html:
        "<strong>Mode Analyse :</strong> Revue des accords existants, précision (%) et corrections en place.",
      empty_bullet_2_html:
        "<strong>Mode Ajout d'accords :</strong> Génération automatique des accords et diagrammes de manche 6 cordes.",
      empty_bullet_3_html:
        "<strong>Contrepoint &amp; Walking Bass :</strong> Propositions de basses inversées évitant le doublage de la mélodie et l'usage systématique de la fondamentale.",

      drive_modal_title: "Sélectionner un dossier Google Drive",
      drive_modal_sub:
        "Naviguez dans vos dossiers pour choisir où se trouvent vos partitions PDF.",
      drive_modal_close_aria: "Fermer l'explorateur Google Drive",
      drive_source_aria: "Source Google Drive",
      drive_tab_my_drive: "Mon Drive",
      drive_tab_shared: "Partagés avec moi",
      drive_search_label: "Rechercher un dossier",
      drive_search_placeholder: "Rechercher un dossier par nom…",
      drive_search_btn: "Rechercher",
      drive_breadcrumbs_aria: "Fil d'Ariane Google Drive",
      drive_subfolders_aria: "Sous-dossiers",
      drive_current_folder_label: "Dossier courant :",
      btn_cancel: "Annuler",
      drive_select_this_folder_btn: "✓ Choisir ce dossier",
      drive_choose_btn: "Choisir",
      drive_empty_subfolders: "Aucun sous-dossier dans cet emplacement.",
      drive_pdfs_detected_in:
        "📄 {count} partition(s) PDF détectée(s) dans « {folder} » :",
      drive_loading_folders: "Chargement des dossiers Google Drive…",
      drive_select_specific_folder_err: "Veuillez ouvrir ou sélectionner un dossier spécifique.",
      drive_folder_selected_scanning:
        "Dossier Google Drive sélectionné : « {folder} ». Scan en cours…",
      drive_browse_error: "Impossible de parcourir Google Drive.",

      pdf_preview_title: "Aperçu de la partition PDF",
      pdf_preview_sub: "Comparaison entre la partition originale et la partition annotée.",
      pdf_preview_download_btn: "⬇ Télécharger le PDF annoté",
      pdf_preview_close_aria: "Fermer l'aperçu PDF",
      pdf_preview_close_btn: "✕ Fermer",
      pdf_preview_orig_label: "Partition originale",
      pdf_preview_orig_label_file: "Partition originale ({file})",
      pdf_preview_annot_label: "Partition annotée",
      pdf_preview_annot_label_file: "Partition annotée ({file})",
      pdf_preview_orig_iframe_title: "Aperçu PDF original",
      pdf_preview_annot_iframe_title: "Aperçu PDF annoté",

      // Report cards & Bass proposals
      bass_tag_walking: "Walking Bass",
      bass_tag_counterpoint: "Contrepoint",
      bass_measure_label: "Mesure {measure}",
      bass_melody_label: "Mélodie : {note}",
      bass_box_title:
        "🎸 Propositions de basses — Contrepoint & Walking Bass (anti-fondamentale / anti-doublage)",
      badge_error: "Erreur",
      badge_analyze_accuracy: "Analyse des accords ({score}% exacts)",
      badge_add_chords: "Accords & Basses ajoutés",
      admin_card_usage_aria: "Consommation de tokens et coût (Administrateur)",
      admin_card_tokens_label: "📊 Tokens (Admin) :",
      admin_card_in_out: "Entrée : {in} • Sortie : {out}",
      admin_card_cost_label: "Coût estimé :",
      admin_card_model_label: "Modèle :",
      btn_preview_pdf: "👁 Prévisualiser le PDF",
      btn_download_annotated_pdf: "⬇ Télécharger le PDF annoté ({file})",
      btn_open_original: "Ouvrir l'original",
      card_toggle_title: "Cliquer pour replier ou déplier cette partition",
      meta_file: "Fichier : {file}",
      meta_key: "Tonalité : {key}",
      meta_annotations: "Annotations : {count}",
      meta_lang: "Langue : {lang}",

      // Job item badges & messages
      badge_queued: "⏳ En file d'attente",
      badge_processing: "⚙️ Analyse en cours ({percent}%)",
      badge_deferred: "📅 Planifié le {date} (Quota 25/j)",
      tomorrow_word: "demain",
      badge_cancelled: "⏹ Annulé",
      badge_error_icon: "❌ Erreur",
      item_waiting: "En attente de traitement…",

      // Dynamic status & progress messages
      server_error_fmt: "Erreur serveur ({status}) : {detail}",
      service_unavailable: "Service indisponible",
      status_oauth_error: "Erreur OAuth : {error}",
      status_digest_sent_url:
        "✅ Récapitulatif quotidien envoyé par e-mail à alexis.mp@gmail.com !",
      status_digest_error_url: "Erreur lors de l'envoi du récapitulatif : {error}",
      status_cancelling: "⏹ Interruption de l'analyse en cours…",
      status_resuming_deferred: "Reprise des partitions reportées (quota quotidien)…",
      status_resumed_count:
        "▶️ {count} partition(s) reportée(s) relancée(s) pour traitement.",
      status_no_deferred_today: "Aucune partition reportée à relancer aujourd'hui.",
      status_resetting_quota: "Remise à zéro du quota quotidien en cours…",
      status_quota_reset_with_resume:
        "✅ Quota quotidien remis à zéro (0 / {limit} PDF) — ▶️ {count} partition(s) reportée(s) relancée(s) immédiatement !",
      status_quota_reset_simple: "✅ Quota quotidien remis à zéro (0 / {limit} PDF).",
      status_sending_digest: "Envoi du récapitulatif quotidien en cours…",
      status_digest_sent_ok:
        "✅ Récapitulatif quotidien envoyé à {recipient} ({count} partition(s)).",
      status_gmail_reauth:
        "Autorisation d'envoi Gmail requise — redirection vers Google pour valider l'envoi…",
      status_no_digest_sent: "Aucun envoi effectué.",
      status_logged_out: "Déconnecté de Google Drive.",
      job_progress_running: "Partition {index} / {total} : {file}",
      job_progress_partially_deferred:
        "Lot du jour terminé ({completed} / {total}) • {deferred} planifiée(s) pour demain",
      job_progress_cancelled:
        "⏹ Analyse interrompue ({completed} / {total} terminée(s))",
      job_progress_completed: "Traitement terminé ({completed} / {total} partition(s))",
      stream_failed: "Échec du traitement.",
      stream_file_label: "Fichier {index} / {total} : {file}",
      stream_file_starting: "Démarrage de {file}…",
      stream_file_done_label: "Fichier {index} / {total} terminé : {file}",
      stream_file_done_msg: "Terminé : {file}",
      stream_cancelled_label: "⏹ Analyse interrompue ({count} partition(s) traitée(s))",
      stream_cancelled_msg: "Analyse interrompue à la demande de l'utilisateur.",
      stream_quota_label:
        "⚠️ Limite quotidienne atteinte ({count} partition(s) traitée(s))",
      stream_quota_msg: "Limite quotidienne de 25 fichiers atteinte.",
      stream_batch_done_label: "Traitement terminé ({count} partition(s))",
      stream_batch_done_msg: "Toutes les partitions ont été annotées avec succès.",
      stream_interrupted_label:
        "⚠️ Connexion interrompue après {count} partition(s)",
      stream_interrupted_msg: "Le flux serveur s'est interrompu prématurément.",
      stream_interrupted_status:
        "Flux interrompu après {count} partition(s) traitée(s).",
      stream_final_status: "Terminé : {count} partition(s) PDF annotée(s).",
      upload_progress_sending: "Envoi de {count} fichier(s) PDF…",
      upload_progress_queueing: "Création de la file d'attente asynchrone…",
      upload_status_submitting: "Soumission du lot de {count} fichier(s) PDF…",
      upload_job_error: "Échec de la création du lot d'analyse.",
      scan_status_searching:
        "Recherche des partitions PDF dans le dossier Google Drive…",
      scan_error: "Échec du scan du dossier.",
      scan_status_found: "{count} fichier(s) PDF trouvé(s) dans le dossier.",
      drive_progress_scheduling: "Planification du dossier Google Drive…",
      drive_progress_discovering:
        "Découverte des partitions PDF et mise en file d'attente d'événements…",
      drive_status_creating_job:
        "Création du job d'analyse asynchrone pour le dossier Google Drive…",
      drive_job_error: "Échec de la planification du dossier Google Drive.",
    },
    en: {
      doc_title: "Akkord — Harmonic Analysis, Counterpoint & Walking Bass",
      header_eyebrow: "Music Harmony & Counterpoint Studio",
      header_subtitle_html:
        "Upload a PDF sheet music score or connect a Google Drive folder. Akkord verifies or generates the chord chart, proposes <strong>counterpoint &amp; walking bass lines</strong>, and produces an annotated PDF in French or English.",
      ui_lang_switcher_aria: "Interface language",
      quota_badge_title: "Daily limit of 25 PDF scores per day",
      quota_badge_text: "Quota: {used} / {limit} PDF",
      header_login_btn: "🔐 Sign in with Google Drive",
      header_admin_badge: "Administrator",
      header_logout_btn: "Sign out",
      auth_google_prefix: "Google: {email}",

      card1_heading: "1. Annotated PDF & UI Language",
      card1_legend: "Annotated PDF & UI Language",
      lang_fr_title: "Français (FR)",
      lang_fr_desc:
        "Chord chart, French Solfège (Am / La m) & bass line proposals (counterpoint / walking bass)",
      lang_en_title: "English (EN)",
      lang_en_desc:
        "Standard chord symbols (Am, Dm/F, G/B) & counterpoint / walking-bass review",

      admin_menu_summary: "Advanced Menu (Model, Token & Cost Tracking, Actions)",
      admin_model_label: "Harmonic Analysis Model",
      admin_badge_paren: "(Admin)",
      admin_model_hint_html: "Restricted to administrator (<code>alexis.mp@gmail.com</code>).",
      admin_usage_heading: "Token Usage & Estimated Costs (Admin)",
      admin_kpi_today_tokens: "Today (Tokens)",
      admin_kpi_today_cost: "Today (Estimated Cost)",
      admin_kpi_cum_cost: "All-Time Total (Tokens & Cost)",
      admin_today_files_count: "{count} score(s) today",
      admin_cum_tokens_sub: "{tokens} tok total ({files} files)",
      admin_usage_details_summary: "Detailed history of today's scores (tokens & costs)",
      admin_usage_table_caption:
        "Detailed token consumption and cost breakdown per score analyzed today",
      admin_th_sheet: "Score",
      admin_th_time_model: "Time & Model",
      admin_th_in_out_think: "Input / Output / Think",
      admin_th_total_tokens: "Total Tokens",
      admin_th_cost: "Cost ($ / €)",
      admin_no_analysis_today: "No analysis today",
      admin_digest_hint:
        "Automatic daily summary sent at 6:00 PM (if PDFs were analyzed).",
      admin_btn_send_digest: "Send today's summary email now",
      admin_btn_resume_deferred: "Resume deferred scores (Next-day quota)",
      admin_btn_reset_quota: "Reset today's quota (0 / 25)",

      card2_heading: "2. Upload a PDF Score",
      upload_label: "Select or drag and drop a PDF file",
      required_badge: "(Required)",
      upload_hint:
        "Upload one or more PDF sheet music files to generate an annotated version with chords, counterpoint, and walking bass.",
      upload_drop_title: "Choose a PDF or drag & drop here",
      upload_drop_selected: "{count} file(s) selected: {names}",
      upload_drop_sub: "Classical scores, guitar tabs, and lead sheets (.pdf)",
      upload_error_msg: "Please select at least one PDF file.",
      upload_submit_btn: "Annotate PDF Score",

      card3_heading: "3. Scan a Google Drive Folder",
      drive_badge_public: "Public / Signed Out",
      drive_badge_connected: "OAuth Connected",
      drive_oauth_callout_html:
        "To analyze a <strong>private Google Drive folder</strong> (or enable administrator mode), sign in with your Google account.",
      drive_oauth_login_btn: "🔐 Sign in with Google",
      drive_folder_label: "Google Drive Folder URL or ID",
      drive_browse_btn: "Browse my Google Drive…",
      drive_folder_hint_html:
        "Browse your Google Drive or paste a folder URL (<code>https://drive.google.com/drive/folders/...</code>).",
      drive_folder_error: "Please enter or select a Google Drive folder.",
      drive_reupload_label: "Re-upload annotated PDFs back to the Google Drive folder",
      drive_scan_btn: "Scan Folder",
      drive_submit_btn: "Analyze Folder PDFs",
      drive_discovered_heading: "PDFs detected in folder",
      drive_discovered_empty:
        "No PDFs found (if this is a private folder, click 'Sign in with Google').",

      results_heading: "Annotated Scores & Harmonic Analysis",
      status_ready: "Ready — upload a PDF or scan a Google Drive folder.",
      progress_processing: "Processing…",
      progress_cancel_btn: "Cancel Analysis",
      progress_initializing: "Initializing…",
      progress_steps_aria: "Processing steps",
      step_1_download: "1. PDF Reading",
      step_2_layout: "2. Staff Detection",
      step_3_harmony: "3. Harmonic Analysis",
      step_4_annotate: "4. PDF Annotation",

      job_counter_done: "Completed:",
      job_counter_queued: "Queued today:",
      job_counter_deferred: "Deferred (25/day quota):",
      btn_collapse_all: "Collapse all",
      btn_expand_all: "Expand all",
      btn_download_zip: "Download all (.zip)",

      empty_state_intro:
        "Your annotated scores will appear here as they are generated, featuring:",
      empty_bullet_1_html:
        "<strong>Analysis Mode:</strong> Review of existing chords, accuracy score (%), and in-place corrections.",
      empty_bullet_2_html:
        "<strong>Chord Addition Mode:</strong> Automatic chord generation and 6-string fretboard diagrams.",
      empty_bullet_3_html:
        "<strong>Counterpoint &amp; Walking Bass:</strong> Inverted slash-bass proposals avoiding melody doubling and root-heavy monotony.",

      drive_modal_title: "Select a Google Drive Folder",
      drive_modal_sub:
        "Browse your folders to choose where your PDF sheet music is stored.",
      drive_modal_close_aria: "Close Google Drive browser",
      drive_source_aria: "Google Drive Source",
      drive_tab_my_drive: "My Drive",
      drive_tab_shared: "Shared with me",
      drive_search_label: "Search for a folder",
      drive_search_placeholder: "Search folder by name…",
      drive_search_btn: "Search",
      drive_breadcrumbs_aria: "Google Drive Breadcrumbs",
      drive_subfolders_aria: "Subfolders",
      drive_current_folder_label: "Current folder:",
      btn_cancel: "Cancel",
      drive_select_this_folder_btn: "✓ Select this folder",
      drive_choose_btn: "Choose",
      drive_empty_subfolders: "No subfolders in this location.",
      drive_pdfs_detected_in:
        "📄 {count} PDF score(s) detected in “{folder}”:",
      drive_loading_folders: "Loading Google Drive folders…",
      drive_select_specific_folder_err: "Please open or select a specific folder.",
      drive_folder_selected_scanning:
        "Google Drive folder selected: “{folder}”. Scanning…",
      drive_browse_error: "Unable to browse Google Drive.",

      pdf_preview_title: "PDF Score Preview",
      pdf_preview_sub: "Side-by-side comparison of the original score and annotated score.",
      pdf_preview_download_btn: "⬇ Download Annotated PDF",
      pdf_preview_close_aria: "Close PDF preview",
      pdf_preview_close_btn: "✕ Close",
      pdf_preview_orig_label: "Original Score",
      pdf_preview_orig_label_file: "Original Score ({file})",
      pdf_preview_annot_label: "Annotated Score",
      pdf_preview_annot_label_file: "Annotated Score ({file})",
      pdf_preview_orig_iframe_title: "Original PDF preview",
      pdf_preview_annot_iframe_title: "Annotated PDF preview",

      // Report cards & Bass proposals
      bass_tag_walking: "Walking Bass",
      bass_tag_counterpoint: "Counterpoint",
      bass_measure_label: "Measure {measure}",
      bass_melody_label: "Melody: {note}",
      bass_box_title:
        "🎸 Bass Line Proposals — Counterpoint & Walking Bass (anti-root / anti-doubling)",
      badge_error: "Error",
      badge_analyze_accuracy: "Chord Analysis ({score}% accurate)",
      badge_add_chords: "Chords & Bass Added",
      admin_card_usage_aria: "Token consumption and cost (Administrator)",
      admin_card_tokens_label: "📊 Tokens (Admin):",
      admin_card_in_out: "In: {in} • Out: {out}",
      admin_card_cost_label: "Estimated cost:",
      admin_card_model_label: "Model:",
      btn_preview_pdf: "👁 Preview PDF",
      btn_download_annotated_pdf: "⬇ Download Annotated PDF ({file})",
      btn_open_original: "Open Original",
      card_toggle_title: "Click to collapse or expand this score",
      meta_file: "File: {file}",
      meta_key: "Key: {key}",
      meta_annotations: "Annotations: {count}",
      meta_lang: "Language: {lang}",

      // Job item badges & messages
      badge_queued: "⏳ Queued",
      badge_processing: "⚙️ Analyzing ({percent}%)",
      badge_deferred: "📅 Scheduled for {date} (25/day quota)",
      tomorrow_word: "tomorrow",
      badge_cancelled: "⏹ Cancelled",
      badge_error_icon: "❌ Error",
      item_waiting: "Waiting to be processed…",

      // Dynamic status & progress messages
      server_error_fmt: "Server error ({status}): {detail}",
      service_unavailable: "Service unavailable",
      status_oauth_error: "OAuth Error: {error}",
      status_digest_sent_url:
        "✅ Daily summary emailed to alexis.mp@gmail.com!",
      status_digest_error_url: "Error sending daily summary: {error}",
      status_cancelling: "⏹ Cancelling current analysis…",
      status_resuming_deferred: "Resuming deferred scores (daily quota)…",
      status_resumed_count:
        "▶️ {count} deferred score(s) requeued for processing.",
      status_no_deferred_today: "No deferred scores to resume today.",
      status_resetting_quota: "Resetting daily quota…",
      status_quota_reset_with_resume:
        "✅ Daily quota reset (0 / {limit} PDF) — ▶️ {count} deferred score(s) resumed immediately!",
      status_quota_reset_simple: "✅ Daily quota reset (0 / {limit} PDF).",
      status_sending_digest: "Sending daily summary email…",
      status_digest_sent_ok:
        "✅ Daily summary sent to {recipient} ({count} score(s)).",
      status_gmail_reauth:
        "Gmail send authorization required — redirecting to Google…",
      status_no_digest_sent: "No email was sent.",
      status_logged_out: "Signed out of Google Drive.",
      job_progress_running: "Score {index} / {total}: {file}",
      job_progress_partially_deferred:
        "Today's batch completed ({completed} / {total}) • {deferred} scheduled for tomorrow",
      job_progress_cancelled:
        "⏹ Analysis cancelled ({completed} / {total} completed)",
      job_progress_completed: "Processing complete ({completed} / {total} score(s))",
      stream_failed: "Processing failed.",
      stream_file_label: "File {index} / {total}: {file}",
      stream_file_starting: "Starting {file}…",
      stream_file_done_label: "File {index} / {total} completed: {file}",
      stream_file_done_msg: "Completed: {file}",
      stream_cancelled_label: "⏹ Analysis cancelled ({count} score(s) processed)",
      stream_cancelled_msg: "Analysis cancelled at user's request.",
      stream_quota_label:
        "⚠️ Daily limit reached ({count} score(s) processed)",
      stream_quota_msg: "Daily limit of 25 files reached.",
      stream_batch_done_label: "Processing complete ({count} score(s))",
      stream_batch_done_msg: "All scores have been annotated successfully.",
      stream_interrupted_label:
        "⚠️ Connection interrupted after {count} score(s)",
      stream_interrupted_msg: "The server stream ended prematurely.",
      stream_interrupted_status:
        "Stream interrupted after {count} processed score(s).",
      stream_final_status: "Completed: {count} PDF score(s) annotated.",
      upload_progress_sending: "Uploading {count} PDF file(s)…",
      upload_progress_queueing: "Creating asynchronous batch queue…",
      upload_status_submitting: "Submitting batch of {count} PDF file(s)…",
      upload_job_error: "Failed to create analysis batch.",
      scan_status_searching:
        "Searching for PDF scores in Google Drive folder…",
      scan_error: "Failed to scan folder.",
      scan_status_found: "{count} PDF file(s) found in folder.",
      drive_progress_scheduling: "Scheduling Google Drive folder…",
      drive_progress_discovering:
        "Discovering PDF scores and queueing batch events…",
      drive_status_creating_job:
        "Creating asynchronous analysis job for Google Drive folder…",
      drive_job_error: "Failed to schedule Google Drive folder.",
    },
  };

  let currentLang = (() => {
    const saved = localStorage.getItem("akkord_ui_lang");
    if (saved === "en" || saved === "fr") return saved;
    const nav = (navigator.language || "").toLowerCase();
    return nav.startsWith("en") ? "en" : "fr";
  })();

  function t(key, vars = {}) {
    const dict = I18N[currentLang] || I18N.fr;
    let str = dict[key] !== undefined ? dict[key] : I18N.fr[key] || key;
    Object.keys(vars).forEach((k) => {
      str = str.replaceAll(`{${k}}`, String(vars[k]));
    });
    return str;
  }

  const uploadForm = document.getElementById("upload-form");
  const pdfFileInput = document.getElementById("pdf-file-input");
  const selectedFileLabel = document.getElementById("selected-file-label");
  const dropZone = document.getElementById("drop-zone");
  const uploadSubmitBtn = document.getElementById("upload-submit-btn");

  const driveForm = document.getElementById("drive-form");
  const folderInput = document.getElementById("folder-input");
  const modelInput = document.getElementById("model-input");
  const adminModelPanel = document.getElementById("admin-model-panel");
  const scanBtn = document.getElementById("scan-btn");
  const driveSubmitBtn = document.getElementById("drive-submit-btn");
  const statusBanner = document.getElementById("status-banner");
  const emptyState = document.getElementById("empty-state");
  const resultsList = document.getElementById("results-list");
  const discoveredContainer = document.getElementById("discovered-container");
  const discoveredList = document.getElementById("discovered-list");

  // Header language switcher buttons & radio buttons
  const uiLangFrBtn = document.getElementById("ui-lang-fr-btn");
  const uiLangEnBtn = document.getElementById("ui-lang-en-btn");
  const radioLangFr = document.getElementById("lang-fr");
  const radioLangEn = document.getElementById("lang-en");

  // Auth UI elements
  const authLoggedOut = document.getElementById("auth-logged-out");
  const authLoggedIn = document.getElementById("auth-logged-in");
  const authUserEmail = document.getElementById("auth-user-email");
  const authAdminBadge = document.getElementById("auth-admin-badge");
  const logoutBtn = document.getElementById("logout-btn");
  const driveOauthBadge = document.getElementById("drive-oauth-badge");
  const driveOauthCallout = document.getElementById("drive-oauth-callout");

  // Google Drive Folder Browser Modal elements
  const browseDriveBtn = document.getElementById("browse-drive-btn");
  const driveBrowserDialog = document.getElementById("drive-browser-dialog");
  const driveTabRoot = document.getElementById("drive-tab-root");
  const driveTabShared = document.getElementById("drive-tab-shared");
  const driveFolderSearch = document.getElementById("drive-folder-search");
  const driveSearchBtn = document.getElementById("drive-search-btn");
  const driveBreadcrumbs = document.getElementById("drive-breadcrumbs");
  const driveBrowserStatus = document.getElementById("drive-browser-status");
  const driveFolderList = document.getElementById("drive-folder-list");
  const drivePdfPreview = document.getElementById("drive-pdf-preview");
  const drivePdfCountLabel = document.getElementById("drive-pdf-count-label");
  const drivePdfNames = document.getElementById("drive-pdf-names");
  const driveCurrentFolderName = document.getElementById("drive-current-folder-name");
  const driveSelectCurrentBtn = document.getElementById("drive-select-current-btn");

  // Real-time Progress Panel elements
  const progressPanel = document.getElementById("progress-panel");
  const progressFileLabel = document.getElementById("progress-file-label");
  const progressPercentLabel = document.getElementById("progress-percent-label");
  const progressBarRole = document.getElementById("progress-bar-role");
  const progressBarFill = document.getElementById("progress-bar-fill");
  const progressStepMessage = document.getElementById("progress-step-message");
  const cancelAnalysisBtn = document.getElementById("cancel-analysis-btn");
  const dailyQuotaBadge = document.getElementById("daily-quota-badge");
  const sendDigestBtn = document.getElementById("send-digest-btn");
  const resumeDeferredBtn = document.getElementById("resume-deferred-btn");
  const resetQuotaBtn = document.getElementById("reset-quota-btn");

  // Batch Job Summary & ZIP Download elements
  const jobSummaryBar = document.getElementById("job-summary-bar");
  const jobCountCompleted = document.getElementById("job-count-completed");
  const jobCountQueued = document.getElementById("job-count-queued");
  const jobCounterDeferredWrap = document.getElementById("job-counter-deferred-wrap");
  const jobCountDeferred = document.getElementById("job-count-deferred");
  const jobDownloadZipBtn = document.getElementById("job-download-zip-btn");
  const toggleAllCardsBtn = document.getElementById("toggle-all-cards-btn");

  // Single Shared On-Demand PDF Preview Dialog elements
  const pdfPreviewDialog = document.getElementById("pdf-preview-dialog");
  const pdfPreviewDialogTitle = document.getElementById("pdf-preview-dialog-title");
  const pdfPreviewDialogSub = document.getElementById("pdf-preview-dialog-sub");
  const pdfPreviewDownloadBtn = document.getElementById("pdf-preview-download-btn");
  const pdfPreviewGrid = document.getElementById("pdf-preview-grid");
  const pdfPreviewOrigPane = document.getElementById("pdf-preview-orig-pane");
  const pdfPreviewOrigLabel = document.getElementById("pdf-preview-orig-label");
  const pdfPreviewOrigIframe = document.getElementById("pdf-preview-orig-iframe");
  const pdfPreviewAnnotPane = document.getElementById("pdf-preview-annot-pane");
  const pdfPreviewAnnotLabel = document.getElementById("pdf-preview-annot-label");
  const pdfPreviewAnnotIframe = document.getElementById("pdf-preview-annot-iframe");

  // Admin Token & Cost Dashboard elements
  const usageTodayTokens = document.getElementById("usage-today-tokens");
  const usageTodayBreakdown = document.getElementById("usage-today-breakdown");
  const usageTodayCost = document.getElementById("usage-today-cost");
  const usageTodayFiles = document.getElementById("usage-today-files");
  const usageCumCost = document.getElementById("usage-cum-cost");
  const usageCumTokens = document.getElementById("usage-cum-tokens");
  const adminUsageTbody = document.getElementById("admin-usage-tbody");

  const stepItems = {
    download: document.getElementById("step-download"),
    layout: document.getElementById("step-layout"),
    harmony: document.getElementById("step-harmony"),
    annotate: document.getElementById("step-annotate"),
  };
  const stepOrder = ["download", "layout", "harmony", "annotate"];

  let currentAbortController = null;
  let activeJobId = null;
  let activeJobPollTimer = null;
  const renderedItemState = new Map();
  const cardDataStore = new WeakMap();
  let lastQuotaState = { used: 0, limit: 25 };
  let lastAdminUsageState = null;

  // Configure On-Demand PDF Preview Dialog (light-dismiss fallback + iframe memory cleanup on close)
  if (pdfPreviewDialog) {
    if (!("closedBy" in HTMLDialogElement.prototype)) {
      pdfPreviewDialog.addEventListener("click", (event) => {
        if (event.target !== pdfPreviewDialog) return;
        const rect = pdfPreviewDialog.getBoundingClientRect();
        const isDialogContent =
          rect.top <= event.clientY &&
          event.clientY <= rect.top + rect.height &&
          rect.left <= event.clientX &&
          event.clientX <= rect.left + rect.width;
        if (isDialogContent) return;
        pdfPreviewDialog.close();
      });
    }

    pdfPreviewDialog.addEventListener("close", () => {
      if (pdfPreviewOrigIframe) pdfPreviewOrigIframe.src = "about:blank";
      if (pdfPreviewAnnotIframe) pdfPreviewAnnotIframe.src = "about:blank";
    });
  }

  function openPdfPreviewModal({ title, sourceName, outputFilename, originalUrl, downloadUrl }) {
    if (!pdfPreviewDialog) return;
    if (pdfPreviewDialogTitle) {
      pdfPreviewDialogTitle.textContent = title || sourceName || t("pdf_preview_title");
    }
    if (pdfPreviewDialogSub) {
      pdfPreviewDialogSub.textContent = outputFilename
        ? `${sourceName} → ${outputFilename}`
        : sourceName || t("pdf_preview_sub");
    }
    if (pdfPreviewDownloadBtn) {
      if (downloadUrl) {
        pdfPreviewDownloadBtn.hidden = false;
        pdfPreviewDownloadBtn.href = downloadUrl;
        pdfPreviewDownloadBtn.setAttribute("download", outputFilename || "annotated-score.pdf");
      } else {
        pdfPreviewDownloadBtn.hidden = true;
      }
    }

    const hasOrig = Boolean(originalUrl);
    const hasAnnot = Boolean(downloadUrl);
    if (pdfPreviewGrid) {
      pdfPreviewGrid.className = hasOrig && hasAnnot ? "pdf-compare-grid two-col" : "pdf-compare-grid";
    }
    if (pdfPreviewOrigPane && pdfPreviewOrigIframe) {
      pdfPreviewOrigPane.hidden = !hasOrig;
      if (pdfPreviewOrigLabel) {
        pdfPreviewOrigLabel.textContent = t("pdf_preview_orig_label_file", {
          file: sourceName || "PDF",
        });
      }
      pdfPreviewOrigIframe.src = hasOrig ? originalUrl : "about:blank";
    }
    if (pdfPreviewAnnotPane && pdfPreviewAnnotIframe) {
      pdfPreviewAnnotPane.hidden = !hasAnnot;
      if (pdfPreviewAnnotLabel) {
        pdfPreviewAnnotLabel.textContent = t("pdf_preview_annot_label_file", {
          file: outputFilename || "PDF",
        });
      }
      pdfPreviewAnnotIframe.src = hasAnnot ? downloadUrl : "about:blank";
    }

    pdfPreviewDialog.showModal();
  }

  // Event delegation on resultsList for PDF preview buttons
  resultsList.addEventListener("click", (e) => {
    const btn = e.target.closest(".js-preview-pdf-btn");
    if (!btn) return;
    openPdfPreviewModal({
      title: btn.dataset.title || "",
      sourceName: btn.dataset.sourceName || "",
      outputFilename: btn.dataset.outputFilename || "",
      originalUrl: btn.dataset.originalUrl || "",
      downloadUrl: btn.dataset.downloadUrl || "",
    });
  });

  function formatInt(n) {
    return Number(n || 0).toLocaleString(currentLang === "en" ? "en-US" : "fr-FR");
  }

  function formatUsd(n) {
    return `$${Number(n || 0).toFixed(4)}`;
  }

  function formatEur(n) {
    return `${Number(n || 0).toFixed(4)} €`;
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function updateQuotaUI(quota) {
    if (quota) {
      lastQuotaState = quota;
    }
    if (!dailyQuotaBadge) return;
    const used = (lastQuotaState && lastQuotaState.used) || 0;
    const limit = (lastQuotaState && lastQuotaState.limit) || 25;
    dailyQuotaBadge.textContent = t("quota_badge_text", { used, limit });
  }

  function updateAdminUsageUI(usage) {
    if (usage) {
      lastAdminUsageState = usage;
    }
    if (!lastAdminUsageState) return;
    const today = lastAdminUsageState.today || {};
    const cum = lastAdminUsageState.cumulative || {};
    if (usageTodayTokens) {
      usageTodayTokens.textContent = `${formatInt(today.total_tokens)} tok`;
    }
    if (usageTodayBreakdown) {
      usageTodayBreakdown.textContent = `In: ${formatInt(today.input_tokens)} • Out: ${formatInt(today.output_tokens)} • Think: ${formatInt(today.thinking_tokens)}`;
    }
    if (usageTodayCost) {
      usageTodayCost.textContent = `${formatUsd(today.estimated_cost_usd)} / ${formatEur(today.estimated_cost_eur)}`;
    }
    if (usageTodayFiles) {
      usageTodayFiles.textContent = t("admin_today_files_count", {
        count: today.files_count || 0,
      });
    }
    if (usageCumCost) {
      usageCumCost.textContent = `${formatUsd(cum.estimated_cost_usd)} / ${formatEur(cum.estimated_cost_eur)}`;
    }
    if (usageCumTokens) {
      usageCumTokens.textContent = t("admin_cum_tokens_sub", {
        tokens: formatInt(cum.total_tokens),
        files: cum.files_count || 0,
      });
    }
    if (adminUsageTbody) {
      const entries = lastAdminUsageState.recent_entries || [];
      if (!entries.length) {
        adminUsageTbody.innerHTML = `
          <tr>
            <th scope="row">${escapeHtml(t("admin_no_analysis_today"))}</th>
            <td>—</td>
            <td>0 / 0 / 0</td>
            <td>0</td>
            <td>$0.0000 / 0.0000 €</td>
          </tr>
        `;
      } else {
        adminUsageTbody.innerHTML = entries
          .map(
            (e) => `
          <tr>
            <th scope="row">${escapeHtml(e.title || e.filename)}</th>
            <td>${escapeHtml(e.timestamp || "")} • <code>${escapeHtml(e.model || "")}</code></td>
            <td>${formatInt(e.input_tokens)} / ${formatInt(e.output_tokens)} / ${formatInt(e.thinking_tokens)}</td>
            <td><strong>${formatInt(e.total_tokens)} tok</strong></td>
            <td><strong>${formatUsd(e.estimated_cost_usd)}</strong> / ${formatEur(e.estimated_cost_eur)}</td>
          </tr>
        `
          )
          .join("");
      }
    }
  }

  let currentAuth = {
    authenticated: false,
    email: "",
    is_admin: false,
    oauth_configured: false,
    redirect_uri: `${window.location.origin}/auth/callback`,
  };

  function getSelectedLanguage() {
    const checked = document.querySelector('input[name="language"]:checked');
    return checked ? checked.value : currentLang;
  }

  function getSelectedModel() {
    if (!currentAuth.is_admin || !modelInput) {
      return "gemini-4-argon";
    }
    return (modelInput.value || "").trim() || "gemini-4-argon";
  }

  let hasCustomStatusMessage = false;

  function setStatus(message, isError = false) {
    hasCustomStatusMessage = true;
    statusBanner.textContent = message;
    statusBanner.classList.toggle("error", isError);
  }

  async function parseJsonResponse(resp) {
    const contentType = resp.headers.get("content-type") || "";
    const rawText = await resp.text();
    if (contentType.includes("application/json")) {
      try {
        return JSON.parse(rawText);
      } catch (_err) {
        // fall through
      }
    }
    const cleanText = rawText.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    throw new Error(
      t("server_error_fmt", {
        status: resp.status,
        detail: cleanText.slice(0, 180) || resp.statusText || t("service_unavailable"),
      })
    );
  }

  function updateAuthUI(auth) {
    if (auth) {
      currentAuth = { ...currentAuth, ...auth };
    }

    if (currentAuth.authenticated) {
      authLoggedOut.hidden = true;
      authLoggedIn.hidden = false;
      authUserEmail.textContent = t("auth_google_prefix", { email: currentAuth.email });
      authAdminBadge.hidden = !currentAuth.is_admin;
      adminModelPanel.hidden = !currentAuth.is_admin;

      if (driveOauthBadge) {
        driveOauthBadge.textContent = t("drive_badge_connected");
        driveOauthBadge.className = "mode-badge mode-analyze";
      }
      if (driveOauthCallout) {
        driveOauthCallout.hidden = true;
      }
    } else {
      authLoggedOut.hidden = false;
      authLoggedIn.hidden = true;
      authAdminBadge.hidden = true;
      adminModelPanel.hidden = true;

      if (driveOauthBadge) {
        driveOauthBadge.textContent = t("drive_badge_public");
        driveOauthBadge.className = "mode-badge mode-skip";
      }
      if (driveOauthCallout) {
        driveOauthCallout.hidden = false;
      }
    }
  }

  function updateSelectedFilesLabel() {
    if (!pdfFileInput || !selectedFileLabel) return;
    const files = pdfFileInput.files;
    if (files && files.length > 0) {
      const names = Array.from(files)
        .map((f) => f.name)
        .join(", ");
      selectedFileLabel.textContent = t("upload_drop_selected", {
        count: files.length,
        names,
      });
    } else {
      selectedFileLabel.textContent = t("upload_drop_title");
    }
  }

  function refreshToggleAllCardsButtonLabel() {
    if (!toggleAllCardsBtn) return;
    const allDetails = Array.from(resultsList.querySelectorAll(".report-details"));
    const anyOpen = allDetails.length === 0 || allDetails.some((d) => d.open);
    toggleAllCardsBtn.innerHTML = `<span aria-hidden="true">↕</span> ${escapeHtml(
      anyOpen ? t("btn_collapse_all") : t("btn_expand_all")
    )}`;
  }

  function rerenderExistingResultCards() {
    const stack = resultsList.querySelector(".reports-stack");
    if (!stack) return;
    const articles = Array.from(stack.querySelectorAll("article.report-item"));
    articles.forEach((articleEl, idx) => {
      const meta = cardDataStore.get(articleEl);
      if (!meta) return;
      const prevDetails = articleEl.querySelector(".report-details");
      const wasOpen = prevDetails ? prevDetails.open : false;
      const itemId = articleEl.dataset.itemId;
      let newEl = null;
      if (meta.kind === "report") {
        newEl = createReportElement(meta.data, idx);
      } else if (meta.kind === "jobItem") {
        newEl = createJobItemCardElement(meta.data, idx);
      }
      if (newEl) {
        if (itemId) newEl.dataset.itemId = itemId;
        const nextDetails = newEl.querySelector(".report-details");
        if (nextDetails) nextDetails.open = wasOpen;
        articleEl.replaceWith(newEl);
      }
    });
    refreshToggleAllCardsButtonLabel();
  }

  function setUILanguage(lang, { syncRadio = true } = {}) {
    currentLang = lang === "en" ? "en" : "fr";
    localStorage.setItem("akkord_ui_lang", currentLang);
    document.documentElement.lang = currentLang;
    document.title = t("doc_title");

    if (uiLangFrBtn && uiLangEnBtn) {
      const isFr = currentLang === "fr";
      uiLangFrBtn.classList.toggle("active", isFr);
      uiLangFrBtn.setAttribute("aria-pressed", String(isFr));
      uiLangEnBtn.classList.toggle("active", !isFr);
      uiLangEnBtn.setAttribute("aria-pressed", String(!isFr));
    }

    if (syncRadio) {
      if (currentLang === "fr" && radioLangFr) radioLangFr.checked = true;
      if (currentLang === "en" && radioLangEn) radioLangEn.checked = true;
    }

    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (!key) return;
      if (el === statusBanner && hasCustomStatusMessage) return;
      if (el === selectedFileLabel && pdfFileInput && pdfFileInput.files && pdfFileInput.files.length > 0) {
        return;
      }
      el.textContent = t(key);
    });

    document.querySelectorAll("[data-i18n-html]").forEach((el) => {
      const key = el.getAttribute("data-i18n-html");
      if (key) el.innerHTML = t(key);
    });

    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      const key = el.getAttribute("data-i18n-placeholder");
      if (key) el.setAttribute("placeholder", t(key));
    });

    document.querySelectorAll("[data-i18n-title]").forEach((el) => {
      const key = el.getAttribute("data-i18n-title");
      if (key) el.setAttribute("title", t(key));
    });

    document.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
      const key = el.getAttribute("data-i18n-aria-label");
      if (key) el.setAttribute("aria-label", t(key));
    });

    updateSelectedFilesLabel();
    updateQuotaUI();
    updateAuthUI();
    updateAdminUsageUI();
    rerenderExistingResultCards();
  }

  if (uiLangFrBtn) {
    uiLangFrBtn.addEventListener("click", () => setUILanguage("fr", { syncRadio: true }));
  }
  if (uiLangEnBtn) {
    uiLangEnBtn.addEventListener("click", () => setUILanguage("en", { syncRadio: true }));
  }
  if (radioLangFr) {
    radioLangFr.addEventListener("change", () => {
      if (radioLangFr.checked) setUILanguage("fr", { syncRadio: false });
    });
  }
  if (radioLangEn) {
    radioLangEn.addEventListener("change", () => {
      if (radioLangEn.checked) setUILanguage("en", { syncRadio: false });
    });
  }

  function showProgressPanel(fileLabel, percent, message, activeStage) {
    progressPanel.hidden = false;
    progressFileLabel.textContent = fileLabel;
    const clamped = Math.max(0, Math.min(100, Math.round(percent || 0)));
    progressPercentLabel.textContent = `${clamped}%`;
    progressBarRole.setAttribute("aria-valuenow", String(clamped));
    progressBarFill.style.width = `${clamped}%`;
    if (message) {
      progressStepMessage.textContent = message;
    }

    const activeIdx = stepOrder.indexOf(activeStage);
    stepOrder.forEach((stage, idx) => {
      const el = stepItems[stage];
      if (!el) return;
      el.classList.remove("active", "done");
      if (activeStage === "done" || (activeIdx !== -1 && idx < activeIdx)) {
        el.classList.add("done");
      } else if (idx === activeIdx) {
        el.classList.add("active");
      }
    });
  }

  function hideProgressPanel() {
    progressPanel.hidden = true;
  }

  // Apply initial language before fetching server config
  setUILanguage(currentLang, { syncRadio: true });

  // Load initial server config, auth status, and resume any active batch job
  fetch("/api/config")
    .then((r) => (r.ok ? r.json() : null))
    .then((cfg) => {
      if (!cfg) return;
      if (cfg.default_model && modelInput) {
        modelInput.value = cfg.default_model;
      }
      if (cfg.auth) {
        updateAuthUI(cfg.auth);
      }
      if (cfg.daily_quota) {
        updateQuotaUI(cfg.daily_quota);
      }
      if (cfg.admin_usage) {
        updateAdminUsageUI(cfg.admin_usage);
      }

      const params = new URLSearchParams(window.location.search);
      if (params.get("oauth_error")) {
        setStatus(t("status_oauth_error", { error: params.get("oauth_error") }), true);
        window.history.replaceState({}, "", "/");
      } else if (params.get("digest_sent") === "1") {
        setStatus(t("status_digest_sent_url"));
        window.history.replaceState({}, "", "/");
      } else if (params.get("digest_error")) {
        setStatus(t("status_digest_error_url", { error: params.get("digest_error") }), true);
        window.history.replaceState({}, "", "/");
      }

      fetch("/api/jobs")
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (!data) return;
          const jobs = data.jobs || [];
          const historyItems = data.history_items || [];
          const savedJobId = localStorage.getItem("akkord_active_job_id");
          const runningJob =
            jobs.find((j) => j.job_id === savedJobId && j.status === "running") ||
            jobs.find((j) => j.status === "running");

          if (runningJob) {
            resumeJobMonitoring(runningJob.job_id);
          } else if (jobs.length > 0 || historyItems.length > 0) {
            renderRestoredHistory(jobs, historyItems);
          }
        })
        .catch(() => {});
    })
    .catch(() => {});

  if (cancelAnalysisBtn) {
    cancelAnalysisBtn.addEventListener("click", async () => {
      cancelAnalysisBtn.disabled = true;
      setStatus(t("status_cancelling"));
      try {
        if (activeJobId) {
          const resp = await fetch(`/api/jobs/${encodeURIComponent(activeJobId)}/cancel`, {
            method: "POST",
          });
          if (resp.ok) {
            const jobData = await resp.json();
            renderBatchJobState(jobData);
          }
        } else {
          await fetch("/api/cancel", { method: "POST" });
        }
      } catch (_e) {}
      if (currentAbortController) {
        currentAbortController.abort();
      }
    });
  }

  if (resumeDeferredBtn) {
    resumeDeferredBtn.addEventListener("click", async () => {
      resumeDeferredBtn.disabled = true;
      setStatus(t("status_resuming_deferred"));
      try {
        const resp = await fetch("/api/internal/tasks/resume-deferred", { method: "POST" });
        const data = await parseJsonResponse(resp);
        if (data.resumed_count > 0) {
          setStatus(t("status_resumed_count", { count: data.resumed_count }));
          if (data.jobs_updated && data.jobs_updated.length > 0) {
            resumeJobMonitoring(data.jobs_updated[0]);
          }
        } else {
          setStatus(data.reason || t("status_no_deferred_today"));
        }
      } catch (err) {
        setStatus(err.message, true);
      } finally {
        resumeDeferredBtn.disabled = false;
      }
    });
  }

  if (resetQuotaBtn) {
    resetQuotaBtn.addEventListener("click", async () => {
      resetQuotaBtn.disabled = true;
      setStatus(t("status_resetting_quota"));
      try {
        const resp = await fetch("/api/admin/reset-quota", { method: "POST" });
        const data = await parseJsonResponse(resp);
        if (data.daily_quota) {
          updateQuotaUI(data.daily_quota);
        }
        if (data.admin_usage) {
          updateAdminUsageUI(data.admin_usage);
        }
        const limit = (data.daily_quota && data.daily_quota.limit) || 25;
        const resumedCount = (data.resumed && data.resumed.resumed_count) || 0;
        if (resumedCount > 0) {
          setStatus(
            t("status_quota_reset_with_resume", {
              limit,
              count: resumedCount,
            })
          );
          if (data.resumed.jobs_updated && data.resumed.jobs_updated.length > 0) {
            resumeJobMonitoring(data.resumed.jobs_updated[0]);
          }
        } else {
          setStatus(t("status_quota_reset_simple", { limit }));
        }
      } catch (err) {
        setStatus(err.message, true);
      } finally {
        resetQuotaBtn.disabled = false;
      }
    });
  }

  if (sendDigestBtn) {
    sendDigestBtn.addEventListener("click", async () => {
      sendDigestBtn.disabled = true;
      setStatus(t("status_sending_digest"));
      try {
        const resp = await fetch("/api/daily-report/send?force=true", { method: "POST" });
        const data = await parseJsonResponse(resp);
        if (data.sent) {
          setStatus(
            t("status_digest_sent_ok", {
              recipient: data.recipient,
              count: data.entries_count,
            })
          );
        } else if (data.needs_reauth && data.reauth_url) {
          setStatus(t("status_gmail_reauth"));
          window.location.href = data.reauth_url;
          return;
        } else {
          setStatus(
            data.reason || (data.errors && data.errors[0]) || t("status_no_digest_sent"),
            true
          );
        }
      } catch (err) {
        setStatus(err.message, true);
      } finally {
        sendDigestBtn.disabled = false;
      }
    });
  }

  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      await fetch("/api/auth/logout", { method: "POST" });
      updateAuthUI({ authenticated: false, email: "", is_admin: false });
      setStatus(t("status_logged_out"));
    });
  }

  // Update file input label on selection or drag-and-drop
  pdfFileInput.addEventListener("change", () => {
    updateSelectedFilesLabel();
  });

  ["dragenter", "dragover"].forEach((evtName) => {
    dropZone.addEventListener(evtName, (e) => {
      e.preventDefault();
      dropZone.classList.add("drag-over");
    });
  });

  ["dragleave", "drop"].forEach((evtName) => {
    dropZone.addEventListener(evtName, () => {
      dropZone.classList.remove("drag-over");
    });
  });

  function renderBassProposals(detail) {
    const proposals = (detail && detail.bass_line_proposals) || [];
    if (!proposals.length) {
      return "";
    }
    const itemsHtml = proposals
      .map((bp) => {
        const isWalking = bp.technique === "walking_bass";
        const badgeLabel = isWalking ? t("bass_tag_walking") : t("bass_tag_counterpoint");
        const badgeClass = isWalking ? "bass-tag-walking" : "bass-tag-counterpoint";
        const mLabel = bp.measure_number
          ? t("bass_measure_label", { measure: bp.measure_number })
          : "";
        const melodyInfo = bp.melody_note
          ? `<span class="bass-melody-note">${escapeHtml(
              t("bass_melody_label", { note: bp.melody_note })
            )}</span>`
          : "";
        return `
          <li class="bass-proposal-item">
            <div class="bass-proposal-top">
              <span class="bass-tag ${badgeClass}">${escapeHtml(badgeLabel)}</span>
              ${mLabel ? `<span class="bass-measure">${escapeHtml(mLabel)}</span>` : ""}
              <strong class="bass-chord-change">${escapeHtml(bp.original_chord)} → ${escapeHtml(
          bp.proposed_slash_chord
        )}</strong>
              ${melodyInfo}
            </div>
            <p class="bass-explanation">${escapeHtml(bp.explanation || "")}</p>
          </li>
        `;
      })
      .join("");

    return `
      <div class="bass-proposals-box">
        <h4 class="bass-proposals-title">${escapeHtml(t("bass_box_title"))}</h4>
        <ul class="bass-proposals-list">
          ${itemsHtml}
        </ul>
      </div>
    `;
  }

  function createReportElement(rep, cardIndex = 0) {
    const wrapper = document.createElement("div");
    const deferredClass = cardIndex >= 2 ? "report-item heavy-card-deferred" : "report-item";
    if (rep.mode === "error") {
      wrapper.innerHTML = `
        <article class="${deferredClass}">
          <details class="report-details" open>
            <summary class="report-header report-summary-toggle">
              <div class="report-header-left">
                <span class="report-chevron" aria-hidden="true">▾</span>
                <span class="report-title">${escapeHtml(rep.source_name)}</span>
              </div>
              <div class="report-header-right">
                <span class="badge" style="background:#fef2f2;color:#b91c1c;">${escapeHtml(
                  t("badge_error")
                )}</span>
              </div>
            </summary>
            <div class="report-body">
              <p class="report-summary">${escapeHtml(rep.error)}</p>
            </div>
          </details>
        </article>
      `;
      const el = wrapper.firstElementChild;
      if (el) cardDataStore.set(el, { kind: "report", data: rep });
      return el;
    }

    const isAnalyze = rep.mode === "analyze";
    const badgeClass = isAnalyze ? "badge-analyze" : "badge-add";
    const badgeText = isAnalyze
      ? t("badge_analyze_accuracy", { score: rep.accuracy_score })
      : t("badge_add_chords");

    const bassProposalsHtml = renderBassProposals(rep.analysis_detail);

    const tok = rep.token_usage || (rep.analysis_detail && rep.analysis_detail.token_usage) || null;
    const adminUsageBarHtml =
      currentAuth.is_admin && tok
        ? `
          <div class="admin-card-usage-bar" aria-label="${escapeHtml(t("admin_card_usage_aria"))}">
            <span><strong>${escapeHtml(t("admin_card_tokens_label"))}</strong> ${formatInt(
            tok.total_tokens
          )} tok</span>
            <span>(${escapeHtml(
              t("admin_card_in_out", {
                in: formatInt(tok.input_tokens),
                out: formatInt(tok.output_tokens),
              })
            )}${tok.thinking_tokens ? ` • Think: ${formatInt(tok.thinking_tokens)}` : ""})</span>
            <span>• <strong>${escapeHtml(t("admin_card_cost_label"))}</strong> ${formatUsd(
            tok.estimated_cost_usd
          )} / ${formatEur(tok.estimated_cost_eur)}</span>
            <span>• ${escapeHtml(t("admin_card_model_label"))} <code>${escapeHtml(
            tok.model || rep.model || "gemini-4-argon"
          )}</code></span>
          </div>
        `
        : "";

    const previewBtnHtml =
      rep.download_url || rep.original_url
        ? `<button
            type="button"
            class="btn btn-outline btn-sm js-preview-pdf-btn"
            data-title="${escapeHtml(rep.title || rep.source_name)}"
            data-source-name="${escapeHtml(rep.source_name)}"
            data-output-filename="${escapeHtml(rep.output_filename || "")}"
            data-original-url="${escapeHtml(rep.original_url || "")}"
            data-download-url="${escapeHtml(rep.download_url || "")}"
          >${escapeHtml(t("btn_preview_pdf"))}</button>`
        : "";

    wrapper.innerHTML = `
      <article class="${deferredClass}">
        <details class="report-details" open>
          <summary class="report-header report-summary-toggle" title="${escapeHtml(
            t("card_toggle_title")
          )}">
            <div class="report-header-left">
              <span class="report-chevron" aria-hidden="true">▾</span>
              <span class="report-title">${escapeHtml(rep.title || rep.source_name)}</span>
              <span class="meta-tag">${escapeHtml(rep.detected_key || "N/A")}</span>
            </div>
            <div class="report-header-right">
              <span class="badge ${badgeClass}">${escapeHtml(badgeText)}</span>
            </div>
          </summary>
          <div class="report-body">
            <div class="report-meta">
              <span class="meta-tag">${escapeHtml(t("meta_file", { file: rep.source_name }))}</span>
              <span class="meta-tag">${escapeHtml(
                t("meta_key", { key: rep.detected_key || "N/A" })
              )}</span>
              <span class="meta-tag">${escapeHtml(
                t("meta_annotations", { count: rep.annotations_count || 0 })
              )}</span>
              <span class="meta-tag">${escapeHtml(
                t("meta_lang", { lang: (rep.language || "fr").toUpperCase() })
              )}</span>
            </div>
            ${adminUsageBarHtml}
            <p class="report-summary">${escapeHtml(rep.overall_summary || "")}</p>
            ${bassProposalsHtml}
            <div class="report-actions">
              ${
                rep.download_url
                  ? `<a class="btn btn-primary btn-sm" href="${escapeHtml(
                      rep.download_url
                    )}" download="${escapeHtml(rep.output_filename)}">${escapeHtml(
                      t("btn_download_annotated_pdf", { file: rep.output_filename })
                    )}</a>`
                  : ""
              }
              ${previewBtnHtml}
              ${
                rep.original_url
                  ? `<a class="btn btn-outline btn-sm" href="${escapeHtml(
                      rep.original_url
                    )}" target="_blank" rel="noopener">${escapeHtml(t("btn_open_original"))}</a>`
                  : ""
              }
            </div>
          </div>
        </details>
      </article>
    `;
    const el = wrapper.firstElementChild;
    if (el) cardDataStore.set(el, { kind: "report", data: rep });
    return el;
  }

  function createJobItemCardElement(item, cardIndex = 0) {
    if (item.report && (item.status === "completed" || item.status === "skipped" || item.status === "error")) {
      const el = createReportElement(item.report, cardIndex);
      if (el) el.dataset.itemId = item.item_id;
      return el;
    }

    const deferredClass = cardIndex >= 2 ? "report-item heavy-card-deferred" : "report-item";
    let badgeClass = "badge-queued";
    let badgeText = t("badge_queued");
    if (item.status === "processing") {
      badgeClass = "badge-add";
      badgeText = t("badge_processing", { percent: item.percent || 15 });
    } else if (item.status === "deferred_next_day") {
      badgeClass = "badge-deferred";
      const dateStr = (item.scheduled_for || "").slice(0, 10) || t("tomorrow_word");
      badgeText = t("badge_deferred", { date: dateStr });
    } else if (item.status === "cancelled") {
      badgeClass = "badge-cancelled";
      badgeText = t("badge_cancelled");
    } else if (item.status === "error") {
      badgeClass = "";
      badgeText = t("badge_error_icon");
    }

    const wrapper = document.createElement("div");
    const openAttr = item.status === "processing" ? " open" : "";
    wrapper.innerHTML = `
      <article class="${deferredClass}" data-item-id="${escapeHtml(item.item_id)}">
        <details class="report-details"${openAttr}>
          <summary class="report-header report-summary-toggle" title="${escapeHtml(
            t("card_toggle_title")
          )}">
            <div class="report-header-left">
              <span class="report-chevron" aria-hidden="true">▾</span>
              <span class="report-title">#${item.index} — ${escapeHtml(item.filename)}</span>
            </div>
            <div class="report-header-right">
              <span class="badge ${badgeClass}">${escapeHtml(badgeText)}</span>
            </div>
          </summary>
          <div class="report-body">
            <p class="report-summary">${escapeHtml(
              item.stage_message || item.error || t("item_waiting")
            )}</p>
          </div>
        </details>
      </article>
    `;
    const el = wrapper.firstElementChild;
    if (el) cardDataStore.set(el, { kind: "jobItem", data: item });
    return el;
  }

  function focusSingleReportCard(targetCardEl) {
    if (!targetCardEl) return;
    const allDetails = Array.from(resultsList.querySelectorAll(".report-details"));
    const targetDetails = targetCardEl.querySelector(".report-details");
    allDetails.forEach((d) => {
      d.open = d === targetDetails;
    });
    if (toggleAllCardsBtn) {
      toggleAllCardsBtn.innerHTML = `<span aria-hidden="true">↕</span> ${escapeHtml(
        t("btn_expand_all")
      )}`;
    }
  }

  if (toggleAllCardsBtn) {
    toggleAllCardsBtn.addEventListener("click", () => {
      const allDetails = Array.from(resultsList.querySelectorAll(".report-details"));
      if (allDetails.length === 0) return;
      const anyOpen = allDetails.some((d) => d.open);
      allDetails.forEach((d) => {
        d.open = !anyOpen;
      });
      toggleAllCardsBtn.innerHTML = anyOpen
        ? `<span aria-hidden="true">↕</span> ${escapeHtml(t("btn_expand_all"))}`
        : `<span aria-hidden="true">↕</span> ${escapeHtml(t("btn_collapse_all"))}`;
    });
  }

  function renderBatchJobState(job) {
    if (!job) return;
    if (job.daily_quota) {
      updateQuotaUI(job.daily_quota);
    }
    if (job.admin_usage) {
      updateAdminUsageUI(job.admin_usage);
    }

    if (jobSummaryBar) {
      jobSummaryBar.hidden = false;
      if (jobCountCompleted) jobCountCompleted.textContent = String(job.completed_files || 0);
      if (jobCountQueued) jobCountQueued.textContent = String(job.queued_today_files || 0);
      if (jobCounterDeferredWrap && jobCountDeferred) {
        const defCount = job.deferred_files || 0;
        jobCounterDeferredWrap.hidden = defCount === 0;
        jobCountDeferred.textContent = String(defCount);
      }
      if (jobDownloadZipBtn) {
        if ((job.completed_files || 0) > 0) {
          jobDownloadZipBtn.hidden = false;
          jobDownloadZipBtn.href = `/api/jobs/${encodeURIComponent(job.job_id)}/download-zip`;
        } else {
          jobDownloadZipBtn.hidden = true;
        }
      }
    }

    const isRunning = job.status === "running";
    if (cancelAnalysisBtn) {
      cancelAnalysisBtn.disabled = !isRunning;
    }

    const fileLabel = isRunning
      ? t("job_progress_running", {
          index: job.active_item_index || (job.completed_files || 0) + 1,
          total: job.total_files || 1,
          file: job.active_filename || "",
        })
      : job.status === "partially_deferred"
      ? t("job_progress_partially_deferred", {
          completed: job.completed_files,
          total: job.total_files,
          deferred: job.deferred_files,
        })
      : job.status === "cancelled"
      ? t("job_progress_cancelled", {
          completed: job.completed_files,
          total: job.total_files,
        })
      : t("job_progress_completed", {
          completed: job.completed_files,
          total: job.total_files,
        });

    showProgressPanel(
      fileLabel,
      job.percent || 0,
      job.message || job.active_stage_message || "",
      isRunning ? job.active_stage || "download" : "done"
    );
    setStatus(job.message || fileLabel, job.status === "error");

    const stack = ensureResultsStack();
    const items = job.items || [];
    let newlyProcessedCard = null;

    items.forEach((it, idx) => {
      const stateSignature = `${it.status}:${it.stage}:${it.percent}:${Boolean(it.report)}`;
      const prevSig = renderedItemState.get(it.item_id);
      const prevStatus = prevSig ? prevSig.split(":")[0] : null;
      const isFinished =
        it.status === "completed" || it.status === "skipped" || it.status === "error";
      let existingNode = stack.querySelector(`[data-item-id="${CSS.escape(it.item_id)}"]`);
      if (!existingNode) {
        const newEl = createJobItemCardElement(it, idx);
        if (newEl) {
          newEl.dataset.itemId = it.item_id;
          stack.appendChild(newEl);
          renderedItemState.set(it.item_id, stateSignature);
          if (isFinished) {
            newlyProcessedCard = newEl;
          }
        }
      } else if (prevSig !== stateSignature) {
        const prevDetails = existingNode.querySelector(".report-details");
        const wasOpen = prevDetails ? prevDetails.open : false;
        const justFinished =
          isFinished &&
          prevStatus !== "completed" &&
          prevStatus !== "skipped" &&
          prevStatus !== "error";
        const updatedEl = createJobItemCardElement(it, idx);
        if (updatedEl) {
          updatedEl.dataset.itemId = it.item_id;
          const nextDetails = updatedEl.querySelector(".report-details");
          if (nextDetails) {
            nextDetails.open = justFinished ? true : wasOpen;
          }
          existingNode.replaceWith(updatedEl);
          renderedItemState.set(it.item_id, stateSignature);
          if (justFinished) {
            newlyProcessedCard = updatedEl;
          }
        }
      }
    });

    if (newlyProcessedCard) {
      focusSingleReportCard(newlyProcessedCard);
    }
  }

  function stopJobPolling() {
    if (activeJobPollTimer) {
      clearTimeout(activeJobPollTimer);
      activeJobPollTimer = null;
    }
  }

  async function pollJobOnce(jobId) {
    try {
      const resp = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
      if (!resp.ok) {
        if (resp.status === 404) {
          localStorage.removeItem("akkord_active_job_id");
          stopJobPolling();
        }
        return;
      }
      const job = await resp.json();
      renderBatchJobState(job);
      if (job.status === "running") {
        activeJobPollTimer = setTimeout(() => pollJobOnce(jobId), 2000);
      } else {
        stopJobPolling();
        uploadSubmitBtn.disabled = false;
        driveSubmitBtn.disabled = false;
        scanBtn.disabled = false;
        if (job.status === "completed" || job.status === "cancelled") {
          localStorage.removeItem("akkord_active_job_id");
        }
      }
    } catch (_err) {
      activeJobPollTimer = setTimeout(() => pollJobOnce(jobId), 3500);
    }
  }

  function startNewJobMonitoring(job) {
    stopJobPolling();
    activeJobId = job.job_id;
    localStorage.setItem("akkord_active_job_id", job.job_id);
    renderedItemState.clear();
    resultsList.innerHTML = "";
    ensureResultsStack();
    renderBatchJobState(job);
    if (job.status === "running") {
      activeJobPollTimer = setTimeout(() => pollJobOnce(job.job_id), 1500);
    } else {
      uploadSubmitBtn.disabled = false;
      driveSubmitBtn.disabled = false;
      scanBtn.disabled = false;
    }
  }

  function resumeJobMonitoring(jobId) {
    stopJobPolling();
    activeJobId = jobId;
    renderedItemState.clear();
    resultsList.innerHTML = "";
    ensureResultsStack();
    pollJobOnce(jobId);
  }

  function renderRestoredHistory(jobs, historyItems) {
    const latestJob = jobs && jobs.length > 0 ? jobs[0] : null;
    const itemsToRender =
      historyItems && historyItems.length > 0
        ? historyItems
        : latestJob && latestJob.items
        ? latestJob.items
        : [];
    if (itemsToRender.length === 0) return;

    activeJobId = latestJob ? latestJob.job_id : null;
    renderedItemState.clear();
    resultsList.innerHTML = "";
    const stack = ensureResultsStack();

    const completedCount = itemsToRender.filter(
      (it) => it.status === "completed" || it.status === "skipped"
    ).length;
    const queuedCount = itemsToRender.filter(
      (it) => it.status === "queued" || it.status === "processing"
    ).length;
    const deferredCount = itemsToRender.filter(
      (it) => it.status === "deferred_next_day"
    ).length;

    if (jobSummaryBar) {
      jobSummaryBar.hidden = false;
      if (jobCountCompleted) jobCountCompleted.textContent = String(completedCount);
      if (jobCountQueued) jobCountQueued.textContent = String(queuedCount);
      if (jobCounterDeferredWrap && jobCountDeferred) {
        jobCounterDeferredWrap.hidden = deferredCount === 0;
        jobCountDeferred.textContent = String(deferredCount);
      }
      if (jobDownloadZipBtn) {
        if (latestJob && (latestJob.completed_files || 0) > 0) {
          jobDownloadZipBtn.hidden = false;
          jobDownloadZipBtn.href = `/api/jobs/${encodeURIComponent(latestJob.job_id)}/download-zip`;
        } else {
          jobDownloadZipBtn.hidden = true;
        }
      }
    }

    itemsToRender.forEach((it, idx) => {
      const cardEl = createJobItemCardElement(it, idx);
      if (cardEl) {
        cardEl.dataset.itemId = it.item_id || `hist-${idx}`;
        const det = cardEl.querySelector(".report-details");
        if (det) {
          det.open = idx === 0;
        }
        stack.appendChild(cardEl);
      }
    });
    if (toggleAllCardsBtn) {
      toggleAllCardsBtn.innerHTML =
        itemsToRender.length > 1
          ? `<span aria-hidden="true">↕</span> ${escapeHtml(t("btn_expand_all"))}`
          : `<span aria-hidden="true">↕</span> ${escapeHtml(t("btn_collapse_all"))}`;
    }
  }

  function ensureResultsStack() {
    emptyState.hidden = true;
    let stack = resultsList.querySelector(".reports-stack");
    if (!stack) {
      resultsList.innerHTML = '<div class="reports-stack"></div>';
      stack = resultsList.querySelector(".reports-stack");
    }
    return stack;
  }

  async function consumeNdjsonStream(resp, options = {}) {
    if (!resp.ok) {
      const errData = await parseJsonResponse(resp);
      throw new Error(errData.detail || t("stream_failed"));
    }

    if (!options.preserveResults) {
      resultsList.innerHTML = "";
    }
    const stack = ensureResultsStack();

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalCount = 0;
    let wasInterruptedOrCapped = false;
    let receivedBatchDone = false;
    const indexOffset = options.indexOffset || 0;
    const totalOverride = options.totalOverride || 0;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        let evt = null;
        try {
          evt = JSON.parse(trimmed);
        } catch (_e) {
          continue;
        }

        if (evt.daily_quota) {
          updateQuotaUI(evt.daily_quota);
        }
        if (evt.admin_usage) {
          updateAdminUsageUI(evt.admin_usage);
        }

        const displayIdx = indexOffset + (evt.file_index || 1);
        const displayTotal = totalOverride || evt.total_files || 1;
        const calcPercent = totalOverride
          ? Math.round(((indexOffset + (evt.percent || 0) / 100) / displayTotal) * 100)
          : evt.percent;

        if (evt.type === "file_start") {
          const label = t("stream_file_label", {
            index: displayIdx,
            total: displayTotal,
            file: evt.filename,
          });
          showProgressPanel(
            label,
            calcPercent,
            t("stream_file_starting", { file: evt.filename }),
            "download"
          );
          setStatus(label);
        } else if (evt.type === "step") {
          const label = t("stream_file_label", {
            index: displayIdx,
            total: displayTotal,
            file: evt.filename,
          });
          showProgressPanel(label, calcPercent, evt.message, evt.stage);
          setStatus(evt.message);
        } else if (evt.type === "file_done") {
          finalCount += 1;
          const donePct = Math.round((displayIdx / displayTotal) * 100);
          const label = t("stream_file_done_label", {
            index: displayIdx,
            total: displayTotal,
            file: evt.filename,
          });
          showProgressPanel(
            label,
            donePct,
            t("stream_file_done_msg", { file: evt.filename }),
            "done"
          );
          if (evt.report) {
            const cardEl = createReportElement(evt.report);
            if (cardEl) {
              stack.appendChild(cardEl);
              focusSingleReportCard(cardEl);
            }
          }
        } else if (evt.type === "cancelled") {
          wasInterruptedOrCapped = true;
          receivedBatchDone = true;
          finalCount = indexOffset + (evt.processed_count || finalCount);
          showProgressPanel(
            t("stream_cancelled_label", { count: finalCount }),
            100,
            evt.message || t("stream_cancelled_msg"),
            "done"
          );
          setStatus(evt.message || t("stream_cancelled_msg"));
          if (cancelAnalysisBtn) cancelAnalysisBtn.disabled = true;
        } else if (evt.type === "quota_reached") {
          wasInterruptedOrCapped = true;
          receivedBatchDone = true;
          finalCount = indexOffset + (evt.processed_count || finalCount);
          showProgressPanel(
            t("stream_quota_label", { count: finalCount }),
            100,
            evt.message || t("stream_quota_msg"),
            "done"
          );
          setStatus(evt.message || t("stream_quota_msg"), true);
          if (cancelAnalysisBtn) cancelAnalysisBtn.disabled = true;
        } else if (evt.type === "batch_done") {
          receivedBatchDone = true;
          finalCount = evt.processed_count || finalCount;
          if (!options.suppressFinalBanner) {
            showProgressPanel(
              t("stream_batch_done_label", { count: indexOffset + finalCount }),
              100,
              t("stream_batch_done_msg"),
              "done"
            );
            if (cancelAnalysisBtn) cancelAnalysisBtn.disabled = true;
          }
        }
      }
    }

    if (!receivedBatchDone && !wasInterruptedOrCapped && !options.suppressFinalBanner) {
      showProgressPanel(
        t("stream_interrupted_label", { count: indexOffset + finalCount }),
        100,
        t("stream_interrupted_msg"),
        "done"
      );
      setStatus(t("stream_interrupted_status", { count: indexOffset + finalCount }), true);
      return { processedCount: finalCount, interrupted: true, cancelled: false, quotaReached: false };
    }

    if (!wasInterruptedOrCapped && !options.suppressFinalBanner) {
      setStatus(t("stream_final_status", { count: indexOffset + finalCount }));
    }
    return {
      processedCount: finalCount,
      interrupted: false,
      cancelled: wasInterruptedOrCapped,
      quotaReached: wasInterruptedOrCapped,
    };
  }

  // Handle direct PDF upload via decoupled asynchronous BatchJob (/api/jobs/upload)
  uploadForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!uploadForm.checkValidity()) {
      uploadForm.reportValidity();
      return;
    }

    const files = Array.from(pdfFileInput.files || []);
    if (files.length === 0) {
      return;
    }

    const language = getSelectedLanguage();
    const model = getSelectedModel();

    uploadSubmitBtn.disabled = true;
    if (cancelAnalysisBtn) cancelAnalysisBtn.disabled = false;
    showProgressPanel(
      t("upload_progress_sending", { count: files.length }),
      3,
      t("upload_progress_queueing"),
      "download"
    );
    setStatus(t("upload_status_submitting", { count: files.length }));

    try {
      const formData = new FormData();
      files.forEach((f) => formData.append("files", f));
      formData.append("language", language);
      formData.append("model", model);

      const resp = await fetch("/api/jobs/upload", {
        method: "POST",
        body: formData,
      });
      const jobData = await parseJsonResponse(resp);
      if (!resp.ok) {
        throw new Error(jobData.detail || t("upload_job_error"));
      }

      startNewJobMonitoring(jobData);
    } catch (err) {
      setStatus(err.message, true);
      hideProgressPanel();
      uploadSubmitBtn.disabled = false;
      if (cancelAnalysisBtn) cancelAnalysisBtn.disabled = true;
    }
  });

  // Scan Google Drive folder
  scanBtn.addEventListener("click", async () => {
    const folder = folderInput.value.trim();
    if (!folder) {
      folderInput.focus();
      driveForm.reportValidity();
      return;
    }

    scanBtn.disabled = true;
    setStatus(t("scan_status_searching"));
    try {
      const resp = await fetch("/api/scan-folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder }),
      });
      const data = await parseJsonResponse(resp);
      if (!resp.ok) {
        throw new Error(data.detail || t("scan_error"));
      }

      discoveredList.innerHTML = "";
      if (data.files.length === 0) {
        const li = document.createElement("li");
        li.textContent = t("drive_discovered_empty");
        discoveredList.appendChild(li);
      } else {
        data.files.forEach((f) => {
          const li = document.createElement("li");
          li.textContent = `${f.name} (${f.source})`;
          discoveredList.appendChild(li);
        });
      }
      discoveredContainer.hidden = false;
      setStatus(t("scan_status_found", { count: data.count }));
    } catch (err) {
      setStatus(err.message, true);
    } finally {
      scanBtn.disabled = false;
    }
  });

  // Process Google Drive folder via decoupled asynchronous BatchJob (/api/jobs/drive)
  driveForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!driveForm.checkValidity()) {
      driveForm.reportValidity();
      return;
    }

    const folder = folderInput.value.trim();
    const language = getSelectedLanguage();
    const model = getSelectedModel();
    const uploadToDrive = document.getElementById("upload-drive").checked;

    driveSubmitBtn.disabled = true;
    scanBtn.disabled = true;
    if (cancelAnalysisBtn) cancelAnalysisBtn.disabled = false;
    showProgressPanel(
      t("drive_progress_scheduling"),
      3,
      t("drive_progress_discovering"),
      "download"
    );
    setStatus(t("drive_status_creating_job"));

    try {
      const resp = await fetch("/api/jobs/drive", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          folder,
          language,
          model,
          upload_to_drive: uploadToDrive,
        }),
      });
      const jobData = await parseJsonResponse(resp);
      if (!resp.ok) {
        throw new Error(jobData.detail || t("drive_job_error"));
      }

      startNewJobMonitoring(jobData);
    } catch (err) {
      setStatus(err.message, true);
      hideProgressPanel();
      driveSubmitBtn.disabled = false;
      scanBtn.disabled = false;
      if (cancelAnalysisBtn) cancelAnalysisBtn.disabled = true;
    }
  });

  // Google Drive Interactive Folder Browser logic
  if (driveBrowserDialog) {
    // Fallback for browsers without <dialog closedby> support
    if (!("closedBy" in HTMLDialogElement.prototype)) {
      driveBrowserDialog.addEventListener("click", (event) => {
        if (event.target !== driveBrowserDialog) return;
        const rect = driveBrowserDialog.getBoundingClientRect();
        const isDialogContent =
          rect.top <= event.clientY &&
          event.clientY <= rect.top + rect.height &&
          rect.left <= event.clientX &&
          event.clientX <= rect.left + rect.width;
        if (isDialogContent) return;
        driveBrowserDialog.close();
      });
    }

    let drivePathStack = [{ id: "root", name: t("drive_tab_my_drive") }];
    let currentBrowseFolderId = "root";
    let currentBrowseFolderName = t("drive_tab_my_drive");

    function setBrowserStatus(msg, isError = false) {
      if (!driveBrowserStatus) return;
      if (!msg) {
        driveBrowserStatus.hidden = true;
        driveBrowserStatus.textContent = "";
        return;
      }
      driveBrowserStatus.hidden = false;
      driveBrowserStatus.textContent = msg;
      driveBrowserStatus.classList.toggle("error", isError);
    }

    function renderBreadcrumbs() {
      if (!driveBreadcrumbs) return;
      driveBreadcrumbs.innerHTML = "";
      drivePathStack.forEach((crumb, idx) => {
        const li = document.createElement("li");
        const isLast = idx === drivePathStack.length - 1;
        if (isLast) {
          const span = document.createElement("span");
          span.className = "drive-crumb-current";
          span.setAttribute("aria-current", "location");
          span.textContent = crumb.name;
          li.appendChild(span);
        } else {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "drive-crumb-btn";
          btn.textContent = crumb.name;
          btn.addEventListener("click", () => {
            drivePathStack = drivePathStack.slice(0, idx + 1);
            loadDriveFolder(crumb.id, "", false);
          });
          li.appendChild(btn);
        }
        driveBreadcrumbs.appendChild(li);
      });
    }

    function selectDriveFolder(folderId, folderName) {
      if (!folderId || folderId === "shared" || folderId === "search") {
        setBrowserStatus(t("drive_select_specific_folder_err"), true);
        return;
      }
      const url =
        folderId === "root"
          ? "root"
          : `https://drive.google.com/drive/folders/${folderId}`;
      folderInput.value = url;
      driveBrowserDialog.close();
      setStatus(t("drive_folder_selected_scanning", { folder: folderName }));
      scanBtn.click();
    }

    async function loadDriveFolder(folderId = "root", searchQuery = "", pushCrumb = false, crumbName = "") {
      setBrowserStatus(t("drive_loading_folders"));
      driveFolderList.innerHTML = "";
      drivePdfPreview.hidden = true;

      try {
        const params = new URLSearchParams();
        params.set("folder_id", folderId);
        if (searchQuery) {
          params.set("q", searchQuery);
        }
        const resp = await fetch(`/api/drive/browse?${params.toString()}`);
        const data = await parseJsonResponse(resp);
        if (!resp.ok) {
          throw new Error(data.detail || t("drive_browse_error"));
        }

        setBrowserStatus("");
        const folderMeta = data.current_folder || { id: folderId, name: crumbName || folderId };
        currentBrowseFolderId = folderMeta.id;
        currentBrowseFolderName =
          folderMeta.id === "root"
            ? t("drive_tab_my_drive")
            : folderMeta.id === "shared"
            ? t("drive_tab_shared")
            : folderMeta.name;

        if (searchQuery) {
          drivePathStack = [
            { id: "root", name: t("drive_tab_my_drive") },
            { id: "search", name: folderMeta.name },
          ];
        } else if (pushCrumb) {
          drivePathStack.push({ id: folderMeta.id, name: currentBrowseFolderName });
        }

        renderBreadcrumbs();
        driveCurrentFolderName.textContent = currentBrowseFolderName;
        driveSelectCurrentBtn.disabled =
          currentBrowseFolderId === "shared" || currentBrowseFolderId === "search";

        const folders = data.folders || [];
        if (folders.length === 0) {
          const emptyLi = document.createElement("li");
          emptyLi.className = "drive-empty-folders";
          emptyLi.textContent = t("drive_empty_subfolders");
          driveFolderList.appendChild(emptyLi);
        } else {
          folders.forEach((f) => {
            const li = document.createElement("li");
            li.className = "drive-folder-item";

            const openBtn = document.createElement("button");
            openBtn.type = "button";
            openBtn.className = "drive-folder-open-btn";
            openBtn.innerHTML = `<span aria-hidden="true">📁</span> <span></span>`;
            openBtn.querySelector("span:last-child").textContent = f.name;
            openBtn.addEventListener("click", () => {
              if (driveFolderSearch) driveFolderSearch.value = "";
              loadDriveFolder(f.id, "", true, f.name);
            });

            const chooseBtn = document.createElement("button");
            chooseBtn.type = "button";
            chooseBtn.className = "btn btn-outline btn-sm";
            chooseBtn.textContent = t("drive_choose_btn");
            chooseBtn.addEventListener("click", () => {
              selectDriveFolder(f.id, f.name);
            });

            li.appendChild(openBtn);
            li.appendChild(chooseBtn);
            driveFolderList.appendChild(li);
          });
        }

        const pdfs = data.pdfs || [];
        if (pdfs.length > 0) {
          drivePdfPreview.hidden = false;
          drivePdfCountLabel.textContent = t("drive_pdfs_detected_in", {
            count: pdfs.length,
            folder: currentBrowseFolderName,
          });
          drivePdfNames.innerHTML = "";
          pdfs.forEach((p) => {
            const pli = document.createElement("li");
            pli.textContent = p.name;
            drivePdfNames.appendChild(pli);
          });
        }
      } catch (err) {
        setBrowserStatus(err.message, true);
      }
    }

    if (browseDriveBtn) {
      browseDriveBtn.addEventListener("click", () => {
        if (!currentAuth.authenticated) {
          window.location.href = "/auth/login";
          return;
        }
        drivePathStack = [{ id: "root", name: t("drive_tab_my_drive") }];
        if (driveTabRoot) driveTabRoot.classList.add("active");
        if (driveTabShared) driveTabShared.classList.remove("active");
        if (driveFolderSearch) driveFolderSearch.value = "";
        driveBrowserDialog.showModal();
        loadDriveFolder("root", "", false);
      });
    }

    if (driveTabRoot) {
      driveTabRoot.addEventListener("click", () => {
        driveTabRoot.classList.add("active");
        if (driveTabShared) driveTabShared.classList.remove("active");
        if (driveFolderSearch) driveFolderSearch.value = "";
        drivePathStack = [{ id: "root", name: t("drive_tab_my_drive") }];
        loadDriveFolder("root", "", false);
      });
    }

    if (driveTabShared) {
      driveTabShared.addEventListener("click", () => {
        driveTabShared.classList.add("active");
        if (driveTabRoot) driveTabRoot.classList.remove("active");
        if (driveFolderSearch) driveFolderSearch.value = "";
        drivePathStack = [{ id: "shared", name: t("drive_tab_shared") }];
        loadDriveFolder("shared", "", false);
      });
    }

    if (driveSearchBtn && driveFolderSearch) {
      const triggerSearch = () => {
        const q = driveFolderSearch.value.trim();
        if (!q) {
          drivePathStack = [{ id: "root", name: t("drive_tab_my_drive") }];
          loadDriveFolder("root", "", false);
          return;
        }
        loadDriveFolder("root", q, false);
      };
      driveSearchBtn.addEventListener("click", triggerSearch);
      driveFolderSearch.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          triggerSearch();
        }
      });
    }

    if (driveSelectCurrentBtn) {
      driveSelectCurrentBtn.addEventListener("click", () => {
        selectDriveFolder(currentBrowseFolderId, currentBrowseFolderName);
      });
    }
  }
})();
