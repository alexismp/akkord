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

package com.akkord.jobs;

import com.akkord.config.AkkordConfig;
import com.akkord.drive.DriveConnector;
import com.akkord.harmony.HarmonyEngine;
import com.akkord.model.Models.HarmonyAnalysisResult;
import com.akkord.model.Models.LayoutExtractionResult;
import com.akkord.model.Models.SheetFile;
import com.akkord.model.Models.SheetProcessReport;
import com.akkord.oauth.OAuthManager;
import com.akkord.pdf.PdfLayoutAnalyzer;
import com.akkord.pdf.PdfVectorAnnotator;
import com.akkord.store.CloudStore;
import com.akkord.store.CloudStore.ActivityManager;
import com.akkord.store.CloudStore.FirestoreBackend;
import com.akkord.store.CloudStore.GCSBackend;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/**
 * End-to-end PDF music sheet pipeline and Virtual-Thread-backed batch job queue for Modern Java 25.
 */
public final class JobQueueManager {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    public static final class Pipeline {
        private final AkkordConfig config;
        private final DriveConnector drive;
        private final HarmonyEngine harmony;

        public Pipeline(AkkordConfig config, String oauthAccessToken) {
            this.config = config;
            this.drive = new DriveConnector(oauthAccessToken);
            this.harmony = new HarmonyEngine(config);
        }

        public DriveConnector getDrive() {
            return drive;
        }

        public SheetProcessReport processSingleSheet(SheetFile sheet, File tmpDir) throws IOException {
            File localPdf = drive.downloadPdf(sheet, tmpDir);
            String stem = sheet.name().replaceFirst("\\.[pP][dD][fF]$", "");
            File workDir = new File(tmpDir, "work_" + stem);
            workDir.mkdirs();

            LayoutExtractionResult layoutRes = PdfLayoutAnalyzer.analyzePdf(localPdf, workDir);
            HarmonyAnalysisResult analysis = harmony.analyzeSheet(sheet.name(), layoutRes);

            if (!analysis.isMusicSheet()) {
                return new SheetProcessReport(
                        sheet.name(), "", "skipped", "-", 0, 0,
                        analysis.overallSummary(), null, null, analysis.tokenUsage()
                );
            }

            String suffix = AkkordConfig.fileSuffix(config.language(), analysis.hasExistingChords());
            String mode = analysis.hasExistingChords() ? "analyze" : "add_chords";
            String outputFilename = stem + suffix;
            File outDir = new File(config.outputDir());
            outDir.mkdirs();
            File outputPdf = new File(outDir, outputFilename);

            PdfVectorAnnotator.annotatePdf(localPdf, outputPdf, config.language(), layoutRes.pages(), analysis);

            String uploadedId = null;
            String uploadedLink = null;
            if (config.uploadToDrive() && sheet.driveParentId() != null && !sheet.driveParentId().isBlank()) {
                Map<String, String> up = drive.uploadPdf(outputPdf, sheet.driveParentId(), outputFilename);
                uploadedId = up.get("id");
                uploadedLink = up.get("webViewLink");
            }

            return new SheetProcessReport(
                    sheet.name(),
                    outputPdf.getAbsolutePath(),
                    mode,
                    analysis.detectedKey(),
                    analysis.accuracyScore(),
                    analysis.annotations() != null ? analysis.annotations().size() : 0,
                    analysis.overallSummary(),
                    uploadedId,
                    uploadedLink,
                    analysis.tokenUsage()
            );
        }
    }

    private final File outputDir;
    private final FirestoreBackend firestore;
    private final GCSBackend gcs;
    private final ActivityManager activity;
    private final OAuthManager oauth;
    private final ExecutorService virtualExecutor = Executors.newVirtualThreadPerTaskExecutor();
    private final Set<String> cancelledJobs = ConcurrentHashMap.newKeySet();

    public JobQueueManager(
            File outputDir,
            FirestoreBackend firestore,
            GCSBackend gcs,
            ActivityManager activity,
            OAuthManager oauth
    ) {
        this.outputDir = outputDir;
        this.firestore = firestore;
        this.gcs = gcs;
        this.activity = activity;
        this.oauth = oauth;
    }

    public Map<String, Object> createBatchJob(
            String sourceType,
            List<Map<String, Object>> itemsInput,
            String model,
            String language,
            boolean uploadToDrive,
            String userEmail,
            String oauthSessionId,
            String driveFolderInput
    ) {
        String ts = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"));
        String jobId = "job_" + ts + "_" + UUID.randomUUID().toString().substring(0, 8);
        String lang = AkkordConfig.normalizeLanguage(language);
        String mdl = (model == null || model.isBlank()) ? AkkordConfig.DEFAULT_MODEL : model;

        Map<String, Object> quota = activity.getTodayQuotaStatus();
        int remainingToday = quota.get("remaining") instanceof Number n ? n.intValue() : 25;
        String nextDay = CloudStore.nextDayKey("");

        File originalsDir = new File(outputDir, "originals");
        originalsDir.mkdirs();

        List<Map<String, Object>> items = new ArrayList<>();
        int queuedNow = 0;
        int deferredNextDay = 0;

        for (int idx = 0; idx < itemsInput.size(); idx++) {
            Map<String, Object> raw = itemsInput.get(idx);
            String itemId = String.format("item_%03d_%s", idx + 1, UUID.randomUUID().toString().substring(0, 6));
            String name = (String) raw.getOrDefault("name", "sheet_" + (idx + 1) + ".pdf");
            String localPath = (String) raw.get("local_path");
            String gcsInputObj = (String) raw.get("gcs_input_object");

            if (localPath != null && !localPath.isBlank()) {
                File lf = new File(localPath);
                if (lf.exists()) {
                    String objName = "jobs/" + jobId + "/inputs/" + lf.getName();
                    gcs.uploadFile(objName, lf, "application/pdf");
                    gcsInputObj = objName;
                    try {
                        Files.copy(lf.toPath(), new File(originalsDir, lf.getName()).toPath(), StandardCopyOption.REPLACE_EXISTING);
                    } catch (IOException ignored) {
                    }
                }
            }

            boolean canRunToday = queuedNow < remainingToday;
            String status = canRunToday ? "queued" : "deferred_next_day";
            String scheduledDate = canRunToday ? CloudStore.todayKey() : nextDay;
            if (canRunToday) queuedNow++;
            else deferredNextDay++;

            Map<String, Object> item = new LinkedHashMap<>();
            item.put("item_id", itemId);
            item.put("index", idx + 1);
            item.put("name", name);
            item.put("source_type", sourceType);
            item.put("drive_file_id", raw.get("drive_file_id"));
            item.put("drive_parent_id", raw.get("drive_parent_id"));
            item.put("web_view_link", raw.get("web_view_link"));
            item.put("gcs_input_object", gcsInputObj);
            item.put("local_path", localPath);
            item.put("status", status);
            item.put("scheduled_date", scheduledDate);
            item.put("mode", null);
            item.put("detected_key", null);
            item.put("accuracy_score", null);
            item.put("annotations_count", 0);
            item.put("summary", "");
            item.put("output_filename", null);
            item.put("output_url", null);
            item.put("original_url", "/api/originals/" + new File(name).getName());
            item.put("gcs_output_object", null);
            item.put("drive_uploaded_id", null);
            item.put("drive_web_view_link", null);
            item.put("token_usage", null);
            item.put("error", null);
            item.put("started_at", null);
            item.put("completed_at", null);
            items.add(item);
        }

        String jobStatus = "running";
        if (queuedNow == 0 && deferredNextDay > 0) jobStatus = "deferred_next_day";
        else if (items.isEmpty()) jobStatus = "completed";

        Map<String, Object> jobDoc = new LinkedHashMap<>();
        jobDoc.put("job_id", jobId);
        jobDoc.put("created_at", CloudStore.nowIso());
        jobDoc.put("updated_at", CloudStore.nowIso());
        jobDoc.put("source_type", sourceType);
        jobDoc.put("drive_folder", driveFolderInput);
        jobDoc.put("model", mdl);
        jobDoc.put("language", lang);
        jobDoc.put("upload_to_drive", uploadToDrive);
        jobDoc.put("user_email", userEmail != null ? userEmail : "");
        jobDoc.put("owner_id", normalizeRecordOwnerId(oauthSessionId, userEmail));
        jobDoc.put("oauth_session_id", oauthSessionId != null ? oauthSessionId : "");
        jobDoc.put("status", jobStatus);
        jobDoc.put("total_files", items.size());
        jobDoc.put("completed_files", 0);
        jobDoc.put("failed_files", 0);
        jobDoc.put("skipped_files", 0);
        jobDoc.put("deferred_files", deferredNextDay);
        jobDoc.put("current_file", null);
        jobDoc.put("next_resume_date", deferredNextDay > 0 ? nextDay : null);
        jobDoc.put("quota_limit", activity.getDailyLimit());
        jobDoc.put("items", items);

        firestore.setDoc("akkord_jobs", jobId, jobDoc);

        List<String> runnableIds = new ArrayList<>();
        for (Map<String, Object> it : items) {
            if ("queued".equals(it.get("status"))) {
                runnableIds.add((String) it.get("item_id"));
            }
        }
        if (!runnableIds.isEmpty()) {
            virtualExecutor.submit(() -> {
                for (String itemId : runnableIds) {
                    if (cancelledJobs.contains(jobId)) break;
                    processJobItem(jobId, itemId);
                }
            });
        }

        return jobDoc;
    }

    @SuppressWarnings("unchecked")
    public synchronized Map<String, Object> processJobItem(String jobId, String itemId) {
        Map<String, Object> jobDoc = firestore.getDoc("akkord_jobs", jobId);
        if (jobDoc == null) return Map.of("error", "Job not found: " + jobId);
        if ("cancelled".equals(jobDoc.get("status"))) return jobDoc;

        List<Map<String, Object>> items = (List<Map<String, Object>>) jobDoc.get("items");
        Map<String, Object> target = null;
        for (Map<String, Object> it : items) {
            if (itemId.equals(it.get("item_id"))) {
                target = it;
                break;
            }
        }
        if (target == null) return Map.of("error", "Item not found: " + itemId);

        if (!activity.checkAndConsumeQuota()) {
            target.put("status", "deferred_next_day");
            target.put("scheduled_date", CloudStore.nextDayKey(""));
            recomputeJobSummary(jobDoc);
            firestore.setDoc("akkord_jobs", jobId, jobDoc);
            return jobDoc;
        }

        target.put("status", "processing");
        target.put("started_at", CloudStore.nowIso());
        jobDoc.put("current_file", target.get("name"));
        jobDoc.put("status", "running");
        firestore.setDoc("akkord_jobs", jobId, jobDoc);

        AkkordConfig cfg = AkkordConfig.fromEnv().withOverrides(
                (String) jobDoc.get("model"),
                (String) jobDoc.get("language"),
                outputDir.getAbsolutePath(),
                Boolean.TRUE.equals(jobDoc.get("upload_to_drive"))
        );

        String itemName = (String) target.get("name");
        String localPath = (String) target.get("local_path");
        SheetFile sheet = new SheetFile(
                target.get("drive_file_id") != null ? (String) target.get("drive_file_id") : itemName,
                itemName,
                localPath,
                (String) target.get("drive_parent_id"),
                (String) target.get("web_view_link")
        );

        try {
            File tmpDir = Files.createTempDirectory("akkord_java_job_").toFile();
            Pipeline pipe = new Pipeline(cfg, "");
            SheetProcessReport rep = pipe.processSingleSheet(sheet, tmpDir);

            String outFname = rep.outputPath() != null && !rep.outputPath().isBlank()
                    ? new File(rep.outputPath()).getName()
                    : null;
            Map<String, Object> tokMap = rep.tokenUsage() != null
                    ? MAPPER.convertValue(rep.tokenUsage(), new TypeReference<>() {})
                    : Map.of();

            target.put("status", "skipped".equals(rep.mode()) ? "skipped" : "completed");
            target.put("mode", rep.mode());
            target.put("detected_key", rep.detectedKey());
            target.put("accuracy_score", rep.accuracyScore());
            target.put("annotations_count", rep.annotationsCount());
            target.put("summary", rep.summary());
            target.put("output_filename", outFname);
            target.put("output_url", outFname != null ? ("/api/outputs/" + outFname + "?job_id=" + jobId) : null);
            target.put("token_usage", tokMap);
            target.put("completed_at", CloudStore.nowIso());

            if (!"skipped".equals(rep.mode())) {
                activity.recordFileProcessed(
                        rep.inputName(), rep.mode(), cfg.model(), cfg.language(),
                        rep.detectedKey(), rep.accuracyScore(), tokMap,
                        (String) jobDoc.get("user_email"), jobId
                );
            }
        } catch (Exception e) {
            target.put("status", "error");
            target.put("error", e.getMessage());
            target.put("completed_at", CloudStore.nowIso());
        }

        recomputeJobSummary(jobDoc);
        firestore.setDoc("akkord_jobs", jobId, jobDoc);
        return jobDoc;
    }

    @SuppressWarnings("unchecked")
    private void recomputeJobSummary(Map<String, Object> jobDoc) {
        List<Map<String, Object>> items = (List<Map<String, Object>>) jobDoc.getOrDefault("items", List.of());
        int completed = 0, failed = 0, skipped = 0, deferred = 0, active = 0;
        for (Map<String, Object> it : items) {
            String st = String.valueOf(it.get("status"));
            switch (st) {
                case "completed" -> completed++;
                case "error" -> failed++;
                case "skipped" -> skipped++;
                case "deferred_next_day" -> deferred++;
                case "processing", "queued" -> active++;
            }
        }
        jobDoc.put("completed_files", completed);
        jobDoc.put("failed_files", failed);
        jobDoc.put("skipped_files", skipped);
        jobDoc.put("deferred_files", deferred);
        jobDoc.put("updated_at", CloudStore.nowIso());
        if (!"cancelled".equals(jobDoc.get("status"))) {
            if (active > 0) jobDoc.put("status", "running");
            else if (deferred > 0) jobDoc.put("status", "deferred_next_day");
            else if (failed > 0 && completed == 0) jobDoc.put("status", "error");
            else jobDoc.put("status", "completed");
        }
    }

    public static String normalizeRecordOwnerId(String rawOwnerId, String userEmail) {
        String owner = rawOwnerId != null ? rawOwnerId.trim() : "";
        if (!owner.isEmpty()) {
            return owner;
        }
        String email = userEmail != null ? userEmail.trim().toLowerCase() : "";
        if (!email.isEmpty()) {
            return "user:" + email;
        }
        return "user:" + AkkordConfig.ADMIN_EMAIL.toLowerCase();
    }

    public static boolean jobBelongsToOwner(Map<String, Object> jobDoc, String viewerOwnerId) {
        if (jobDoc == null || viewerOwnerId == null || viewerOwnerId.isBlank()) {
            return false;
        }
        String jobOwner = normalizeRecordOwnerId(
                jobDoc.get("owner_id") instanceof String s ? s : "",
                jobDoc.get("user_email") instanceof String u ? u : ""
        );
        return jobOwner.equals(viewerOwnerId.trim());
    }

    public Map<String, Object> getJob(String jobId) {
        return firestore.getDoc("akkord_jobs", jobId);
    }

    public List<Map<String, Object>> listJobs(int limit) {
        return listJobs(limit, "");
    }

    public List<Map<String, Object>> listJobs(int limit, String viewerOwnerId) {
        if (viewerOwnerId == null || viewerOwnerId.isBlank()) {
            return List.of();
        }
        List<Map<String, Object>> all = firestore.listDocs("akkord_jobs", 100);
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> doc : all) {
            if (jobBelongsToOwner(doc, viewerOwnerId)) {
                out.add(doc);
                if (out.size() >= limit) break;
            }
        }
        return out;
    }

    public List<Map<String, Object>> getRecentHistory(int limit) {
        return List.of();
    }

    public List<Map<String, Object>> getRecentHistory(int limit, String viewerOwnerId) {
        return List.of();
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> cancelJob(String jobId) {
        cancelledJobs.add(jobId);
        Map<String, Object> jobDoc = firestore.getDoc("akkord_jobs", jobId);
        if (jobDoc == null) return Map.of("error", "Job not found");
        List<Map<String, Object>> items = (List<Map<String, Object>>) jobDoc.getOrDefault("items", List.of());
        for (Map<String, Object> it : items) {
            String st = String.valueOf(it.get("status"));
            if ("queued".equals(st) || "deferred_next_day".equals(st)) {
                it.put("status", "cancelled");
            }
        }
        jobDoc.put("status", "cancelled");
        firestore.setDoc("akkord_jobs", jobId, jobDoc);
        return jobDoc;
    }

    public Map<String, Object> resumeDeferredJobs() {
        return Map.of("status", "ok", "resumed_files", 0, "date", CloudStore.todayKey());
    }

    @SuppressWarnings("unchecked")
    public byte[] buildJobZipBytes(String jobId) throws IOException {
        Map<String, Object> jobDoc = getJob(jobId);
        if (jobDoc == null) return new byte[0];
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        int count = 0;
        try (ZipOutputStream zos = new ZipOutputStream(baos)) {
            List<Map<String, Object>> items = (List<Map<String, Object>>) jobDoc.getOrDefault("items", List.of());
            for (Map<String, Object> it : items) {
                if ("completed".equals(it.get("status"))) {
                    String fname = (String) it.get("output_filename");
                    if (fname != null) {
                        File f = new File(outputDir, fname);
                        if (f.exists()) {
                            zos.putNextEntry(new ZipEntry(fname));
                            zos.write(Files.readAllBytes(f.toPath()));
                            zos.closeEntry();
                            count++;
                        }
                    }
                }
            }
        }
        return count > 0 ? baos.toByteArray() : new byte[0];
    }
}
