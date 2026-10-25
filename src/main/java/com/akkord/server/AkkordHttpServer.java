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

package com.akkord.server;

import com.akkord.config.AkkordConfig;
import com.akkord.drive.DriveConnector;
import com.akkord.jobs.JobQueueManager;
import com.akkord.model.Models.SheetFile;
import com.akkord.model.Models.UserSession;
import com.akkord.oauth.OAuthManager;
import com.akkord.store.CloudStore.ActivityManager;
import com.akkord.store.CloudStore.FirestoreBackend;
import com.akkord.store.CloudStore.GCSBackend;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.File;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;

/**
 * Virtual-Thread-powered HTTP server for the Modern Java 25 Akkord application.
 */
public final class AkkordHttpServer {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final File outputDir;
    private final File originalsDir;
    private final File staticDir;
    private final FirestoreBackend firestore;
    private final GCSBackend gcs;
    private final ActivityManager activity;
    private final OAuthManager oauth;
    private final JobQueueManager jobQueue;

    public AkkordHttpServer(File outputDir, File staticDir) {
        this.outputDir = outputDir != null ? outputDir : new File(AkkordConfig.defaultOutputDir());
        this.outputDir.mkdirs();
        this.originalsDir = new File(this.outputDir, "originals");
        this.originalsDir.mkdirs();
        this.staticDir = staticDir != null ? staticDir : resolveStaticDir();
        this.firestore = new FirestoreBackend("", new File(this.outputDir, "_firestore_mirror"));
        this.gcs = new GCSBackend("", new File(this.outputDir, "_gcs_mirror"));
        this.activity = new ActivityManager(this.outputDir, this.firestore);
        this.oauth = new OAuthManager(this.outputDir, this.firestore);
        this.jobQueue = new JobQueueManager(this.outputDir, this.firestore, this.gcs, this.activity, this.oauth);
    }

    private static File resolveStaticDir() {
        for (String c : List.of("akkord/static", "../akkord/static", "/app/akkord/static")) {
            File f = new File(c);
            if (f.exists() && f.isDirectory()) return f.getAbsoluteFile();
        }
        return new File("akkord/static");
    }

    public HttpServer start(int port) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", port), 0);
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
        server.createContext("/", this::dispatch);
        server.start();
        return server;
    }

    public Map<String, Object> buildConfigPayload(UserSession user) {
        Map<String, Object> userDict = user != null
                ? user.toPublicDict(AkkordConfig.ADMIN_EMAIL)
                : Map.of("authenticated", false);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("default_model", AkkordConfig.DEFAULT_MODEL);
        res.put("available_models", AkkordConfig.AVAILABLE_MODELS);
        res.put("default_language", AkkordConfig.DEFAULT_LANGUAGE);
        res.put("languages", List.of("fr", "en"));
        res.put("default_project", AkkordConfig.DEFAULT_GCP_PROJECT);
        res.put("default_location", AkkordConfig.DEFAULT_GCP_LOCATION);
        res.put("oauth_configured", oauth.isConfigured());
        res.put("user", userDict);
        res.put("quota", activity.getTodayQuotaStatus());
        res.put("daily_report_hour", String.format("%02d:00", activity.getReportHourLocal()));
        res.put("daily_report_email", activity.getReportEmail());
        res.put("active_job", null);
        res.put("recent_history", jobQueue.getRecentHistory(25));
        res.put("runtime_engine", "java-25-virtual-threads");
        return res;
    }

    private void dispatch(HttpExchange ex) throws IOException {
        String path = ex.getRequestURI().getPath();
        try {
            switch (path) {
                case "/" -> serveStaticFile(ex, new File(staticDir, "index.html"));
                case "/api/config" -> sendJson(ex, 200, buildConfigPayload(currentUser(ex)));
                case "/api/auth/status" -> {
                    UserSession u = currentUser(ex);
                    if (u != null) {
                        Map<String, Object> m = new LinkedHashMap<>(u.toPublicDict(AkkordConfig.ADMIN_EMAIL));
                        m.put("oauth_configured", oauth.isConfigured());
                        sendJson(ex, 200, m);
                    } else {
                        sendJson(ex, 200, Map.of("authenticated", false, "oauth_configured", oauth.isConfigured()));
                    }
                }
                case "/api/admin/usage" -> sendJson(ex, 200, activity.getUsageSummary(14));
                case "/api/admin/reset-quota" -> {
                    Map<String, Object> newQuota = activity.resetDailyQuota("", "admin");
                    sendJson(ex, 200, Map.of("status", "quota_reset", "quota", newQuota, "usage", activity.getUsageSummary(14)));
                }
                case "/api/daily-report/preview" -> sendJson(ex, 200, activity.buildDailyReportEmail(""));
                case "/api/daily-report/send" -> sendJson(ex, 200, activity.sendDailyReportEmail("", false, ""));
                case "/api/scan-folder" -> handleScanFolder(ex);
                case "/api/jobs/drive" -> handleCreateDriveJob(ex);
                case "/api/jobs" -> sendJson(ex, 200, Map.of(
                        "jobs", jobQueue.listJobs(20),
                        "recent_history", jobQueue.getRecentHistory(30),
                        "quota", activity.getTodayQuotaStatus()
                ));
                default -> {
                    if (path.startsWith("/static/")) {
                        String rel = path.substring("/static/".length());
                        if (!rel.contains("..")) {
                            serveStaticFile(ex, new File(staticDir, rel));
                            return;
                        }
                    } else if (path.startsWith("/api/jobs/")) {
                        handleJobSubroute(ex, path);
                        return;
                    } else if (path.startsWith("/api/outputs/")) {
                        String fname = new File(path.substring("/api/outputs/".length())).getName();
                        serveStaticFile(ex, new File(outputDir, fname));
                        return;
                    } else if (path.startsWith("/api/originals/")) {
                        String fname = new File(path.substring("/api/originals/".length())).getName();
                        File f = new File(originalsDir, fname);
                        if (!f.exists()) f = new File("samples", fname);
                        serveStaticFile(ex, f);
                        return;
                    }
                    sendJson(ex, 404, Map.of("detail", "Not found: " + path));
                }
            }
        } catch (Exception e) {
            sendJson(ex, 500, Map.of("detail", e.getMessage() != null ? e.getMessage() : "Internal error"));
        }
    }

    private void handleScanFolder(HttpExchange ex) throws IOException {
        Map<String, Object> req = MAPPER.readValue(ex.getRequestBody(), new TypeReference<>() {});
        String folder = String.valueOf(req.getOrDefault("drive_folder", "")).trim();
        if (folder.isEmpty()) {
            sendJson(ex, 400, Map.of("detail", "drive_folder cannot be empty"));
            return;
        }
        DriveConnector conn = new DriveConnector("");
        List<SheetFile> files = conn.listPdfs(folder);
        sendJson(ex, 200, Map.of(
                "folder", folder,
                "count", files.size(),
                "files", files,
                "quota", activity.getTodayQuotaStatus()
        ));
    }

    private void handleCreateDriveJob(HttpExchange ex) throws IOException {
        Map<String, Object> req = MAPPER.readValue(ex.getRequestBody(), new TypeReference<>() {});
        String folder = String.valueOf(req.getOrDefault("drive_folder", "")).trim();
        String model = String.valueOf(req.getOrDefault("model", AkkordConfig.DEFAULT_MODEL));
        String lang = String.valueOf(req.getOrDefault("language", AkkordConfig.DEFAULT_LANGUAGE));
        boolean upload = Boolean.TRUE.equals(req.get("upload_to_drive"));

        DriveConnector conn = new DriveConnector("");
        List<SheetFile> sheets = conn.listPdfs(folder);
        List<Map<String, Object>> items = new ArrayList<>();
        for (SheetFile s : sheets) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("name", s.name());
            m.put("drive_file_id", s.id());
            m.put("drive_parent_id", s.driveParentId());
            m.put("web_view_link", s.webViewLink());
            m.put("local_path", s.localPath());
            items.add(m);
        }
        Map<String, Object> jobDoc = jobQueue.createBatchJob("drive", items, model, lang, upload, "", "", folder);
        sendJson(ex, 200, Map.of("job", jobDoc, "quota", activity.getTodayQuotaStatus()));
    }

    private void handleJobSubroute(HttpExchange ex, String path) throws IOException {
        String[] parts = path.substring("/api/jobs/".length()).split("/");
        String jobId = parts[0];
        if (parts.length == 1) {
            Map<String, Object> job = jobQueue.getJob(jobId);
            if (job == null) {
                sendJson(ex, 404, Map.of("detail", "Job not found"));
                return;
            }
            sendJson(ex, 200, Map.of("job", job, "quota", activity.getTodayQuotaStatus()));
        } else if ("cancel".equals(parts[1])) {
            sendJson(ex, 200, Map.of("job", jobQueue.cancelJob(jobId)));
        } else if ("download-zip".equals(parts[1])) {
            byte[] zipBytes = jobQueue.buildJobZipBytes(jobId);
            ex.getResponseHeaders().set("Content-Type", "application/zip");
            ex.getResponseHeaders().set("Content-Disposition", "attachment; filename=\"akkord-" + jobId + ".zip\"");
            ex.sendResponseHeaders(200, zipBytes.length);
            try (OutputStream os = ex.getResponseBody()) {
                os.write(zipBytes);
            }
        }
    }

    private UserSession currentUser(HttpExchange ex) {
        List<String> cookies = ex.getRequestHeaders().get("Cookie");
        if (cookies == null) return null;
        for (String header : cookies) {
            for (String part : header.split(";")) {
                String[] kv = part.trim().split("=", 2);
                if (kv.length == 2 && AkkordConfig.SESSION_COOKIE_NAME.equals(kv[0])) {
                    return oauth.getSession(kv[1]);
                }
            }
        }
        return null;
    }

    private static void serveStaticFile(HttpExchange ex, File file) throws IOException {
        if (!file.exists() || !file.isFile()) {
            sendJson(ex, 404, Map.of("detail", "File not found"));
            return;
        }
        String name = file.getName().toLowerCase();
        String mime = "application/octet-stream";
        if (name.endsWith(".html")) mime = "text/html; charset=utf-8";
        else if (name.endsWith(".css")) mime = "text/css; charset=utf-8";
        else if (name.endsWith(".js")) mime = "application/javascript; charset=utf-8";
        else if (name.endsWith(".pdf")) mime = "application/pdf";
        else if (name.endsWith(".png")) mime = "image/png";
        else if (name.endsWith(".svg")) mime = "image/svg+xml";

        byte[] data = Files.readAllBytes(file.toPath());
        ex.getResponseHeaders().set("Content-Type", mime);
        ex.sendResponseHeaders(200, data.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(data);
        }
    }

    private static void sendJson(HttpExchange ex, int status, Object payload) throws IOException {
        byte[] bytes = MAPPER.writeValueAsString(payload).getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        ex.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(bytes);
        }
    }
}
