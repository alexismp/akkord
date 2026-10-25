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

package com.akkord.model;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

/**
 * Immutable domain records for the Akkord Modern Java 25 architecture.
 */
public final class Models {
    private Models() {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record StaffSystem(
            @JsonProperty("index") int index,
            @JsonProperty("y_top_pt") double yTopPt,
            @JsonProperty("y_bottom_pt") double yBottomPt,
            @JsonProperty("chord_y_pt") double chordYPt,
            @JsonProperty("treble_height_pt") double trebleHeightPt
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record ExtractedTextToken(
            @JsonProperty("page_num") int pageNum,
            @JsonProperty("x_pt") double xPt,
            @JsonProperty("y_pt") double yPt,
            @JsonProperty("token") String token
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record PageLayout(
            @JsonProperty("page_num") int pageNum,
            @JsonProperty("width_pt") double widthPt,
            @JsonProperty("height_pt") double heightPt,
            @JsonProperty("systems") List<StaffSystem> systems,
            @JsonProperty("bottom_free_pt") double bottomFreePt,
            @JsonProperty("clean_png_path") String cleanPngPath,
            @JsonProperty("guide_png_path") String guidePngPath,
            @JsonProperty("ink_grid_b64") String inkGridB64,
            @JsonProperty("ink_cols") int inkCols,
            @JsonProperty("ink_rows") int inkRows,
            byte[] inkGridRaw
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record LayoutExtractionResult(
            @JsonProperty("detected_title") String detectedTitle,
            @JsonProperty("chord_tokens") List<ExtractedTextToken> chordTokens,
            @JsonProperty("pages") List<PageLayout> pages
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record ChordAnnotation(
            @JsonProperty("page_num") int pageNum,
            @JsonProperty("system_index") int systemIndex,
            @JsonProperty("x_pt") double xPt,
            @JsonProperty("y_pt") Double yPt,
            @JsonProperty("chord") String chord,
            @JsonProperty("status") String status,
            @JsonProperty("suggested_chord") String suggestedChord,
            @JsonProperty("measure_number") Integer measureNumber,
            @JsonProperty("note") String note
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record BassLineProposal(
            @JsonProperty("measure_number") Integer measureNumber,
            @JsonProperty("original_chord") String originalChord,
            @JsonProperty("proposed_slash_chord") String proposedSlashChord,
            @JsonProperty("melody_note") String melodyNote,
            @JsonProperty("technique") String technique,
            @JsonProperty("explanation") String explanation
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record GuitarDiagram(
            @JsonProperty("name") String name,
            @JsonProperty("frets") List<String> frets
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record TokenUsageStats(
            @JsonProperty("model") String model,
            @JsonProperty("input_tokens") int inputTokens,
            @JsonProperty("output_tokens") int outputTokens,
            @JsonProperty("thinking_tokens") int thinkingTokens,
            @JsonProperty("cached_tokens") int cachedTokens,
            @JsonProperty("total_tokens") int totalTokens,
            @JsonProperty("estimated_cost_usd") double estimatedCostUsd,
            @JsonProperty("estimated_cost_eur") double estimatedCostEur,
            @JsonProperty("source") String source
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record HarmonyAnalysisResult(
            @JsonProperty("is_music_sheet") boolean isMusicSheet,
            @JsonProperty("has_existing_chords") boolean hasExistingChords,
            @JsonProperty("title") String title,
            @JsonProperty("detected_key") String detectedKey,
            @JsonProperty("overall_summary") String overallSummary,
            @JsonProperty("accuracy_score") int accuracyScore,
            @JsonProperty("annotations") List<ChordAnnotation> annotations,
            @JsonProperty("chord_diagrams") List<GuitarDiagram> chordDiagrams,
            @JsonProperty("bass_line_proposals") List<BassLineProposal> bassLineProposals,
            @JsonProperty("slash_chord_notes") List<String> slashChordNotes,
            @JsonProperty("review_improvements") List<String> reviewImprovements,
            @JsonProperty("review_missing") List<String> reviewMissing,
            @JsonProperty("review_correct") List<String> reviewCorrect,
            @JsonProperty("token_usage") TokenUsageStats tokenUsage
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record SheetFile(
            @JsonProperty("id") String id,
            @JsonProperty("name") String name,
            @JsonProperty("local_path") String localPath,
            @JsonProperty("drive_parent_id") String driveParentId,
            @JsonProperty("web_view_link") String webViewLink
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record SheetProcessReport(
            @JsonProperty("input_name") String inputName,
            @JsonProperty("output_path") String outputPath,
            @JsonProperty("mode") String mode,
            @JsonProperty("detected_key") String detectedKey,
            @JsonProperty("accuracy_score") int accuracyScore,
            @JsonProperty("annotations_count") int annotationsCount,
            @JsonProperty("summary") String summary,
            @JsonProperty("drive_uploaded_id") String driveUploadedId,
            @JsonProperty("drive_web_view_link") String driveWebViewLink,
            @JsonProperty("token_usage") TokenUsageStats tokenUsage
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record UserSession(
            @JsonProperty("session_id") String sessionId,
            @JsonProperty("email") String email,
            @JsonProperty("name") String name,
            @JsonProperty("picture") String picture,
            @JsonProperty("access_token") String accessToken,
            @JsonProperty("refresh_token") String refreshToken,
            @JsonProperty("expires_at") double expiresAt,
            @JsonProperty("created_at") double createdAt
    ) {
        public boolean isAdmin(String adminEmail) {
            return email != null && email.trim().equalsIgnoreCase(adminEmail);
        }

        public boolean isExpired() {
            double now = System.currentTimeMillis() / 1000.0;
            return now >= (expiresAt - 60.0);
        }

        public Map<String, Object> toPublicDict(String adminEmail) {
            return Map.of(
                    "authenticated", true,
                    "email", email != null ? email : "",
                    "name", name != null ? name : "",
                    "picture", picture != null ? picture : "",
                    "is_admin", isAdmin(adminEmail)
            );
        }
    }
}
