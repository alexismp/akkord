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
      pdfPreviewDialogTitle.textContent = title || sourceName || "Aperçu de la partition PDF";
    }
    if (pdfPreviewDialogSub) {
      pdfPreviewDialogSub.textContent = outputFilename
        ? `${sourceName} → ${outputFilename}`
        : sourceName || "";
    }
    if (pdfPreviewDownloadBtn) {
      if (downloadUrl) {
        pdfPreviewDownloadBtn.hidden = false;
        pdfPreviewDownloadBtn.href = downloadUrl;
        pdfPreviewDownloadBtn.setAttribute("download", outputFilename || "partition-annotee.pdf");
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
        pdfPreviewOrigLabel.textContent = `Partition originale (${sourceName || "PDF"})`;
      }
      pdfPreviewOrigIframe.src = hasOrig ? originalUrl : "about:blank";
    }
    if (pdfPreviewAnnotPane && pdfPreviewAnnotIframe) {
      pdfPreviewAnnotPane.hidden = !hasAnnot;
      if (pdfPreviewAnnotLabel) {
        pdfPreviewAnnotLabel.textContent = `Partition annotée (${outputFilename || "PDF"})`;
      }
      pdfPreviewAnnotIframe.src = hasAnnot ? downloadUrl : "about:blank";
    }

    pdfPreviewDialog.showModal();
  }

  // Event delegation on resultsList for "👁 Prévisualiser le PDF" buttons
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
    return Number(n || 0).toLocaleString("fr-FR");
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
    if (!quota || !dailyQuotaBadge) return;
    const used = quota.used || 0;
    const limit = quota.limit || 25;
    dailyQuotaBadge.textContent = `Quota : ${used} / ${limit} PDF`;
  }

  function updateAdminUsageUI(usage) {
    if (!usage) return;
    const today = usage.today || {};
    const cum = usage.cumulative || {};
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
      usageTodayFiles.textContent = `${today.files_count || 0} partition(s) aujourd'hui`;
    }
    if (usageCumCost) {
      usageCumCost.textContent = `${formatUsd(cum.estimated_cost_usd)} / ${formatEur(cum.estimated_cost_eur)}`;
    }
    if (usageCumTokens) {
      usageCumTokens.textContent = `${formatInt(cum.total_tokens)} tok au total (${cum.files_count || 0} fichiers)`;
    }
    if (adminUsageTbody) {
      const entries = usage.recent_entries || [];
      if (!entries.length) {
        adminUsageTbody.innerHTML = `
          <tr>
            <th scope="row">Aucune analyse aujourd'hui</th>
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
    return checked ? checked.value : "fr";
  }

  function getSelectedModel() {
    if (!currentAuth.is_admin || !modelInput) {
      return "gemini-4-argon";
    }
    return (modelInput.value || "").trim() || "gemini-4-argon";
  }

  function setStatus(message, isError = false) {
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
      `Erreur serveur (${resp.status}) : ${cleanText.slice(0, 180) || resp.statusText || "Service indisponible"}`
    );
  }

  function updateAuthUI(auth) {
    if (!auth) return;
    currentAuth = { ...currentAuth, ...auth };

    if (currentAuth.authenticated) {
      authLoggedOut.hidden = true;
      authLoggedIn.hidden = false;
      authUserEmail.textContent = `Google : ${currentAuth.email}`;
      authAdminBadge.hidden = !currentAuth.is_admin;
      adminModelPanel.hidden = !currentAuth.is_admin;

      if (driveOauthBadge) {
        driveOauthBadge.textContent = "Connecté OAuth";
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
        driveOauthBadge.textContent = "Public / Non connecté";
        driveOauthBadge.className = "mode-badge mode-skip";
      }
      if (driveOauthCallout) {
        driveOauthCallout.hidden = false;
      }
    }
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
        setStatus(`Erreur OAuth : ${params.get("oauth_error")}`, true);
        window.history.replaceState({}, "", "/");
      } else if (params.get("digest_sent") === "1") {
        setStatus("✅ Récapitulatif quotidien envoyé par e-mail à alexis.mp@gmail.com !");
        window.history.replaceState({}, "", "/");
      } else if (params.get("digest_error")) {
        setStatus(`Erreur lors de l'envoi du récapitulatif : ${params.get("digest_error")}`, true);
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
      setStatus("⏹ Interruption de l'analyse en cours…");
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
      setStatus("Reprise des partitions reportées (quota quotidien)…");
      try {
        const resp = await fetch("/api/internal/tasks/resume-deferred", { method: "POST" });
        const data = await parseJsonResponse(resp);
        if (data.resumed_count > 0) {
          setStatus(
            `▶️ ${data.resumed_count} partition(s) reportée(s) relancée(s) pour traitement.`
          );
          if (data.jobs_updated && data.jobs_updated.length > 0) {
            resumeJobMonitoring(data.jobs_updated[0]);
          }
        } else {
          setStatus(data.reason || "Aucune partition reportée à relancer aujourd'hui.");
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
      setStatus("Remise à zéro du quota quotidien en cours…");
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
            `✅ Quota quotidien remis à zéro (0 / ${limit} PDF) — ▶️ ${resumedCount} partition(s) reportée(s) relancée(s) immédiatement !`
          );
          if (data.resumed.jobs_updated && data.resumed.jobs_updated.length > 0) {
            resumeJobMonitoring(data.resumed.jobs_updated[0]);
          }
        } else {
          setStatus(`✅ Quota quotidien remis à zéro (0 / ${limit} PDF).`);
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
      setStatus("Envoi du récapitulatif quotidien en cours…");
      try {
        const resp = await fetch("/api/daily-report/send?force=true", { method: "POST" });
        const data = await parseJsonResponse(resp);
        if (data.sent) {
          setStatus(
            `✅ Récapitulatif quotidien envoyé à ${data.recipient} (${data.entries_count} partition(s)).`
          );
        } else if (data.needs_reauth && data.reauth_url) {
          setStatus(
            "Autorisation d'envoi Gmail requise — redirection vers Google pour valider l'envoi…"
          );
          window.location.href = data.reauth_url;
          return;
        } else {
          setStatus(data.reason || (data.errors && data.errors[0]) || "Aucun envoi effectué.", true);
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
      setStatus("Déconnecté de Google Drive.");
    });
  }

  // Update file input label on selection or drag-and-drop
  pdfFileInput.addEventListener("change", () => {
    const files = pdfFileInput.files;
    if (files && files.length > 0) {
      const names = Array.from(files)
        .map((f) => f.name)
        .join(", ");
      selectedFileLabel.textContent = `${files.length} fichier(s) sélectionné(s) : ${names}`;
    } else {
      selectedFileLabel.textContent = "Choisir un PDF ou glisser-déposer ici";
    }
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
        const badgeLabel = isWalking ? "Walking Bass" : "Contrepoint";
        const badgeClass = isWalking ? "bass-tag-walking" : "bass-tag-counterpoint";
        const mLabel = bp.measure_number ? `Mesure ${bp.measure_number}` : "";
        const melodyInfo = bp.melody_note
          ? `<span class="bass-melody-note">Mélodie : ${bp.melody_note}</span>`
          : "";
        return `
          <li class="bass-proposal-item">
            <div class="bass-proposal-top">
              <span class="bass-tag ${badgeClass}">${badgeLabel}</span>
              ${mLabel ? `<span class="bass-measure">${mLabel}</span>` : ""}
              <strong class="bass-chord-change">${bp.original_chord} → ${bp.proposed_slash_chord}</strong>
              ${melodyInfo}
            </div>
            <p class="bass-explanation">${bp.explanation || ""}</p>
          </li>
        `;
      })
      .join("");

    return `
      <div class="bass-proposals-box">
        <h4 class="bass-proposals-title">🎸 Propositions de basses — Contrepoint &amp; Walking Bass (anti-fondamentale / anti-doublage)</h4>
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
                <span class="badge" style="background:#fef2f2;color:#b91c1c;">Erreur</span>
              </div>
            </summary>
            <div class="report-body">
              <p class="report-summary">${escapeHtml(rep.error)}</p>
            </div>
          </details>
        </article>
      `;
      return wrapper.firstElementChild;
    }

    const isAnalyze = rep.mode === "analyze";
    const badgeClass = isAnalyze ? "badge-analyze" : "badge-add";
    const badgeText = isAnalyze
      ? `Analyse des accords (${rep.accuracy_score}% exacts)`
      : "Accords & Basses ajoutés";

    const bassProposalsHtml = renderBassProposals(rep.analysis_detail);

    const tok = rep.token_usage || (rep.analysis_detail && rep.analysis_detail.token_usage) || null;
    const adminUsageBarHtml =
      currentAuth.is_admin && tok
        ? `
          <div class="admin-card-usage-bar" aria-label="Consommation de tokens et coût (Administrateur)">
            <span><strong>📊 Tokens (Admin) :</strong> ${formatInt(tok.total_tokens)} tok</span>
            <span>(Entrée : ${formatInt(tok.input_tokens)} • Sortie : ${formatInt(tok.output_tokens)}${
              tok.thinking_tokens ? ` • Think : ${formatInt(tok.thinking_tokens)}` : ""
            })</span>
            <span>• <strong>Coût estimé :</strong> ${formatUsd(tok.estimated_cost_usd)} / ${formatEur(tok.estimated_cost_eur)}</span>
            <span>• Modèle : <code>${escapeHtml(tok.model || rep.model || "gemini-4-argon")}</code></span>
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
          >👁 Prévisualiser le PDF</button>`
        : "";

    wrapper.innerHTML = `
      <article class="${deferredClass}">
        <details class="report-details" open>
          <summary class="report-header report-summary-toggle" title="Cliquer pour replier ou déplier cette partition">
            <div class="report-header-left">
              <span class="report-chevron" aria-hidden="true">▾</span>
              <span class="report-title">${escapeHtml(rep.title || rep.source_name)}</span>
              <span class="meta-tag">${escapeHtml(rep.detected_key || "N/A")}</span>
            </div>
            <div class="report-header-right">
              <span class="badge ${badgeClass}">${badgeText}</span>
            </div>
          </summary>
          <div class="report-body">
            <div class="report-meta">
              <span class="meta-tag">Fichier : ${escapeHtml(rep.source_name)}</span>
              <span class="meta-tag">Tonalité : ${escapeHtml(rep.detected_key || "N/A")}</span>
              <span class="meta-tag">Annotations : ${rep.annotations_count || 0}</span>
              <span class="meta-tag">Langue : ${escapeHtml((rep.language || "fr").toUpperCase())}</span>
            </div>
            ${adminUsageBarHtml}
            <p class="report-summary">${escapeHtml(rep.overall_summary || "")}</p>
            ${bassProposalsHtml}
            <div class="report-actions">
              ${
                rep.download_url
                  ? `<a class="btn btn-primary btn-sm" href="${escapeHtml(rep.download_url)}" download="${escapeHtml(rep.output_filename)}">⬇ Télécharger le PDF annoté (${escapeHtml(rep.output_filename)})</a>`
                  : ""
              }
              ${previewBtnHtml}
              ${
                rep.original_url
                  ? `<a class="btn btn-outline btn-sm" href="${escapeHtml(rep.original_url)}" target="_blank" rel="noopener">Ouvrir l'original</a>`
                  : ""
              }
            </div>
          </div>
        </details>
      </article>
    `;
    return wrapper.firstElementChild;
  }

  function createJobItemCardElement(item, cardIndex = 0) {
    if (item.report && (item.status === "completed" || item.status === "skipped" || item.status === "error")) {
      const el = createReportElement(item.report, cardIndex);
      if (el) el.dataset.itemId = item.item_id;
      return el;
    }

    const deferredClass = cardIndex >= 2 ? "report-item heavy-card-deferred" : "report-item";
    let badgeClass = "badge-queued";
    let badgeText = "⏳ En file d'attente";
    if (item.status === "processing") {
      badgeClass = "badge-add";
      badgeText = `⚙️ Analyse en cours (${item.percent || 15}%)`;
    } else if (item.status === "deferred_next_day") {
      badgeClass = "badge-deferred";
      const dateStr = (item.scheduled_for || "").slice(0, 10) || "demain";
      badgeText = `📅 Planifié le ${dateStr} (Quota 25/j)`;
    } else if (item.status === "cancelled") {
      badgeClass = "badge-cancelled";
      badgeText = "⏹ Annulé";
    } else if (item.status === "error") {
      badgeClass = "";
      badgeText = "❌ Erreur";
    }

    const wrapper = document.createElement("div");
    const openAttr = item.status === "processing" ? " open" : "";
    wrapper.innerHTML = `
      <article class="${deferredClass}" data-item-id="${escapeHtml(item.item_id)}">
        <details class="report-details"${openAttr}>
          <summary class="report-header report-summary-toggle" title="Cliquer pour replier ou déplier">
            <div class="report-header-left">
              <span class="report-chevron" aria-hidden="true">▾</span>
              <span class="report-title">#${item.index} — ${escapeHtml(item.filename)}</span>
            </div>
            <div class="report-header-right">
              <span class="badge ${badgeClass}">${escapeHtml(badgeText)}</span>
            </div>
          </summary>
          <div class="report-body">
            <p class="report-summary">${escapeHtml(item.stage_message || item.error || "En attente de traitement…")}</p>
          </div>
        </details>
      </article>
    `;
    return wrapper.firstElementChild;
  }

  function focusSingleReportCard(targetCardEl) {
    if (!targetCardEl) return;
    const allDetails = Array.from(resultsList.querySelectorAll(".report-details"));
    const targetDetails = targetCardEl.querySelector(".report-details");
    allDetails.forEach((d) => {
      d.open = d === targetDetails;
    });
    if (toggleAllCardsBtn) {
      toggleAllCardsBtn.innerHTML = '<span aria-hidden="true">↕</span> Tout déplier';
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
        ? '<span aria-hidden="true">↕</span> Tout déplier'
        : '<span aria-hidden="true">↕</span> Tout replier';
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
      ? `Partition ${job.active_item_index || (job.completed_files || 0) + 1} / ${job.total_files || 1} : ${job.active_filename || ""}`
      : job.status === "partially_deferred"
      ? `Lot du jour terminé (${job.completed_files} / ${job.total_files}) • ${job.deferred_files} planifiée(s) pour demain`
      : job.status === "cancelled"
      ? `⏹ Analyse interrompue (${job.completed_files} / ${job.total_files} terminée(s))`
      : `Traitement terminé (${job.completed_files} / ${job.total_files} partition(s))`;

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
          ? '<span aria-hidden="true">↕</span> Tout déplier'
          : '<span aria-hidden="true">↕</span> Tout replier';
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
      throw new Error(errData.detail || "Échec du traitement.");
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
          const label = `Fichier ${displayIdx} / ${displayTotal} : ${evt.filename}`;
          showProgressPanel(label, calcPercent, `Démarrage de ${evt.filename}…`, "download");
          setStatus(label);
        } else if (evt.type === "step") {
          const label = `Fichier ${displayIdx} / ${displayTotal} : ${evt.filename}`;
          showProgressPanel(label, calcPercent, evt.message, evt.stage);
          setStatus(evt.message);
        } else if (evt.type === "file_done") {
          finalCount += 1;
          const donePct = Math.round((displayIdx / displayTotal) * 100);
          const label = `Fichier ${displayIdx} / ${displayTotal} terminé : ${evt.filename}`;
          showProgressPanel(label, donePct, `Terminé : ${evt.filename}`, "done");
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
            `⏹ Analyse interrompue (${finalCount} partition(s) traitée(s))`,
            100,
            evt.message || "Analyse interrompue à la demande de l'utilisateur.",
            "done"
          );
          setStatus(evt.message || "⏹ Analyse interrompue par l'utilisateur.");
          if (cancelAnalysisBtn) cancelAnalysisBtn.disabled = true;
        } else if (evt.type === "quota_reached") {
          wasInterruptedOrCapped = true;
          receivedBatchDone = true;
          finalCount = indexOffset + (evt.processed_count || finalCount);
          showProgressPanel(
            `⚠️ Limite quotidienne atteinte (${finalCount} partition(s) traitée(s))`,
            100,
            evt.message || "Limite quotidienne de 25 fichiers atteinte.",
            "done"
          );
          setStatus(evt.message || "Limite quotidienne de 25 fichiers atteinte.", true);
          if (cancelAnalysisBtn) cancelAnalysisBtn.disabled = true;
        } else if (evt.type === "batch_done") {
          receivedBatchDone = true;
          finalCount = evt.processed_count || finalCount;
          if (!options.suppressFinalBanner) {
            showProgressPanel(
              `Traitement terminé (${indexOffset + finalCount} partition(s))`,
              100,
              "Toutes les partitions ont été annotées avec succès.",
              "done"
            );
            if (cancelAnalysisBtn) cancelAnalysisBtn.disabled = true;
          }
        }
      }
    }

    if (!receivedBatchDone && !wasInterruptedOrCapped && !options.suppressFinalBanner) {
      showProgressPanel(
        `⚠️ Connexion interrompue après ${indexOffset + finalCount} partition(s)`,
        100,
        "Le flux serveur s'est interrompu prématurément.",
        "done"
      );
      setStatus(
        `Flux interrompu après ${indexOffset + finalCount} partition(s) traitée(s).`,
        true
      );
      return { processedCount: finalCount, interrupted: true, cancelled: false, quotaReached: false };
    }

    if (!wasInterruptedOrCapped && !options.suppressFinalBanner) {
      setStatus(`Terminé : ${indexOffset + finalCount} partition(s) PDF annotée(s).`);
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
      `Envoi de ${files.length} fichier(s) PDF…`,
      3,
      "Création de la file d'attente asynchrone…",
      "download"
    );
    setStatus(`Soumission du lot de ${files.length} fichier(s) PDF…`);

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
        throw new Error(jobData.detail || "Échec de la création du lot d'analyse.");
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
    setStatus("Recherche des partitions PDF dans le dossier Google Drive…");
    try {
      const resp = await fetch("/api/scan-folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder }),
      });
      const data = await parseJsonResponse(resp);
      if (!resp.ok) {
        throw new Error(data.detail || "Échec du scan du dossier.");
      }

      discoveredList.innerHTML = "";
      if (data.files.length === 0) {
        discoveredList.innerHTML =
          "<li>Aucun PDF trouvé (s'il s'agit d'un dossier privé, cliquez sur « Se connecter avec Google »).</li>";
      } else {
        data.files.forEach((f) => {
          const li = document.createElement("li");
          li.textContent = `${f.name} (${f.source})`;
          discoveredList.appendChild(li);
        });
      }
      discoveredContainer.hidden = false;
      setStatus(`${data.count} fichier(s) PDF trouvé(s) dans le dossier.`);
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
      "Planification du dossier Google Drive…",
      3,
      "Découverte des partitions PDF et mise en file d'attente d'événements…",
      "download"
    );
    setStatus("Création du job d'analyse asynchrone pour le dossier Google Drive…");

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
        throw new Error(jobData.detail || "Échec de la planification du dossier Google Drive.");
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

    let drivePathStack = [{ id: "root", name: "Mon Drive" }];
    let currentBrowseFolderId = "root";
    let currentBrowseFolderName = "Mon Drive";

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
        setBrowserStatus("Veuillez ouvrir ou sélectionner un dossier spécifique.", true);
        return;
      }
      const url =
        folderId === "root"
          ? "root"
          : `https://drive.google.com/drive/folders/${folderId}`;
      folderInput.value = url;
      driveBrowserDialog.close();
      setStatus(`Dossier Google Drive sélectionné : « ${folderName} ». Scan en cours…`);
      scanBtn.click();
    }

    async function loadDriveFolder(folderId = "root", searchQuery = "", pushCrumb = false, crumbName = "") {
      setBrowserStatus("Chargement des dossiers Google Drive…");
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
          throw new Error(data.detail || "Impossible de parcourir Google Drive.");
        }

        setBrowserStatus("");
        const folderMeta = data.current_folder || { id: folderId, name: crumbName || folderId };
        currentBrowseFolderId = folderMeta.id;
        currentBrowseFolderName = folderMeta.name;

        if (searchQuery) {
          drivePathStack = [
            { id: "root", name: "Mon Drive" },
            { id: "search", name: folderMeta.name },
          ];
        } else if (pushCrumb) {
          drivePathStack.push({ id: folderMeta.id, name: folderMeta.name });
        }

        renderBreadcrumbs();
        driveCurrentFolderName.textContent = currentBrowseFolderName;
        driveSelectCurrentBtn.disabled =
          currentBrowseFolderId === "shared" || currentBrowseFolderId === "search";

        const folders = data.folders || [];
        if (folders.length === 0) {
          const emptyLi = document.createElement("li");
          emptyLi.className = "drive-empty-folders";
          emptyLi.textContent = "Aucun sous-dossier dans cet emplacement.";
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
            chooseBtn.textContent = "Choisir";
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
          drivePdfCountLabel.textContent = `📄 ${pdfs.length} partition(s) PDF détectée(s) dans « ${currentBrowseFolderName} » :`;
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
        drivePathStack = [{ id: "root", name: "Mon Drive" }];
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
        drivePathStack = [{ id: "root", name: "Mon Drive" }];
        loadDriveFolder("root", "", false);
      });
    }

    if (driveTabShared) {
      driveTabShared.addEventListener("click", () => {
        driveTabShared.classList.add("active");
        if (driveTabRoot) driveTabRoot.classList.remove("active");
        if (driveFolderSearch) driveFolderSearch.value = "";
        drivePathStack = [{ id: "shared", name: "Partagés avec moi" }];
        loadDriveFolder("shared", "", false);
      });
    }

    if (driveSearchBtn && driveFolderSearch) {
      const triggerSearch = () => {
        const q = driveFolderSearch.value.trim();
        if (!q) {
          drivePathStack = [{ id: "root", name: "Mon Drive" }];
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
