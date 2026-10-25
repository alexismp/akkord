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

package com.akkord.oauth;

import com.akkord.config.AkkordConfig;
import com.akkord.model.Models.UserSession;
import com.akkord.store.CloudStore.FirestoreBackend;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.zip.Deflater;
import java.util.zip.DeflaterOutputStream;
import java.util.zip.InflaterOutputStream;

/**
 * Stateless OAuth 2.0 manager (`v1.<b64>.<sig>` zlib + HMAC-SHA256 cookies) for Modern Java 25.
 */
public final class OAuthManager {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final SecureRandom RNG = new SecureRandom();

    public static final List<String> SCOPES = List.of(
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/gmail.send"
    );

    private final File outputDir;
    private final String clientId;
    private String clientSecret;
    private final String redirectUri;
    private final FirestoreBackend firestore;
    private final Map<String, UserSession> sessions = new ConcurrentHashMap<>();

    public OAuthManager(File outputDir, FirestoreBackend firestore) {
        this.outputDir = outputDir;
        this.clientId = AkkordConfig.envOr("AKKORD_OAUTH_CLIENT_ID", AkkordConfig.DEFAULT_OAUTH_CLIENT);
        this.clientSecret = AkkordConfig.envOr("AKKORD_OAUTH_CLIENT_SECRET", "");
        this.redirectUri = AkkordConfig.envOr("AKKORD_OAUTH_REDIRECT_URI", AkkordConfig.DEFAULT_REDIRECT_URI);
        this.firestore = firestore;
    }

    public void setClientSecret(String secret) {
        this.clientSecret = secret != null ? secret : "";
    }

    public boolean isConfigured() {
        return !clientId.isBlank() && !clientSecret.isBlank();
    }

    private byte[] signingKey() throws Exception {
        String secret = AkkordConfig.envOr("AKKORD_SESSION_SECRET", clientSecret);
        if (secret.isBlank()) {
            secret = "akkord-default-session-secret-key";
        }
        return MessageDigest.getInstance("SHA-256").digest(secret.getBytes(StandardCharsets.UTF_8));
    }

    private String hmacHex32(String data) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(signingKey(), "HmacSHA256"));
        byte[] sig = mac.doFinal(data.getBytes(StandardCharsets.US_ASCII));
        return HexFormat.of().formatHex(sig).substring(0, 32);
    }

    public String encodeSessionCookie(UserSession s) {
        try {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("sid", s.sessionId());
            payload.put("em", s.email());
            payload.put("nm", s.name());
            payload.put("pic", s.picture());
            payload.put("at", s.accessToken());
            payload.put("rt", s.refreshToken());
            payload.put("exp", s.expiresAt());
            payload.put("crt", s.createdAt());

            byte[] jsonBytes = MAPPER.writeValueAsBytes(payload);
            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            try (DeflaterOutputStream dos = new DeflaterOutputStream(baos, new Deflater(Deflater.BEST_COMPRESSION))) {
                dos.write(jsonBytes);
            }
            String b64 = Base64.getUrlEncoder().withoutPadding().encodeToString(baos.toByteArray());
            String sig = hmacHex32(b64);
            return "v1." + b64 + "." + sig;
        } catch (Exception e) {
            return s.sessionId();
        }
    }

    public UserSession decodeSessionCookie(String cookieValue) {
        if (cookieValue == null || !cookieValue.startsWith("v1.")) {
            return null;
        }
        String[] parts = cookieValue.split("\\.");
        if (parts.length != 3) {
            return null;
        }
        String b64 = parts[1];
        String sig = parts[2];
        try {
            String expected = hmacHex32(b64);
            if (!MessageDigest.isEqual(sig.getBytes(StandardCharsets.US_ASCII), expected.getBytes(StandardCharsets.US_ASCII))) {
                return null;
            }
            byte[] compressed = Base64.getUrlDecoder().decode(b64);
            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            try (InflaterOutputStream ios = new InflaterOutputStream(baos)) {
                ios.write(compressed);
            }
            Map<String, Object> data = MAPPER.readValue(baos.toByteArray(), new TypeReference<>() {});
            String email = (String) data.get("em");
            if (email == null || email.isBlank()) {
                return null;
            }
            String sid = (String) data.getOrDefault("sid", randomToken(16));
            String name = (String) data.getOrDefault("nm", email);
            String pic = (String) data.getOrDefault("pic", "");
            String at = (String) data.getOrDefault("at", "");
            String rt = (String) data.getOrDefault("rt", "");
            double exp = data.get("exp") instanceof Number n ? n.doubleValue() : 0.0;
            double crt = data.get("crt") instanceof Number n ? n.doubleValue() : 0.0;
            return new UserSession(sid, email, name, pic, at, rt, exp, crt);
        } catch (Exception e) {
            return null;
        }
    }

    public UserSession getSession(String cookieOrId) {
        if (cookieOrId == null || cookieOrId.isBlank()) return null;
        UserSession decoded = decodeSessionCookie(cookieOrId);
        if (decoded != null) {
            if (decoded.isExpired()) return null;
            sessions.put(decoded.sessionId(), decoded);
            return decoded;
        }
        UserSession s = sessions.get(cookieOrId);
        if (s != null && !s.isExpired()) {
            return s;
        }
        return null;
    }

    public void deleteSession(String cookieOrId) {
        if (cookieOrId == null) return;
        UserSession decoded = decodeSessionCookie(cookieOrId);
        String sid = decoded != null ? decoded.sessionId() : cookieOrId;
        sessions.remove(sid);
        firestore.deleteDoc("akkord_oauth_sessions", sid);
    }

    public String buildAuthorizationUrl(String requestBaseUrl) {
        String state = randomToken(18);
        String redir = requestBaseUrl != null && !requestBaseUrl.isBlank()
                ? requestBaseUrl.replaceAll("/+$", "") + "/auth/callback"
                : redirectUri;
        return "https://accounts.google.com/o/oauth2/v2/auth?client_id=" + URLEncoder.encode(clientId, StandardCharsets.UTF_8)
                + "&redirect_uri=" + URLEncoder.encode(redir, StandardCharsets.UTF_8)
                + "&response_type=code"
                + "&scope=" + URLEncoder.encode(String.join(" ", SCOPES), StandardCharsets.UTF_8)
                + "&access_type=offline&prompt=consent&state=" + URLEncoder.encode(state, StandardCharsets.UTF_8);
    }

    private static String randomToken(int numBytes) {
        byte[] b = new byte[numBytes];
        RNG.nextBytes(b);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(b);
    }
}
