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

package com.akkord.drive;

import com.akkord.model.Models.SheetFile;
import com.akkord.store.CloudStore;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Google Drive API v3 and local filesystem connector for Modern Java 25.
 */
public final class DriveConnector {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Pattern FOLDER_RE = Pattern.compile("/folders/([a-zA-Z0-9_-]+)");
    private static final Pattern FILE_RE = Pattern.compile("/file/d/([a-zA-Z0-9_-]+)");
    private static final Pattern ID_PARAM_RE = Pattern.compile("[?&]id=([a-zA-Z0-9_-]+)");

    public static final List<String> GENERATED_SUFFIXES = List.of(
            "-avec-accords.pdf",
            "-analyse-accords.pdf",
            "-with-chords.pdf",
            "-chord-analysis.pdf"
    );

    private final String oauthAccessToken;
    private final HttpClient http;

    public DriveConnector(String oauthAccessToken) {
        this.oauthAccessToken = oauthAccessToken != null ? oauthAccessToken.trim() : "";
        this.http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(15)).build();
    }

    public static boolean isGeneratedOutput(String filename) {
        if (filename == null) return false;
        String lower = filename.toLowerCase();
        for (String suf : GENERATED_SUFFIXES) {
            if (lower.endsWith(suf)) return true;
        }
        return false;
    }

    public static String extractFolderId(String input) {
        if (input == null) return "";
        String cleaned = input.trim();
        for (Pattern p : List.of(FOLDER_RE, FILE_RE, ID_PARAM_RE)) {
            Matcher m = p.matcher(cleaned);
            if (m.find()) return m.group(1);
        }
        return cleaned;
    }

    private String bearerToken() {
        if (!oauthAccessToken.isEmpty()) return oauthAccessToken;
        return CloudStore.GLOBAL_ADC.getAccessToken();
    }

    public List<SheetFile> listPdfs(String folderOrPath) throws IOException {
        File local = new File(folderOrPath.trim());
        if (local.exists()) {
            if (local.isFile() && local.getName().toLowerCase().endsWith(".pdf")) {
                return List.of(new SheetFile(local.getName(), local.getName(), local.getAbsolutePath(), null, null));
            }
            if (local.isDirectory()) {
                File[] files = local.listFiles((d, name) -> name.toLowerCase().endsWith(".pdf") && !isGeneratedOutput(name));
                if (files == null) return List.of();
                Arrays.sort(files, Comparator.comparing(File::getName));
                List<SheetFile> out = new ArrayList<>(files.length);
                for (File f : files) {
                    out.add(new SheetFile(f.getName(), f.getName(), f.getAbsolutePath(), null, null));
                }
                return out;
            }
        }

        String folderId = extractFolderId(folderOrPath);
        return listDriveFolder(folderId);
    }

    @SuppressWarnings("unchecked")
    private List<SheetFile> listDriveFolder(String folderId) throws IOException {
        String token = bearerToken();
        if (token.isEmpty()) {
            throw new IOException("No Google OAuth/ADC token available to list Drive folder: " + folderId);
        }
        String q = String.format("'%s' in parents and trashed = false", folderId);
        String url = "https://www.googleapis.com/drive/v3/files?q=" + URLEncoder.encode(q, StandardCharsets.UTF_8)
                + "&fields=" + URLEncoder.encode("files(id,name,mimeType,webViewLink)", StandardCharsets.UTF_8)
                + "&pageSize=200&supportsAllDrives=true&includeItemsFromAllDrives=true";
        try {
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .timeout(Duration.ofSeconds(20))
                    .header("Authorization", "Bearer " + token)
                    .GET()
                    .build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() < 200 || resp.statusCode() >= 300) {
                throw new IOException("Drive API HTTP " + resp.statusCode() + ": " + resp.body());
            }
            Map<String, Object> payload = MAPPER.readValue(resp.body(), new TypeReference<>() {});
            List<Map<String, Object>> files = (List<Map<String, Object>>) payload.getOrDefault("files", List.of());
            List<SheetFile> out = new ArrayList<>();
            for (Map<String, Object> f : files) {
                String id = (String) f.get("id");
                String name = (String) f.get("name");
                String mime = (String) f.get("mimeType");
                String webLink = (String) f.get("webViewLink");
                if (id != null && name != null && ("application/pdf".equals(mime) || name.toLowerCase().endsWith(".pdf"))
                        && !isGeneratedOutput(name)) {
                    out.add(new SheetFile(id, name, null, folderId, webLink));
                }
            }
            return out;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException(e);
        }
    }

    public File downloadPdf(SheetFile sheet, File destDir) throws IOException {
        if (sheet.localPath() != null && !sheet.localPath().isBlank()) {
            File f = new File(sheet.localPath());
            if (f.exists()) return f;
        }
        destDir.mkdirs();
        File target = new File(destDir, new File(sheet.name()).getName());
        String token = bearerToken();
        if (!token.isEmpty()) {
            String url = "https://www.googleapis.com/drive/v3/files/" + URLEncoder.encode(sheet.id(), StandardCharsets.UTF_8)
                    + "?alt=media&supportsAllDrives=true";
            try {
                HttpRequest req = HttpRequest.newBuilder()
                        .uri(URI.create(url))
                        .timeout(Duration.ofSeconds(45))
                        .header("Authorization", "Bearer " + token)
                        .GET()
                        .build();
                HttpResponse<byte[]> resp = http.send(req, HttpResponse.BodyHandlers.ofByteArray());
                if (resp.statusCode() == 200 && resp.body().length > 4) {
                    Files.write(target.toPath(), resp.body());
                    return target;
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        throw new IOException("Unable to download PDF: " + sheet.name());
    }

    public Map<String, String> uploadPdf(File localPdf, String parentFolderId, String outputFilename) throws IOException {
        if (parentFolderId == null || parentFolderId.isBlank()) return Map.of();
        String token = bearerToken();
        if (token.isEmpty()) return Map.of();

        String boundary = "akkord_" + UUID.randomUUID().toString().replace("-", "");
        byte[] pdfBytes = Files.readAllBytes(localPdf.toPath());
        String metaJson = MAPPER.writeValueAsString(Map.of(
                "name", outputFilename != null ? outputFilename : localPdf.getName(),
                "parents", List.of(parentFolderId),
                "mimeType", "application/pdf"
        ));

        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        baos.write(("--" + boundary + "\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n" + metaJson + "\r\n").getBytes(StandardCharsets.UTF_8));
        baos.write(("--" + boundary + "\r\nContent-Type: application/pdf\r\n\r\n").getBytes(StandardCharsets.UTF_8));
        baos.write(pdfBytes);
        baos.write(("\r\n--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));

        String url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,webViewLink&supportsAllDrives=true";
        try {
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .timeout(Duration.ofSeconds(60))
                    .header("Authorization", "Bearer " + token)
                    .header("Content-Type", "multipart/related; boundary=" + boundary)
                    .POST(HttpRequest.BodyPublishers.ofByteArray(baos.toByteArray()))
                    .build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() >= 200 && resp.statusCode() < 300) {
                Map<String, String> created = MAPPER.readValue(resp.body(), new TypeReference<>() {});
                return created;
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        return Map.of();
    }

    public Map<String, Object> browseDriveFolder(String folderId, String query) {
        String target = (folderId == null || folderId.isBlank()) ? "root" : extractFolderId(folderId);
        Map<String, Object> current = new LinkedHashMap<>();
        current.put("id", target);
        current.put("name", "Mon Drive");
        current.put("parent_id", null);
        return Map.of(
                "current_folder", current,
                "folders", List.of(),
                "pdf_files", List.of(),
                "total_pdfs", 0
        );
    }
}
