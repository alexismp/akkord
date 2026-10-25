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

package com.akkord.store;

import com.akkord.config.AkkordConfig;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;

import java.io.File;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.time.Duration;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Base64;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Cloud Firestore v1, Cloud Storage (GCS) v1, and Daily Quota/Activity Manager (25 PDFs/day in Europe/Paris).
 */
public final class CloudStore {
    private static final ObjectMapper MAPPER = new ObjectMapper().enable(SerializationFeature.INDENT_OUTPUT);
    public static final ZoneId PARIS_ZONE = ZoneId.of("Europe/Paris");
    public static final ADCTokenProvider GLOBAL_ADC = new ADCTokenProvider();

    public static String todayKey() {
        return LocalDate.now(PARIS_ZONE).format(DateTimeFormatter.ISO_LOCAL_DATE);
    }

    public static String nextDayKey(String fromDate) {
        LocalDate base = (fromDate == null || fromDate.isBlank())
                ? LocalDate.now(PARIS_ZONE)
                : LocalDate.parse(fromDate, DateTimeFormatter.ISO_LOCAL_DATE);
        return base.plusDays(1).format(DateTimeFormatter.ISO_LOCAL_DATE);
    }

    public static String nowIso() {
        return ZonedDateTime.now(PARIS_ZONE).format(DateTimeFormatter.ISO_OFFSET_DATE_TIME);
    }

    public static final class ADCTokenProvider {
        private String token = "";
        private long expiresAtMillis = 0L;
        private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofMillis(1500)).build();

        public synchronized String getAccessToken() {
            if (!token.isEmpty() && System.currentTimeMillis() < expiresAtMillis) {
                return token;
            }
            String envTok = System.getenv("GOOGLE_OAUTH_ACCESS_TOKEN");
            if (envTok != null && !envTok.isBlank()) {
                token = envTok.trim();
                expiresAtMillis = System.currentTimeMillis() + 1800_000L;
                return token;
            }
            if ("1".equals(System.getenv("AKKORD_DISABLE_REMOTE_GCP"))) {
                return "";
            }
            try {
                HttpRequest req = HttpRequest.newBuilder()
                        .uri(URI.create("http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"))
                        .timeout(Duration.ofMillis(1500))
                        .header("Metadata-Flavor", "Google")
                        .GET()
                        .build();
                HttpResponse<String> resp = client.send(req, HttpResponse.BodyHandlers.ofString());
                if (resp.statusCode() == 200) {
                    JsonNode node = MAPPER.readTree(resp.body());
                    String at = node.path("access_token").asText("");
                    int exp = node.path("expires_in").asInt(1800);
                    if (!at.isEmpty()) {
                        token = at;
                        expiresAtMillis = System.currentTimeMillis() + Math.max(60, exp - 60) * 1000L;
                        return token;
                    }
                }
            } catch (Exception ignored) {
            }
            for (String[] cmd : new String[][]{
                    {"gcloud", "auth", "application-default", "print-access-token"},
                    {"gcloud", "auth", "print-access-token"}
            }) {
                try {
                    Process p = new ProcessBuilder(cmd).redirectErrorStream(true).start();
                    String out = new String(p.getInputStream().readAllBytes(), StandardCharsets.UTF_8).trim();
                    if (p.waitFor() == 0 && !out.isEmpty() && !out.contains("ERROR")) {
                        token = out;
                        expiresAtMillis = System.currentTimeMillis() + 2400_000L;
                        return token;
                    }
                } catch (Exception ignored) {
                }
            }
            return "";
        }
    }

    public static Map<String, Object> toFirestoreValue(Object val) {
        if (val == null) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("nullValue", null);
            return m;
        }
        return switch (val) {
            case Boolean b -> Map.of("booleanValue", b);
            case Integer i -> Map.of("integerValue", String.valueOf(i));
            case Long l -> Map.of("integerValue", String.valueOf(l));
            case Double d -> {
                if (Math.rint(d) == d && !Double.isInfinite(d)) {
                    yield Map.of("integerValue", String.valueOf(d.longValue()));
                }
                yield Map.of("doubleValue", d);
            }
            case Number n -> Map.of("doubleValue", n.doubleValue());
            case String s -> Map.of("stringValue", s);
            case List<?> list -> {
                List<Map<String, Object>> vals = new ArrayList<>(list.size());
                for (Object item : list) {
                    vals.add(toFirestoreValue(item));
                }
                yield Map.of("arrayValue", Map.of("values", vals));
            }
            case Map<?, ?> map -> {
                Map<String, Object> fields = new LinkedHashMap<>();
                for (Map.Entry<?, ?> e : map.entrySet()) {
                    fields.put(String.valueOf(e.getKey()), toFirestoreValue(e.getValue()));
                }
                yield Map.of("mapValue", Map.of("fields", fields));
            }
            default -> {
                Map<String, Object> converted = MAPPER.convertValue(val, new TypeReference<>() {});
                yield toFirestoreValue(converted);
            }
        };
    }

    @SuppressWarnings("unchecked")
    public static Object fromFirestoreValue(Map<String, Object> fv) {
        if (fv == null || fv.containsKey("nullValue")) return null;
        if (fv.containsKey("booleanValue")) return fv.get("booleanValue");
        if (fv.containsKey("integerValue")) {
            Object iv = fv.get("integerValue");
            try {
                return Integer.parseInt(String.valueOf(iv));
            } catch (NumberFormatException e) {
                return 0;
            }
        }
        if (fv.containsKey("doubleValue")) {
            Object dv = fv.get("doubleValue");
            return dv instanceof Number n ? n.doubleValue() : Double.parseDouble(String.valueOf(dv));
        }
        if (fv.containsKey("stringValue")) return String.valueOf(fv.get("stringValue"));
        if (fv.containsKey("arrayValue")) {
            Map<String, Object> av = (Map<String, Object>) fv.get("arrayValue");
            List<Map<String, Object>> vals = (List<Map<String, Object>>) av.getOrDefault("values", List.of());
            List<Object> out = new ArrayList<>(vals.size());
            for (Map<String, Object> item : vals) {
                out.add(fromFirestoreValue(item));
            }
            return out;
        }
        if (fv.containsKey("mapValue")) {
            Map<String, Object> mv = (Map<String, Object>) fv.get("mapValue");
            Map<String, Object> fields = (Map<String, Object>) mv.getOrDefault("fields", Map.of());
            Map<String, Object> out = new LinkedHashMap<>();
            for (Map.Entry<String, Object> e : fields.entrySet()) {
                out.put(e.getKey(), fromFirestoreValue((Map<String, Object>) e.getValue()));
            }
            return out;
        }
        return null;
    }

    public static final class FirestoreBackend {
        private final String projectId;
        private final String databaseId;
        private final File localDir;
        private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(8)).build();

        public FirestoreBackend(String projectId, File localDir) {
            this.projectId = (projectId == null || projectId.isBlank())
                    ? AkkordConfig.envOr("AKKORD_GCP_PROJECT", AkkordConfig.DEFAULT_GCP_PROJECT)
                    : projectId;
            this.databaseId = AkkordConfig.envOr("AKKORD_FIRESTORE_DB", "(default)");
            this.localDir = localDir != null ? localDir : new File(AkkordConfig.defaultOutputDir(), "_firestore_mirror");
            this.localDir.mkdirs();
        }

        private String baseUrl() {
            return String.format("https://firestore.googleapis.com/v1/projects/%s/databases/%s/documents", projectId, databaseId);
        }

        private File localDocFile(String collection, String docId) {
            File col = new File(localDir, collection);
            col.mkdirs();
            String safe = docId.replace("/", "_").replace("..", "_");
            return new File(col, safe + ".json");
        }

        public synchronized boolean setDoc(String collection, String docId, Map<String, Object> data) {
            try {
                MAPPER.writeValue(localDocFile(collection, docId), data);
            } catch (Exception ignored) {
            }
            if ("1".equals(System.getenv("AKKORD_DISABLE_FIRESTORE"))) {
                return false;
            }
            String token = GLOBAL_ADC.getAccessToken();
            if (token.isEmpty()) return false;
            try {
                Map<String, Object> fields = new LinkedHashMap<>();
                for (Map.Entry<String, Object> e : data.entrySet()) {
                    fields.put(e.getKey(), toFirestoreValue(e.getValue()));
                }
                String body = MAPPER.writeValueAsString(Map.of("fields", fields));
                String url = baseUrl() + "/" + collection + "/" + URLEncoder.encode(docId, StandardCharsets.UTF_8);
                HttpRequest req = HttpRequest.newBuilder()
                        .uri(URI.create(url))
                        .timeout(Duration.ofSeconds(8))
                        .header("Authorization", "Bearer " + token)
                        .header("Content-Type", "application/json")
                        .method("PATCH", HttpRequest.BodyPublishers.ofString(body))
                        .build();
                HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
                return resp.statusCode() >= 200 && resp.statusCode() < 300;
            } catch (Exception e) {
                return false;
            }
        }

        @SuppressWarnings("unchecked")
        public synchronized Map<String, Object> getDoc(String collection, String docId) {
            if (!"1".equals(System.getenv("AKKORD_DISABLE_FIRESTORE"))) {
                String token = GLOBAL_ADC.getAccessToken();
                if (!token.isEmpty()) {
                    try {
                        String url = baseUrl() + "/" + collection + "/" + URLEncoder.encode(docId, StandardCharsets.UTF_8);
                        HttpRequest req = HttpRequest.newBuilder()
                                .uri(URI.create(url))
                                .timeout(Duration.ofSeconds(8))
                                .header("Authorization", "Bearer " + token)
                                .GET()
                                .build();
                        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
                        if (resp.statusCode() == 200) {
                            Map<String, Object> raw = MAPPER.readValue(resp.body(), new TypeReference<>() {});
                            Map<String, Map<String, Object>> fields = (Map<String, Map<String, Object>>) raw.get("fields");
                            if (fields != null) {
                                Map<String, Object> out = new LinkedHashMap<>();
                                for (Map.Entry<String, Map<String, Object>> e : fields.entrySet()) {
                                    out.put(e.getKey(), fromFirestoreValue(e.getValue()));
                                }
                                return out;
                            }
                        }
                    } catch (Exception ignored) {
                    }
                }
            }
            File f = localDocFile(collection, docId);
            if (!f.exists()) return null;
            try {
                return MAPPER.readValue(f, new TypeReference<>() {});
            } catch (Exception e) {
                return null;
            }
        }

        public synchronized void deleteDoc(String collection, String docId) {
            File f = localDocFile(collection, docId);
            if (f.exists()) f.delete();
        }

        public synchronized List<Map<String, Object>> listDocs(String collection, int limit) {
            File col = new File(localDir, collection);
            File[] files = col.listFiles((d, name) -> name.endsWith(".json"));
            if (files == null || files.length == 0) return List.of();
            Arrays.sort(files, Comparator.comparingLong(File::lastModified).reversed());
            List<Map<String, Object>> out = new ArrayList<>();
            for (int i = 0; i < Math.min(limit, files.length); i++) {
                try {
                    out.add(MAPPER.readValue(files[i], new TypeReference<>() {}));
                } catch (Exception ignored) {
                }
            }
            return out;
        }
    }

    public static final class GCSBackend {
        private final String bucketName;
        private final File localDir;
        private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(15)).build();

        public GCSBackend(String bucketName, File localDir) {
            this.bucketName = (bucketName == null || bucketName.isBlank())
                    ? AkkordConfig.envOr("AKKORD_GCS_BUCKET", AkkordConfig.DEFAULT_GCS_BUCKET)
                    : bucketName;
            this.localDir = localDir != null ? localDir : new File(AkkordConfig.defaultOutputDir(), "_gcs_mirror");
            this.localDir.mkdirs();
        }

        private File localBlobFile(String objectName) {
            String safe = objectName.replaceAll("^/+", "").replace("..", "_");
            File target = new File(localDir, safe);
            if (target.getParentFile() != null) target.getParentFile().mkdirs();
            return target;
        }

        public String uploadFile(String objectName, File file, String contentType) {
            try {
                byte[] data = Files.readAllBytes(file.toPath());
                File local = localBlobFile(objectName);
                Files.write(local.toPath(), data);
                if (!"1".equals(System.getenv("AKKORD_DISABLE_GCS"))) {
                    String token = GLOBAL_ADC.getAccessToken();
                    if (!token.isEmpty()) {
                        String url = String.format("https://storage.googleapis.com/upload/storage/v1/b/%s/o?uploadType=media&name=%s",
                                URLEncoder.encode(bucketName, StandardCharsets.UTF_8),
                                URLEncoder.encode(objectName, StandardCharsets.UTF_8));
                        HttpRequest req = HttpRequest.newBuilder()
                                .uri(URI.create(url))
                                .timeout(Duration.ofSeconds(30))
                                .header("Authorization", "Bearer " + token)
                                .header("Content-Type", contentType != null ? contentType : "application/pdf")
                                .POST(HttpRequest.BodyPublishers.ofByteArray(data))
                                .build();
                        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
                        if (resp.statusCode() >= 200 && resp.statusCode() < 300) {
                            return "gs://" + bucketName + "/" + objectName;
                        }
                    }
                }
                return local.getAbsolutePath();
            } catch (Exception e) {
                return "";
            }
        }

        public byte[] downloadBytes(String objectName) {
            File local = localBlobFile(objectName);
            if (local.exists()) {
                try {
                    return Files.readAllBytes(local.toPath());
                } catch (Exception ignored) {
                }
            }
            return null;
        }
    }

    public static final class ActivityManager {
        private final File storageFile;
        private int dailyLimit;
        private final String reportEmail;
        private final int reportHourLocal;
        private final FirestoreBackend firestore;

        public ActivityManager(File outputDir, FirestoreBackend firestore) {
            outputDir.mkdirs();
            this.storageFile = new File(outputDir, "activity_usage.json");
            this.dailyLimit = AkkordConfig.DAILY_FILE_LIMIT;
            this.reportEmail = AkkordConfig.envOr("AKKORD_REPORT_EMAIL", AkkordConfig.ADMIN_EMAIL);
            this.reportHourLocal = AkkordConfig.DAILY_REPORT_HOUR;
            this.firestore = firestore;
        }

        public int getDailyLimit() {
            return dailyLimit;
        }

        public void setDailyLimit(int dailyLimit) {
            this.dailyLimit = dailyLimit;
        }

        public String getReportEmail() {
            return reportEmail;
        }

        public int getReportHourLocal() {
            return reportHourLocal;
        }

        private Map<String, Object> newDayEntry(String dateKey) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("date", dateKey);
            m.put("files_processed", 0);
            m.put("quota_reset_baseline", 0);
            m.put("quota_resets", new ArrayList<>());
            m.put("input_tokens", 0);
            m.put("output_tokens", 0);
            m.put("thinking_tokens", 0);
            m.put("cached_tokens", 0);
            m.put("total_tokens", 0);
            m.put("estimated_cost_usd", 0.0);
            m.put("estimated_cost_eur", 0.0);
            m.put("report_sent", false);
            m.put("report_sent_at", null);
            m.put("events", new ArrayList<>());
            return m;
        }

        @SuppressWarnings("unchecked")
        private Map<String, Object> loadStore() {
            Map<String, Object> storeData = new LinkedHashMap<>();
            storeData.put("days", new LinkedHashMap<String, Object>());
            if (storageFile.exists()) {
                try {
                    Map<String, Object> parsed = MAPPER.readValue(storageFile, new TypeReference<>() {});
                    if (parsed.get("days") instanceof Map<?, ?>) {
                        storeData = parsed;
                    }
                } catch (Exception ignored) {
                }
            }
            Map<String, Object> days = (Map<String, Object>) storeData.get("days");
            String tKey = todayKey();
            Map<String, Object> fsDay = firestore.getDoc("akkord_daily_usage", tKey);
            if (fsDay != null && fsDay.containsKey("files_processed")) {
                days.put(tKey, fsDay);
            }
            return storeData;
        }

        @SuppressWarnings("unchecked")
        private void saveStore(Map<String, Object> storeData) {
            try {
                MAPPER.writeValue(storageFile, storeData);
            } catch (Exception ignored) {
            }
            Map<String, Object> days = (Map<String, Object>) storeData.get("days");
            String tKey = todayKey();
            if (days.get(tKey) instanceof Map<?, ?> day) {
                firestore.setDoc("akkord_daily_usage", tKey, (Map<String, Object>) day);
            }
        }

        @SuppressWarnings("unchecked")
        private Map<String, Object> ensureDay(Map<String, Object> storeData, String dateKey) {
            Map<String, Object> days = (Map<String, Object>) storeData.get("days");
            if (days.get(dateKey) instanceof Map<?, ?> existing) {
                return (Map<String, Object>) existing;
            }
            Map<String, Object> entry = newDayEntry(dateKey);
            days.put(dateKey, entry);
            return entry;
        }

        private static int toInt(Object o) {
            if (o instanceof Number n) return n.intValue();
            if (o instanceof String s) {
                try { return Integer.parseInt(s); } catch (NumberFormatException ignored) {}
            }
            return 0;
        }

        private static double toDouble(Object o) {
            if (o instanceof Number n) return n.doubleValue();
            if (o instanceof String s) {
                try { return Double.parseDouble(s); } catch (NumberFormatException ignored) {}
            }
            return 0.0;
        }

        public synchronized Map<String, Object> getTodayQuotaStatus() {
            Map<String, Object> storeData = loadStore();
            String tKey = todayKey();
            Map<String, Object> day = ensureDay(storeData, tKey);
            int total = toInt(day.get("files_processed"));
            int baseline = toInt(day.get("quota_reset_baseline"));
            int used = Math.max(0, total - baseline);
            int rem = Math.max(0, dailyLimit - used);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("date", tKey);
            res.put("used", used);
            res.put("total_processed_today", total);
            res.put("quota_reset_baseline", baseline);
            res.put("limit", dailyLimit);
            res.put("remaining", rem);
            res.put("exceeded", used >= dailyLimit);
            return res;
        }

        public synchronized boolean checkAndConsumeQuota() {
            Map<String, Object> q = getTodayQuotaStatus();
            return !Boolean.TRUE.equals(q.get("exceeded"));
        }

        @SuppressWarnings("unchecked")
        public synchronized Map<String, Object> resetDailyQuota(String dateKey, String resetBy) {
            String dKey = (dateKey == null || dateKey.isBlank()) ? todayKey() : dateKey;
            Map<String, Object> storeData = loadStore();
            Map<String, Object> day = ensureDay(storeData, dKey);
            int total = toInt(day.get("files_processed"));
            day.put("quota_reset_baseline", total);
            List<Object> resets = (List<Object>) day.computeIfAbsent("quota_resets", k -> new ArrayList<>());
            resets.add(Map.of(
                    "timestamp", nowIso(),
                    "reset_by", resetBy != null ? resetBy : "admin",
                    "baseline_set_to", total
            ));
            saveStore(storeData);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("date", dKey);
            res.put("used", 0);
            res.put("total_processed_today", total);
            res.put("quota_reset_baseline", total);
            res.put("limit", dailyLimit);
            res.put("remaining", dailyLimit);
            res.put("exceeded", false);
            return res;
        }

        @SuppressWarnings("unchecked")
        public synchronized Map<String, Object> recordFileProcessed(
                String filename,
                String mode,
                String model,
                String language,
                String detectedKey,
                int accuracyScore,
                Map<String, Object> tokenUsage,
                String userEmail,
                String jobId
        ) {
            Map<String, Object> storeData = loadStore();
            String tKey = todayKey();
            Map<String, Object> day = ensureDay(storeData, tKey);

            int inTok = tokenUsage != null ? toInt(tokenUsage.get("input_tokens")) : 0;
            int outTok = tokenUsage != null ? toInt(tokenUsage.get("output_tokens")) : 0;
            int thinkTok = tokenUsage != null ? toInt(tokenUsage.get("thinking_tokens")) : 0;
            int cacheTok = tokenUsage != null ? toInt(tokenUsage.get("cached_tokens")) : 0;
            int totalTok = tokenUsage != null ? toInt(tokenUsage.get("total_tokens")) : 0;
            if (totalTok == 0) totalTok = inTok + outTok + thinkTok;
            double costUsd = tokenUsage != null ? toDouble(tokenUsage.get("estimated_cost_usd")) : 0.0;
            double costEur = tokenUsage != null ? toDouble(tokenUsage.get("estimated_cost_eur")) : 0.0;

            day.put("files_processed", toInt(day.get("files_processed")) + 1);
            day.put("input_tokens", toInt(day.get("input_tokens")) + inTok);
            day.put("output_tokens", toInt(day.get("output_tokens")) + outTok);
            day.put("thinking_tokens", toInt(day.get("thinking_tokens")) + thinkTok);
            day.put("cached_tokens", toInt(day.get("cached_tokens")) + cacheTok);
            day.put("total_tokens", toInt(day.get("total_tokens")) + totalTok);
            day.put("estimated_cost_usd", Math.round((toDouble(day.get("estimated_cost_usd")) + costUsd) * 1e6) / 1e6);
            day.put("estimated_cost_eur", Math.round((toDouble(day.get("estimated_cost_eur")) + costEur) * 1e6) / 1e6);

            Map<String, Object> ev = new LinkedHashMap<>();
            ev.put("timestamp", nowIso());
            ev.put("filename", filename);
            ev.put("mode", mode);
            ev.put("model", model);
            ev.put("language", language);
            ev.put("detected_key", detectedKey);
            ev.put("accuracy_score", accuracyScore);
            ev.put("user_email", userEmail != null ? userEmail : "");
            ev.put("job_id", jobId != null ? jobId : "");
            ev.put("input_tokens", inTok);
            ev.put("output_tokens", outTok);
            ev.put("thinking_tokens", thinkTok);
            ev.put("cached_tokens", cacheTok);
            ev.put("total_tokens", totalTok);
            ev.put("estimated_cost_usd", Math.round(costUsd * 1e6) / 1e6);
            ev.put("estimated_cost_eur", Math.round(costEur * 1e6) / 1e6);

            List<Object> events = (List<Object>) day.computeIfAbsent("events", k -> new ArrayList<>());
            events.add(ev);
            saveStore(storeData);
            return ev;
        }

        @SuppressWarnings("unchecked")
        public synchronized Map<String, Object> getUsageSummary(int daysLimit) {
            Map<String, Object> storeData = loadStore();
            Map<String, Object> days = (Map<String, Object>) storeData.get("days");
            String tKey = todayKey();
            Map<String, Object> todayEntry = ensureDay(storeData, tKey);

            List<String> keys = new ArrayList<>(days.keySet());
            keys.sort(Comparator.reverseOrder());
            if (keys.size() > daysLimit) keys = keys.subList(0, daysLimit);

            List<Map<String, Object>> recentDays = new ArrayList<>();
            for (String k : keys) {
                if (days.get(k) instanceof Map<?, ?> d) {
                    recentDays.add((Map<String, Object>) d);
                }
            }

            int totalFiles = 0;
            int totalTokens = 0;
            double totalUsd = 0.0;
            double totalEur = 0.0;
            for (Object v : days.values()) {
                if (v instanceof Map<?, ?> d) {
                    totalFiles += toInt(d.get("files_processed"));
                    totalTokens += toInt(d.get("total_tokens"));
                    totalUsd += toDouble(d.get("estimated_cost_usd"));
                    totalEur += toDouble(d.get("estimated_cost_eur"));
                }
            }

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("today", todayEntry);
            res.put("daily_limit", dailyLimit);
            res.put("report_email", reportEmail);
            res.put("report_hour", String.format("%02d:00", reportHourLocal));
            res.put("quota", getTodayQuotaStatus());
            res.put("totals", Map.of(
                    "files_processed", totalFiles,
                    "total_tokens", totalTokens,
                    "estimated_cost_usd", Math.round(totalUsd * 1e4) / 1e4,
                    "estimated_cost_eur", Math.round(totalEur * 1e4) / 1e4
            ));
            res.put("recent_days", recentDays);
            return res;
        }

        public synchronized Map<String, Object> buildDailyReportEmail(String dateKey) {
            String dKey = (dateKey == null || dateKey.isBlank()) ? todayKey() : dateKey;
            Map<String, Object> storeData = loadStore();
            Map<String, Object> day = ensureDay(storeData, dKey);
            int files = toInt(day.get("files_processed"));
            int totalTok = toInt(day.get("total_tokens"));
            double costEur = toDouble(day.get("estimated_cost_eur"));
            String subject = String.format("[Akkord] Rapport d'activite quotidien — %s (%d/%d partitions)", dKey, files, dailyLimit);
            String text = String.format("Akkord (%s) : %d/%d partitions, %d tokens, %.4f EUR", dKey, files, dailyLimit, totalTok, costEur);
            String html = String.format("<html><body><h2>%s</h2><p>%s</p></body></html>", subject, text);
            return Map.of(
                    "date", dKey,
                    "recipient", reportEmail,
                    "subject", subject,
                    "text_preview", text,
                    "html_preview", html
            );
        }

        public synchronized Map<String, Object> sendDailyReportEmail(String dateKey, boolean force, String oauthAccessToken) {
            Map<String, Object> preview = new LinkedHashMap<>(buildDailyReportEmail(dateKey));
            preview.put("status", "preview_only");
            preview.put("delivered", false);
            return preview;
        }
    }
}
