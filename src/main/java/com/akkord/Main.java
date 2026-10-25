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
import com.akkord.jobs.JobQueueManager.Pipeline;
import com.akkord.model.Models.SheetFile;
import com.akkord.model.Models.SheetProcessReport;
import com.akkord.server.AkkordHttpServer;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;

import java.io.File;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;

/**
 * Unified Modern Java 25 entrypoint for the Akkord HTTP Server and CLI.
 */
public final class Main {
    public static void main(String[] args) throws Exception {
        if (args.length == 0 || "serve".equalsIgnoreCase(args[0])) {
            int port = Integer.parseInt(AkkordConfig.envOr("PORT", "8080"));
            String outDir = AkkordConfig.defaultOutputDir();
            for (int i = 0; i < args.length - 1; i++) {
                if ("--port".equals(args[i])) port = Integer.parseInt(args[i + 1]);
                if ("--output-dir".equals(args[i])) outDir = args[i + 1];
            }
            AkkordHttpServer srv = new AkkordHttpServer(new File(outDir), null);
            srv.start(port);
            System.out.printf("Akkord Modern Java 25 Server (Virtual Threads + PDFBox 3) listening on http://0.0.0.0:%d%n", port);
            Thread.currentThread().join();
            return;
        }

        String model = AkkordConfig.DEFAULT_MODEL;
        String lang = AkkordConfig.DEFAULT_LANGUAGE;
        String outDir = AkkordConfig.defaultOutputDir();
        boolean upload = false;
        boolean asJson = false;
        String target = null;

        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--model", "-m" -> model = args[++i];
                case "--lang", "-l" -> lang = args[++i];
                case "--output-dir", "-o" -> outDir = args[++i];
                case "--upload-to-drive" -> upload = true;
                case "--json" -> asJson = true;
                default -> {
                    if (!args[i].startsWith("-")) target = args[i];
                }
            }
        }

        if (target == null) {
            System.err.println("Usage: java -jar target/akkord.jar [serve | <folder_or_pdf> [--lang fr|en] [--model gemini-4-argon] [--output-dir outputs]]");
            System.exit(1);
        }

        AkkordConfig cfg = AkkordConfig.fromEnv().withOverrides(model, lang, outDir, upload);
        Pipeline pipe = new Pipeline(cfg, "");
        List<SheetFile> sheets = pipe.getDrive().listPdfs(target);
        File tmpDir = Files.createTempDirectory("akkord_java_cli_").toFile();

        List<SheetProcessReport> reports = new ArrayList<>();
        for (SheetFile sh : sheets) {
            reports.add(pipe.processSingleSheet(sh, tmpDir));
        }

        if (asJson) {
            ObjectMapper mapper = new ObjectMapper().enable(SerializationFeature.INDENT_OUTPUT);
            System.out.println(mapper.writeValueAsString(reports));
        } else {
            System.out.printf("Akkord (Modern Java 25) processed %d sheet(s) using model '%s'%n", reports.size(), cfg.model());
            System.out.println("------------------------------------------------------------------------");
            for (SheetProcessReport r : reports) {
                System.out.printf("[%s] %s%n", r.mode(), r.inputName());
                System.out.printf("  Key: %s | Score: %d%% | Chords: %d%n", r.detectedKey(), r.accuracyScore(), r.annotationsCount());
                System.out.printf("  Saved to: %s%n", r.outputPath());
                System.out.printf("  Summary: %s%n%n", r.summary());
            }
        }
    }
}
