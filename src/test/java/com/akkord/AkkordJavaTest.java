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

package com.akkord;

import com.akkord.config.AkkordConfig;
import com.akkord.harmony.HarmonyEngine;
import com.akkord.jobs.JobQueueManager.Pipeline;
import com.akkord.model.Models.ChordAnnotation;
import com.akkord.model.Models.HarmonyAnalysisResult;
import com.akkord.model.Models.LayoutExtractionResult;
import com.akkord.model.Models.SheetFile;
import com.akkord.model.Models.SheetProcessReport;
import com.akkord.model.Models.UserSession;
import com.akkord.oauth.OAuthManager;
import com.akkord.pdf.PdfLayoutAnalyzer;
import com.akkord.server.AkkordHttpServer;
import com.akkord.store.CloudStore.ActivityManager;
import com.akkord.store.CloudStore.FirestoreBackend;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.File;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class AkkordJavaTest {

    @Test
    void testCleanSingleStaffClusterStripsOuterBeams() {
        List<Double> cluster = List.of(100.0, 112.0, 117.0, 122.0, 127.0, 132.0, 145.0);
        List<double[]> cleaned = PdfLayoutAnalyzer.cleanSingleStaffCluster(cluster);
        assertEquals(1, cleaned.size());
        assertEquals(112.0, cleaned.getFirst()[0], 0.01);
        assertEquals(132.0, cleaned.getFirst()[1], 0.01);
        assertEquals(5.0, cleaned.getFirst()[2], 0.01);
    }

    @Test
    void testOAuthStatelessCookieRoundTrip(@TempDir Path tempDir) {
        FirestoreBackend fs = new FirestoreBackend("test-proj", tempDir.resolve("_fs").toFile());
        OAuthManager oauth = new OAuthManager(tempDir.toFile(), fs);
        oauth.setClientSecret("unit-test-secret");

        double now = System.currentTimeMillis() / 1000.0;
        UserSession session = new UserSession(
                "sess_java25",
                "alexis.mp@gmail.com",
                "Admin",
                "https://example.com/p.png",
                "ya29.token",
                "1//refresh",
                now + 3600,
                now
        );

        String cookie = oauth.encodeSessionCookie(session);
        assertTrue(cookie.startsWith("v1."));

        UserSession decoded = oauth.decodeSessionCookie(cookie);
        assertNotNull(decoded);
        assertEquals("alexis.mp@gmail.com", decoded.email());
        assertTrue(decoded.isAdmin(AkkordConfig.ADMIN_EMAIL));

        String tampered = cookie.substring(0, cookie.length() - 2) + "ff";
        assertNull(oauth.decodeSessionCookie(tampered));
    }

    @Test
    void testHarmonyHelpersAndAccuracyScore() {
        assertEquals("E7/B", HarmonyEngine.extractCompactChordSymbol("E7/B (renversement)").symbol());
        assertEquals("Am", HarmonyEngine.extractCompactChordSymbol("Am ou C/G").symbol());
        assertEquals("Gm", HarmonyEngine.extractCompactChordSymbol("G m").symbol());

        HarmonyAnalysisResult res = new HarmonyAnalysisResult(
                true, true, "Test", "Am", "Summary", 100,
                List.of(
                        new ChordAnnotation(1, 1, 80.0, 700.0, "Am", "correct", null, 1, null),
                        new ChordAnnotation(1, 1, 150.0, 700.0, "Dm", "correct", null, 2, null),
                        new ChordAnnotation(1, 1, 220.0, 700.0, "E7", "improve", "E7/G#", 3, "3rd in bass"),
                        new ChordAnnotation(1, 1, 290.0, 700.0, "G", "improve", "Gm", 4, "Minor chord"),
                        new ChordAnnotation(1, 1, 360.0, 700.0, "C", "missing", null, 5, null)
                ),
                List.of(), List.of(), List.of(), List.of(), List.of(), List.of(), null
        );
        int score = HarmonyEngine.computeHarmonyAccuracyScore(res);
        assertTrue(score >= 60 && score <= 85, "Expected blended score in 60..85, got " + score);
    }

    @Test
    void testQuotaAndAdminResetPreservesHistory(@TempDir Path tempDir) {
        FirestoreBackend fs = new FirestoreBackend("test-proj", tempDir.resolve("_fs").toFile());
        ActivityManager act = new ActivityManager(tempDir.toFile(), fs);
        act.setDailyLimit(2);

        act.recordFileProcessed("s1.pdf", "add_chords", "gemini-4-argon", "fr", "Am", 100,
                Map.of("total_tokens", 1000, "estimated_cost_eur", 0.01), "", "j1");
        act.recordFileProcessed("s2.pdf", "add_chords", "gemini-4-argon", "fr", "Em", 100,
                Map.of("total_tokens", 1200, "estimated_cost_eur", 0.012), "", "j1");

        assertFalse(act.checkAndConsumeQuota());
        Map<String, Object> qReset = act.resetDailyQuota("", "alexis.mp@gmail.com");
        assertEquals(0, qReset.get("used"));
        assertEquals(2, qReset.get("remaining"));
        assertEquals(2, qReset.get("total_processed_today"));
    }

    @Test
    @SuppressWarnings("unchecked")
    void testEndToEndJava25PdfBoxPipeline(@TempDir Path tempDir) throws Exception {
        AkkordHttpServer srv = new AkkordHttpServer(tempDir.toFile(), new File("akkord/static"));
        Map<String, Object> cfgPayload = srv.buildConfigPayload(null);
        assertEquals("java-25-virtual-threads", cfgPayload.get("runtime_engine"));

        File carcassi = new File("samples/Carcassi-Op60-No7.pdf");
        File koh = new File("samples/koh.pdf");
        assertTrue(carcassi.exists());
        assertTrue(koh.exists());

        LayoutExtractionResult carcassiLayout = PdfLayoutAnalyzer.analyzePdf(carcassi, tempDir.resolve("work_c").toFile());
        assertEquals(9, carcassiLayout.pages().getFirst().systems().size());

        LayoutExtractionResult kohLayout = PdfLayoutAnalyzer.analyzePdf(koh, tempDir.resolve("work_k").toFile());
        assertEquals(4, kohLayout.pages().getFirst().systems().size());

        AkkordConfig cfg = new AkkordConfig(
                "gemini-4-argon", false, "test-proj", "europe-west1", "",
                "fr", tempDir.toString(), false, null
        );
        Pipeline pipe = new Pipeline(cfg, "");
        for (File pdf : List.of(carcassi, koh)) {
            SheetFile sf = new SheetFile(pdf.getName(), pdf.getName(), pdf.getAbsolutePath(), null, null);
            SheetProcessReport rep = pipe.processSingleSheet(sf, tempDir.toFile());
            File outFile = new File(rep.outputPath());
            assertTrue(outFile.exists() && outFile.length() > 5000);
            try (PDDocument outDoc = Loader.loadPDF(outFile)) {
                assertTrue(outDoc.getNumberOfPages() >= 2, "Expected original pages + appended harmonic report page");
            }
        }
    }
}
