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

// Command akkord is the unified Go server & CLI entrypoint for the Akkord Go + Rust polyglot architecture.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/alexismp/akkord/internal/config"
	"github.com/alexismp/akkord/internal/jobs"
	"github.com/alexismp/akkord/internal/server"
	"github.com/alexismp/akkord/internal/store"
)

func main() {
	if len(os.Args) == 1 || (len(os.Args) >= 2 && os.Args[1] == "serve") {
		runServer(os.Args[1:])
		return
	}
	runCLI(os.Args[1:])
}

func runServer(args []string) {
	fs := flag.NewFlagSet("serve", flag.ExitOnError)
	port := fs.String("port", config.EnvOr("PORT", "8080"), "HTTP listen port")
	host := fs.String("host", config.EnvOr("HOST", "0.0.0.0"), "HTTP listen host")
	outputDir := fs.String("output-dir", config.DefaultOutputDir(), "Output directory for generated PDFs")
	staticDir := fs.String("static-dir", "", "Static web UI directory")
	if len(args) > 0 && args[0] == "serve" {
		_ = fs.Parse(args[1:])
	} else {
		_ = fs.Parse(args)
	}

	srv := server.NewServer(*outputDir, *staticDir)

	// Start daily 18:00 Europe/Paris report & midnight deferred-job resume scheduler
	go func() {
		ticker := time.NewTicker(60 * time.Second)
		defer ticker.Stop()
		lastResumeDay := ""
		for range ticker.C {
			loc, err := time.LoadLocation("Europe/Paris")
			now := time.Now()
			if err == nil {
				now = now.In(loc)
			}
			today := store.TodayKey()
			if now.Hour() >= srv.Activity.ReportHourLocal {
				oauthTok := srv.OAuth.GetAdminAccessToken()
				srv.Activity.SendDailyReportEmail(today, false, oauthTok)
			}
			if now.Hour() == 0 && now.Minute() < 15 && lastResumeDay != today {
				srv.JobQueue.ResumeDeferredJobs()
				lastResumeDay = today
			}
		}
	}()

	addr := fmt.Sprintf("%s:%s", *host, *port)
	log.Printf("Akkord Polyglot Server (Go + Rust [%s]) listening on http://%s", config.ResolveRustEngineBin(), addr)
	if err := http.ListenAndServe(addr, srv.Handler()); err != nil {
		log.Fatalf("server error: %v", err)
	}
}

func runCLI(args []string) {
	fs := flag.NewFlagSet("akkord", flag.ExitOnError)
	model := fs.String("model", config.EnvOr("AKKORD_MODEL", config.DefaultModel), "Gemini model to use")
	lang := fs.String("lang", config.EnvOr("AKKORD_LANG", config.DefaultLanguage), "Language ('fr' or 'en')")
	outputDir := fs.String("output-dir", config.DefaultOutputDir(), "Output directory for annotated PDFs")
	upload := fs.Bool("upload-to-drive", false, "Upload generated PDFs back to Google Drive")
	asJSON := fs.Bool("json", false, "Output JSON report")
	_ = fs.Parse(args)

	if fs.NArg() < 1 {
		fmt.Fprintln(os.Stderr, "Usage: akkord [serve | <drive_folder_or_local_pdf> [flags]]")
		os.Exit(1)
	}
	target := fs.Arg(0)

	validLang, err := config.ValidateLanguage(*lang)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}

	cfg := config.NewDefaultConfig()
	cfg.Model = *model
	cfg.Language = validLang
	cfg.OutputDir = *outputDir
	cfg.UploadToDrive = *upload

	pipe := jobs.NewPipeline(cfg, "")
	sheets, err := pipe.Drive.ListPDFs(target)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error listing PDFs: %v\n", err)
		os.Exit(1)
	}

	tmpDir, _ := os.MkdirTemp("", "akkord_cli_")
	defer os.RemoveAll(tmpDir)

	var reports []*jobs.SheetProcessReport
	for _, sh := range sheets {
		rep, err := pipe.ProcessSingleSheet(sh, tmpDir)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error processing %s: %v\n", sh.Name, err)
			continue
		}
		reports = append(reports, rep)
	}

	if *asJSON {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(reports)
		return
	}

	fmt.Printf("Akkord (Go + Rust) processed %d sheet(s) using model '%s'\n", len(reports), cfg.Model)
	fmt.Println("------------------------------------------------------------------------")
	for _, r := range reports {
		fmt.Printf("[%s] %s\n", r.Mode, r.InputName)
		fmt.Printf("  Key: %s | Score: %d%% | Chords: %d\n", r.DetectedKey, r.AccuracyScore, r.AnnotationsCount)
		if r.OutputPath != "" {
			fmt.Printf("  Saved to: %s\n", r.OutputPath)
		}
		fmt.Printf("  Summary: %s\n\n", r.Summary)
	}
}
