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

package com.akkord.pdf;

import com.akkord.model.Models.BassLineProposal;
import com.akkord.model.Models.ChordAnnotation;
import com.akkord.model.Models.GuitarDiagram;
import com.akkord.model.Models.HarmonyAnalysisResult;
import com.akkord.model.Models.PageLayout;
import com.akkord.model.Models.StaffSystem;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.PDPageContentStream;
import org.apache.pdfbox.pdmodel.common.PDRectangle;
import org.apache.pdfbox.pdmodel.font.PDType1Font;
import org.apache.pdfbox.pdmodel.font.Standard14Fonts;

import java.awt.Color;
import java.io.File;
import java.io.IOException;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * Pure-Java 25 vector PDF annotator using Apache PDFBox 3 (`PDPageContentStream`).
 * Overlays chord pills/badges with 2pt spiral low-ink collision avoidance, multi-row guitar fretboard diagrams,
 * and appended harmonic analysis & counterpoint report pages.
 */
public final class PdfVectorAnnotator {

    private record FootnoteEntry(
            int index,
            int pageNum,
            int systemIndex,
            Integer measureNumber,
            String originalChord,
            String displayedChord,
            String status,
            String note
    ) {}

    public static void annotatePdf(
            File inputPdf,
            File outputPdf,
            String language,
            List<PageLayout> layouts,
            HarmonyAnalysisResult result
    ) throws IOException {
        boolean isFr = !"en".equalsIgnoreCase(language);
        try (PDDocument doc = Loader.loadPDF(inputPdf)) {
            PDType1Font fontBold = new PDType1Font(Standard14Fonts.FontName.HELVETICA_BOLD);
            PDType1Font fontReg = new PDType1Font(Standard14Fonts.FontName.HELVETICA);

            List<FootnoteEntry> footnotes = new ArrayList<>();
            int footnoteSeq = 1;

            int numOrigPages = doc.getNumberOfPages();
            for (int pageIdx = 0; pageIdx < numOrigPages; pageIdx++) {
                int pageNum = pageIdx + 1;
                PDPage page = doc.getPage(pageIdx);
                PDRectangle mediaBox = page.getMediaBox();
                double pageW = mediaBox.getWidth();
                double pageH = mediaBox.getHeight();

                PageLayout layout = layouts.stream()
                        .filter(l -> l.pageNum() == pageNum)
                        .findFirst()
                        .orElse(new PageLayout(pageNum, pageW, pageH, List.of(), 72.0, "", "", "", 0, 0, new byte[0]));

                List<ChordAnnotation> pageAnns = new ArrayList<>();
                if (result.annotations() != null) {
                    for (ChordAnnotation a : result.annotations()) {
                        if (a.pageNum() == pageNum) {
                            pageAnns.add(a);
                        }
                    }
                }
                pageAnns.sort(Comparator.comparingInt(ChordAnnotation::systemIndex).thenComparingDouble(ChordAnnotation::xPt));

                try (PDPageContentStream cs = new PDPageContentStream(doc, page, PDPageContentStream.AppendMode.APPEND, true, true)) {
                    // Page 1 header banner
                    if (pageNum == 1) {
                        String keyLabel = isFr ? "Tonalite : " : "Key: ";
                        String bannerText = "Akkord — " + keyLabel + toWinAnsiSafe(result.detectedKey()) +
                                (result.hasExistingChords() ? ("  |  Score : " + result.accuracyScore() + "%") : "");
                        drawFilledRect(cs, 36.0, pageH - 22.0, pageW - 72.0, 15.0, new Color(252, 248, 240), new Color(180, 150, 100));
                        drawText(cs, fontBold, 8.5f, 44.0, pageH - 17.5, bannerText, new Color(30, 36, 77));
                    }

                    List<double[]> placedBoxes = new ArrayList<>();

                    for (ChordAnnotation ann : pageAnns) {
                        String status = ann.status() != null ? ann.status() : "added";
                        if (result.hasExistingChords() && "correct".equalsIgnoreCase(status)) {
                            continue;
                        }

                        StaffSystem sys = findSystem(layout.systems(), ann.systemIndex());
                        double baseY = ann.yPt() != null ? ann.yPt() : (sys != null ? sys.chordYPt() : pageH - 110.0);
                        double minAllowedY = sys != null ? sys.yTopPt() + 4.0 : 36.0;
                        double maxAllowedY = pageH - 28.0;

                        String mainSym = toWinAnsiSafe(ann.chord());
                        if ("improve".equalsIgnoreCase(status) && ann.suggestedChord() != null && !ann.suggestedChord().isBlank()) {
                            mainSym = toWinAnsiSafe(ann.suggestedChord());
                        }
                        if (mainSym.isBlank()) {
                            continue;
                        }

                        Integer fnNum = null;
                        if (result.hasExistingChords() && ("improve".equalsIgnoreCase(status) || "missing".equalsIgnoreCase(status))) {
                            fnNum = footnoteSeq++;
                            footnotes.add(new FootnoteEntry(
                                    fnNum,
                                    pageNum,
                                    ann.systemIndex(),
                                    ann.measureNumber(),
                                    toWinAnsiSafe(ann.chord()),
                                    mainSym,
                                    status,
                                    toWinAnsiSafe(ann.note())
                            ));
                        }

                        float fontSize = result.hasExistingChords() ? 8.2f : 8.6f;
                        double textW = mainSym.length() * (fontSize * 0.56) + (fnNum != null ? 9.0 : 0.0);
                        double boxW = Math.max(result.hasExistingChords() ? 27.0 : 18.0, textW + 7.0);
                        double boxH = result.hasExistingChords() ? 12.5 : 12.0;

                        double targetX = Math.clamp(ann.xPt(), 34.0, pageW - boxW - 18.0);
                        double targetY = Math.clamp(baseY, minAllowedY, maxAllowedY);

                        double[] pos = findLowInkPosition(layout, targetX, targetY, boxW, boxH, minAllowedY, maxAllowedY, placedBoxes);
                        placedBoxes.add(new double[]{pos[0], pos[1], boxW, boxH});

                        Color fillCol;
                        Color strokeCol;
                        Color textCol;
                        if (result.hasExistingChords()) {
                            if ("missing".equalsIgnoreCase(status)) {
                                fillCol = new Color(239, 246, 255);
                                strokeCol = new Color(37, 99, 235);
                                textCol = new Color(29, 78, 216);
                            } else {
                                fillCol = new Color(254, 243, 199);
                                strokeCol = new Color(217, 119, 6);
                                textCol = new Color(146, 64, 14);
                            }
                        } else {
                            fillCol = new Color(240, 247, 255);
                            strokeCol = new Color(59, 130, 246);
                            textCol = new Color(29, 78, 216);
                        }

                        drawFilledRect(cs, pos[0], pos[1], boxW, boxH, fillCol, strokeCol);
                        drawText(cs, fontBold, fontSize, pos[0] + 3.5, pos[1] + 3.2, mainSym, textCol);
                        if (fnNum != null) {
                            double supX = pos[0] + 3.5 + mainSym.length() * (fontSize * 0.55) + 1.2;
                            drawText(cs, fontBold, 5.8f, supX, pos[1] + 6.4, String.valueOf(fnNum), textCol);
                        }
                    }

                    // Draw inline guitar diagrams at bottom of last page if there is enough free space and no footnotes page is needed
                    if (pageNum == numOrigPages && !result.hasExistingChords() && layout.bottomFreePt() >= 115.0
                            && result.chordDiagrams() != null && !result.chordDiagrams().isEmpty()) {
                        drawGuitarDiagramGrid(cs, fontBold, fontReg, result.chordDiagrams(), 42.0, 26.0, pageW - 84.0, isFr);
                    }
                }
            }

            // Always append a dedicated Harmonic Analysis & Guitar Diagrams Report Page
            appendAnalysisReportPage(doc, fontBold, fontReg, result, footnotes, isFr);

            if (outputPdf.getParentFile() != null) {
                outputPdf.getParentFile().mkdirs();
            }
            doc.save(outputPdf);
        }
    }

    private static StaffSystem findSystem(List<StaffSystem> systems, int sysIndex) {
        if (systems == null || systems.isEmpty()) {
            return null;
        }
        for (StaffSystem s : systems) {
            if (s.index() == sysIndex) {
                return s;
            }
        }
        int clamped = Math.clamp(sysIndex - 1, 0, systems.size() - 1);
        return systems.get(clamped);
    }

    private static double[] findLowInkPosition(
            PageLayout layout,
            double startX,
            double startY,
            double boxW,
            double boxH,
            double minY,
            double maxY,
            List<double[]> placedBoxes
    ) {
        double[] dySteps = {0.0, 2.5, -2.0, 5.0, 7.5, 10.0, 12.5};
        double[] dxSteps = {0.0, 2.5, -2.5, 5.0, -5.0, 8.0, -8.0, 11.0};

        double bestX = startX;
        double bestY = startY;
        double bestScore = Double.MAX_VALUE;

        for (double dx : dxSteps) {
            double candX = Math.clamp(startX + dx, 30.0, Math.max(40.0, layout.widthPt() - boxW - 16.0));
            for (double dy : dySteps) {
                double candY = Math.clamp(startY + dy, minY, maxY);
                if (overlapsExisting(candX, candY, boxW, boxH, placedBoxes)) {
                    continue;
                }
                double ink = sampleInkPenalty(layout, candX, candY, boxW, boxH);
                double distPenalty = Math.abs(dx) * 1.45 + Math.abs(dy) * 0.42;
                double score = ink + distPenalty;
                if (score < bestScore) {
                    bestScore = score;
                    bestX = candX;
                    bestY = candY;
                }
            }
        }
        return new double[]{bestX, bestY};
    }

    private static boolean overlapsExisting(double x, double y, double w, double h, List<double[]> boxes) {
        for (double[] b : boxes) {
            boolean xOv = (x < b[0] + b[2] + 3.0) && (x + w + 3.0 > b[0]);
            boolean yOv = (y < b[1] + b[3] + 2.0) && (y + h + 2.0 > b[1]);
            if (xOv && yOv) {
                return true;
            }
        }
        return false;
    }

    private static double sampleInkPenalty(PageLayout layout, double x, double y, double w, double h) {
        byte[] grid = layout.inkGridRaw();
        if (grid == null || grid.length == 0 || layout.inkCols() <= 0 || layout.inkRows() <= 0) {
            return 0.0;
        }
        int c0 = Math.clamp((int) Math.floor(x / 2.0), 0, layout.inkCols() - 1);
        int c1 = Math.clamp((int) Math.ceil((x + w) / 2.0), c0 + 1, layout.inkCols());
        int r0 = Math.clamp((int) Math.floor(y / 2.0), 0, layout.inkRows() - 1);
        int r1 = Math.clamp((int) Math.ceil((y + h) / 2.0), r0 + 1, layout.inkRows());

        double sum = 0.0;
        int count = 0;
        for (int r = r0; r < r1; r++) {
            for (int c = c0; c < c1; c++) {
                int idx = r * layout.inkCols() + c;
                if (idx >= 0 && idx < grid.length) {
                    sum += (grid[idx] & 0xFF);
                    count++;
                }
            }
        }
        return count > 0 ? (sum / count) : 0.0;
    }

    private static void appendAnalysisReportPage(
            PDDocument doc,
            PDType1Font fontBold,
            PDType1Font fontReg,
            HarmonyAnalysisResult result,
            List<FootnoteEntry> footnotes,
            boolean isFr
    ) throws IOException {
        PDPage reportPage = new PDPage(PDRectangle.A4);
        doc.addPage(reportPage);
        double pageW = PDRectangle.A4.getWidth();
        double pageH = PDRectangle.A4.getHeight();

        try (PDPageContentStream cs = new PDPageContentStream(doc, reportPage)) {
            drawFilledRect(cs, 36.0, pageH - 74.0, pageW - 72.0, 44.0, new Color(30, 36, 77), new Color(198, 139, 44));
            String headerTitle = isFr
                    ? "Akkord — Rapport d'Analyse Harmonique & Contrepoint"
                    : "Akkord — Harmonic Analysis & Counterpoint Report";
            drawText(cs, fontBold, 13.0f, 48.0, pageH - 49.0, headerTitle, Color.WHITE);

            String subHeader = (isFr ? "Tonalite detectee : " : "Detected Key: ") + toWinAnsiSafe(result.detectedKey())
                    + "   |   " + (isFr ? "Precision harmonique : " : "Harmonic Accuracy: ") + result.accuracyScore() + "%";
            drawText(cs, fontReg, 9.5f, 48.0, pageH - 64.0, subHeader, new Color(244, 239, 230));

            double curY = pageH - 96.0;

            if (result.overallSummary() != null && !result.overallSummary().isBlank()) {
                String sumTitle = isFr ? "Synthese musicale :" : "Musical Summary:";
                drawText(cs, fontBold, 10.5f, 40.0, curY, sumTitle, new Color(158, 42, 43));
                curY -= 14.0;
                for (String line : wrapText(toWinAnsiSafe(result.overallSummary()), 92)) {
                    drawText(cs, fontReg, 9.0f, 44.0, curY, line, new Color(24, 22, 21));
                    curY -= 12.0;
                }
                curY -= 6.0;
            }

            if (!footnotes.isEmpty()) {
                String fnTitle = isFr ? "Notes detaillees de la partition (renvois numerotes) :" : "Detailed Score Footnotes:";
                drawText(cs, fontBold, 10.5f, 40.0, curY, fnTitle, new Color(30, 36, 77));
                curY -= 15.0;
                for (FootnoteEntry fn : footnotes) {
                    if (curY < 195.0) {
                        break;
                    }
                    String badgeLabel = fn.displayedChord + " [" + fn.index + "]";
                    drawFilledRect(cs, 42.0, curY - 3.0, 52.0, 12.0, new Color(254, 243, 199), new Color(217, 119, 6));
                    drawText(cs, fontBold, 8.0f, 45.0, curY, badgeLabel, new Color(146, 64, 14));

                    String locInfo = String.format("S%d%s (%s -> %s) : %s",
                            fn.systemIndex,
                            fn.measureNumber != null ? (" M." + fn.measureNumber) : "",
                            fn.originalChord != null && !fn.originalChord.isBlank() ? fn.originalChord : "-",
                            fn.displayedChord,
                            fn.note != null ? fn.note : "");
                    List<String> wrapped = wrapText(locInfo, 78);
                    for (int i = 0; i < wrapped.size(); i++) {
                        drawText(cs, fontReg, 8.5f, 102.0, curY, wrapped.get(i), new Color(40, 38, 36));
                        curY -= 11.5;
                    }
                    curY -= 3.0;
                }
                curY -= 6.0;
            }

            if (result.bassLineProposals() != null && !result.bassLineProposals().isEmpty() && curY > 210.0) {
                String bassTitle = isFr
                        ? "Ligne de basse — Contrepoint & Walking Bass :"
                        : "Bass Line — Counterpoint & Walking Bass:";
                drawText(cs, fontBold, 10.5f, 40.0, curY, bassTitle, new Color(30, 36, 77));
                curY -= 14.0;
                for (BassLineProposal bp : result.bassLineProposals()) {
                    if (curY < 190.0) {
                        break;
                    }
                    String line = String.format("• %s -> %s (%s) : %s",
                            toWinAnsiSafe(bp.originalChord()),
                            toWinAnsiSafe(bp.proposedSlashChord()),
                            toWinAnsiSafe(bp.technique()),
                            toWinAnsiSafe(bp.explanation()));
                    for (String wl : wrapText(line, 90)) {
                        drawText(cs, fontReg, 8.5f, 44.0, curY, wl, new Color(40, 38, 36));
                        curY -= 11.5;
                    }
                }
            }

            if (result.chordDiagrams() != null && !result.chordDiagrams().isEmpty()) {
                drawGuitarDiagramGrid(cs, fontBold, fontReg, result.chordDiagrams(), 42.0, 36.0, pageW - 84.0, isFr);
            }
        }
    }

    private static void drawGuitarDiagramGrid(
            PDPageContentStream cs,
            PDType1Font fontBold,
            PDType1Font fontReg,
            List<GuitarDiagram> diagrams,
            double startX,
            double bottomY,
            double totalW,
            boolean isFr
    ) throws IOException {
        int count = Math.min(8, diagrams.size());
        if (count == 0) {
            return;
        }
        int cols = Math.min(4, count);
        int rows = (count + cols - 1) / cols;
        double cellW = totalW / cols;
        double rowH = 68.0;

        String gridTitle = isFr ? "Diagrammes d'accords guitare principaux :" : "Main Guitar Chord Diagrams:";
        drawText(cs, fontBold, 10.0f, startX, bottomY + rows * rowH + 8.0, gridTitle, new Color(30, 36, 77));

        for (int idx = 0; idx < count; idx++) {
            GuitarDiagram d = diagrams.get(idx);
            int r = idx / cols;
            int c = idx % cols;
            double gx = startX + c * cellW + 14.0;
            double gy = bottomY + (rows - 1 - r) * rowH;

            drawText(cs, fontBold, 8.5f, gx, gy + 48.0, toWinAnsiSafe(d.name()), new Color(24, 22, 21));

            double gridW = 40.0;
            double gridH = 36.0;
            double strStep = gridW / 5.0;
            double fretStep = gridH / 4.0;

            cs.setStrokingColor(new Color(80, 75, 70));
            cs.setLineWidth(1.6f);
            cs.moveTo((float) gx, (float) (gy + gridH));
            cs.lineTo((float) (gx + gridW), (float) (gy + gridH));
            cs.stroke();

            cs.setLineWidth(0.6f);
            for (int f = 0; f <= 4; f++) {
                double fy = gy + f * fretStep;
                cs.moveTo((float) gx, (float) fy);
                cs.lineTo((float) (gx + gridW), (float) fy);
            }
            for (int s = 0; s < 6; s++) {
                double sx = gx + s * strStep;
                cs.moveTo((float) sx, (float) gy);
                cs.lineTo((float) sx, (float) (gy + gridH));
            }
            cs.stroke();

            List<String> frets = d.frets() != null ? d.frets() : List.of("x", "0", "2", "2", "1", "0");
            for (int s = 0; s < Math.min(6, frets.size()); s++) {
                String fv = frets.get(s).trim();
                double sx = gx + s * strStep;
                if ("x".equalsIgnoreCase(fv) || "0".equals(fv)) {
                    drawText(cs, fontReg, 6.5f, sx - 2.0, gy + gridH + 2.5, fv.toUpperCase(), new Color(90, 85, 80));
                } else {
                    try {
                        int fretNum = Integer.parseInt(fv);
                        if (fretNum >= 1 && fretNum <= 4) {
                            double cy = gy + gridH - (fretNum - 0.5) * fretStep;
                            drawFilledRect(cs, sx - 2.2, cy - 2.2, 4.4, 4.4, new Color(30, 36, 77), new Color(30, 36, 77));
                        }
                    } catch (NumberFormatException ignored) {
                    }
                }
            }
        }
    }

    private static void drawFilledRect(PDPageContentStream cs, double x, double y, double w, double h, Color fill, Color stroke) throws IOException {
        cs.setNonStrokingColor(fill);
        cs.setStrokingColor(stroke);
        cs.setLineWidth(0.75f);
        cs.addRect((float) x, (float) y, (float) w, (float) h);
        cs.fillAndStroke();
    }

    private static void drawText(PDPageContentStream cs, PDType1Font font, float size, double x, double y, String text, Color col) throws IOException {
        String safe = toWinAnsiSafe(text);
        if (safe.isEmpty()) {
            return;
        }
        cs.beginText();
        cs.setFont(font, size);
        cs.setNonStrokingColor(col);
        cs.newLineAtOffset((float) x, (float) y);
        cs.showText(safe);
        cs.endText();
    }

    public static String toWinAnsiSafe(String input) {
        if (input == null) {
            return "";
        }
        String s = input
                .replace("♯", "#")
                .replace("♭", "b")
                .replace("♮", "")
                .replace("→", "->")
                .replace("—", "-")
                .replace("–", "-")
                .replace("’", "'")
                .replace("“", "\"")
                .replace("”", "\"");
        StringBuilder out = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c >= 32 && c <= 126) {
                out.append(c);
            } else if (c >= 160 && c <= 255) {
                out.append(c);
            } else {
                String decomposed = Normalizer.normalize(String.valueOf(c), Normalizer.Form.NFD)
                        .replaceAll("\\p{M}", "");
                for (int j = 0; j < decomposed.length(); j++) {
                    char dc = decomposed.charAt(j);
                    if (dc >= 32 && dc <= 126) {
                        out.append(dc);
                    }
                }
            }
        }
        return out.toString();
    }

    private static List<String> wrapText(String text, int maxChars) {
        if (text == null || text.isBlank()) {
            return List.of();
        }
        List<String> lines = new ArrayList<>();
        String[] words = text.split("\\s+");
        StringBuilder cur = new StringBuilder();
        for (String w : words) {
            if (cur.length() + w.length() + 1 > maxChars && !cur.isEmpty()) {
                lines.add(cur.toString());
                cur.setLength(0);
            }
            if (!cur.isEmpty()) {
                cur.append(' ');
            }
            cur.append(w);
        }
        if (!cur.isEmpty()) {
            lines.add(cur.toString());
        }
        return lines;
    }
}
