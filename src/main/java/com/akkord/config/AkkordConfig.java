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

package com.akkord.config;

import java.io.File;
import java.util.List;

/**
 * Runtime configuration and i18n localization for the Modern Java 25 Akkord application.
 */
public record AkkordConfig(
        String model,
        boolean vertexAi,
        String project,
        String location,
        String apiKey,
        String language,
        String outputDir,
        boolean uploadToDrive,
        String googleCredentialsPath
) {
    public static final String DEFAULT_MODEL = "gemini-4-argon";
    public static final String DEFAULT_GCP_PROJECT = "alexismp-runner";
    public static final String DEFAULT_GCP_LOCATION = "europe-west1";
    public static final String DEFAULT_GCS_BUCKET = "alexismp-runner-akkord-data";
    public static final String DEFAULT_TASKS_QUEUE = "akkord-pdf-queue";
    public static final String DEFAULT_SERVICE_URL = "https://akkord-2500276981.europe-west1.run.app";
    public static final String DEFAULT_LANGUAGE = "fr";
    public static final int DAILY_FILE_LIMIT = 25;
    public static final int DAILY_REPORT_HOUR = 18;
    public static final String ADMIN_EMAIL = "alexis.mp@gmail.com";
    public static final String DEFAULT_OAUTH_CLIENT = "2500276981-gmjvvn9ucbagv4g44n7rsdq9qo688hpb.apps.googleusercontent.com";
    public static final String DEFAULT_REDIRECT_URI = "https://akkord-2500276981.europe-west1.run.app/auth/callback";
    public static final String SESSION_COOKIE_NAME = "akkord_session";

    public static final List<String> AVAILABLE_MODELS = List.of(
            "gemini-4-argon",
            "gemini-3.8-flash",
            "gemini-3.5-flash-lite",
            "gemini-2.5-pro",
            "gemini-2.5-flash"
    );

    public static AkkordConfig fromEnv() {
        String model = envOr("AKKORD_MODEL", DEFAULT_MODEL);
        String vRaw = envOr("AKKORD_VERTEXAI", "true").toLowerCase();
        boolean vertexAi = vRaw.equals("1") || vRaw.equals("true") || vRaw.equals("yes");
        String project = envOr("AKKORD_GCP_PROJECT", envOr("GOOGLE_CLOUD_PROJECT", DEFAULT_GCP_PROJECT));
        String location = envOr("GOOGLE_CLOUD_LOCATION", DEFAULT_GCP_LOCATION);
        String apiKey = envOr("AKKORD_GEMINI_API_KEY", envOr("GEMINI_API_KEY", ""));
        String lang = normalizeLanguage(envOr("AKKORD_LANG", DEFAULT_LANGUAGE));
        String outDir = envOr("AKKORD_OUTPUT_DIR", defaultOutputDir());
        new File(outDir).mkdirs();
        String creds = System.getenv("GOOGLE_APPLICATION_CREDENTIALS");

        return new AkkordConfig(model, vertexAi, project, location, apiKey, lang, outDir, false, creds);
    }

    public AkkordConfig withOverrides(String newModel, String newLang, String newOutputDir, boolean newUploadToDrive) {
        return new AkkordConfig(
                newModel != null && !newModel.isBlank() ? newModel : this.model,
                this.vertexAi,
                this.project,
                this.location,
                this.apiKey,
                normalizeLanguage(newLang != null ? newLang : this.language),
                newOutputDir != null && !newOutputDir.isBlank() ? newOutputDir : this.outputDir,
                newUploadToDrive,
                this.googleCredentialsPath
        );
    }

    public static String defaultOutputDir() {
        File local = new File("outputs");
        if (local.exists() && local.isDirectory()) {
            return local.getAbsolutePath();
        }
        return "/tmp/akkord_outputs";
    }

    public static String envOr(String key, String fallback) {
        String v = System.getenv(key);
        return (v != null && !v.trim().isEmpty()) ? v.trim() : fallback;
    }

    public static String normalizeLanguage(String lang) {
        if (lang != null && lang.trim().equalsIgnoreCase("en")) {
            return "en";
        }
        return "fr";
    }

    public static String fileSuffix(String lang, boolean hasExistingChords) {
        boolean isFr = normalizeLanguage(lang).equals("fr");
        if (hasExistingChords) {
            return isFr ? "-analyse-accords.pdf" : "-chord-analysis.pdf";
        }
        return isFr ? "-avec-accords.pdf" : "-with-chords.pdf";
    }

    public static String promptDirective(String lang) {
        if (normalizeLanguage(lang).equals("en")) {
            return """
                    Respond strictly in English. Use standard international chord notation (e.g., 'Am', 'Dm/F', 'E7/G#', 'G/B'). \
                    CRITICAL COUNTERPOINT & WALKING BASS RULE: Avoid systematically placing the chord root in the bass or doubling the melody note! \
                    Use counterpoint rules (contrary motion against the melody, placing the 3rd, 5th, or 7th in the bass when the melody plays the root) \
                    and walking bass movement (stepwise diatonic or chromatic bass lines across measures, e.g., Am -> Am/G -> Dm/F -> E7). \
                    Populate `bass_line_proposals` with specific measure-by-measure bass proposals explaining how each slash chord avoids melody doubling or root monotony. \
                    Write all harmonic explanations, counterpoint/walking-bass notes, and review comments in clear English.""";
        }
        return """
                Respond strictly in French (Français). For guitar chord diagram titles, include both standard international notation \
                and French Solfège in parentheses, e.g., 'Am (La m)', 'Dm (Ré m)', 'E (Mi)', 'C (Do)', 'G (Sol)', 'F (Fa)', 'A7 (La 7)'. \
                For inline staff chord symbols, keep standard international symbols (e.g., 'Am', 'Dm/F', 'G/B', 'E7/G#') so they stay compact above the staff. \
                CRITICAL COUNTERPOINT & WALKING BASS RULE: Avoid the trap of systematically using the root note (fondamentale) in the bass or doubling the melody note! \
                Apply strict counterpoint rules (contrary motion / mouvement contraire against the melody, using the 3rd, 5th, or 7th in the bass when the melody plays the root or moves in parallel) \
                and walking bass principles (conjoint diatonic or chromatic bass lines connecting chords across measures, e.g. Am -> Am/G -> Dm/F -> E7 or Em -> D/F# -> G -> E7/G# -> Am). \
                Populate `bass_line_proposals` with specific measure-by-measure bass proposals explaining how each slash chord avoids melody doubling or root monotony. \
                Write all harmonic explanations, counterpoint/walking-bass notes, and review comments in French.""";
    }
}
