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

import com.akkord.model.Models.ExtractedTextToken;
import com.akkord.model.Models.LayoutExtractionResult;
import com.akkord.model.Models.PageLayout;
import com.akkord.model.Models.StaffSystem;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.common.PDRectangle;
import org.apache.pdfbox.rendering.ImageType;
import org.apache.pdfbox.rendering.PDFRenderer;
import org.apache.pdfbox.text.PDFTextStripper;
import org.apache.pdfbox.text.TextPosition;

import javax.imageio.ImageIO;
import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Comparator;
import java.util.List;
import java.util.logging.Level;
import java.util.logging.Logger;
import java.util.regex.Pattern;
import java.util.zip.DeflaterOutputStream;

/**
 * Pure-Java 25 PDF layout detector, 2pt ink density grid analyzer, text/chord token extractor,
 * and visual guide PNG renderer powered by Apache PDFBox 3 and Java2D.
 */
public final class PdfLayoutAnalyzer {
    static {
        Logger.getLogger("org.apache.pdfbox").setLevel(Level.SEVERE);
        Logger.getLogger("org.apache.fontbox").setLevel(Level.SEVERE);
    }

    public static final float RENDER_DPI = 200.0f;
    public static final float SCALE = RENDER_DPI / 72.0f;

    private static final Pattern CHORD_TOKEN_RE = Pattern.compile(
            "^([A-G]|Do|Ré|Re|Mi|Fa|Sol|La|Si)[#b♯♭]?(m|maj|min|dim|aug|sus|add)?(6|7|9|11|13|M7|maj7)?([/#b♯♭A-G0-9+-])*$"
    );

    public static LayoutExtractionResult analyzePdf(File pdfFile, File workDir) throws IOException {
        if (!workDir.exists()) {
            workDir.mkdirs();
        }
        try (PDDocument doc = Loader.loadPDF(pdfFile)) {
            PDFRenderer renderer = new PDFRenderer(doc);
            int numPages = doc.getNumberOfPages();

            List<PageLayout> pages = new ArrayList<>(numPages);
            List<ExtractedTextToken> allChordTokens = new ArrayList<>();
            StringBuilder titleBuilder = new StringBuilder();

            for (int pageIdx = 0; pageIdx < numPages; pageIdx++) {
                int pageNum = pageIdx + 1;
                PDPage page = doc.getPage(pageIdx);
                PDRectangle mediaBox = page.getMediaBox();
                double widthPt = mediaBox.getWidth();
                double heightPt = mediaBox.getHeight();

                BufferedImage cleanImg = renderer.renderImageWithDPI(pageIdx, RENDER_DPI, ImageType.RGB);
                File cleanPng = new File(workDir, String.format("page_%d_clean.png", pageNum));
                ImageIO.write(cleanImg, "PNG", cleanPng);

                List<StaffSystem> systems = detectStaffSystems(cleanImg, widthPt, heightPt);
                InkGridData inkGrid = computeInkGrid2pt(cleanImg, widthPt, heightPt);

                double bottomFreePt = 72.0;
                if (!systems.isEmpty()) {
                    double minBottom = systems.stream().mapToDouble(StaffSystem::yBottomPt).min().orElse(72.0);
                    bottomFreePt = Math.max(0.0, minBottom);
                }

                File guidePng = new File(workDir, String.format("page_%d_guide.png", pageNum));
                renderGuideImage(cleanImg, systems, widthPt, heightPt, guidePng);

                pages.add(new PageLayout(
                        pageNum,
                        round1(widthPt),
                        round1(heightPt),
                        systems,
                        round1(bottomFreePt),
                        cleanPng.getAbsolutePath(),
                        guidePng.getAbsolutePath(),
                        inkGrid.b64,
                        inkGrid.cols,
                        inkGrid.rows,
                        inkGrid.raw
                ));

                PageTokenHarvest harvest = extractPageTokens(doc, pageNum, heightPt);
                if (pageNum == 1 && !harvest.titleCandidate.isBlank()) {
                    titleBuilder.append(harvest.titleCandidate);
                }
                allChordTokens.addAll(harvest.chordTokens);
            }

            return new LayoutExtractionResult(titleBuilder.toString().trim(), allChordTokens, pages);
        }
    }

    public static List<double[]> cleanSingleStaffCluster(List<Double> cluster) {
        if (cluster.size() < 4) {
            return List.of();
        }
        List<Double> c = new ArrayList<>(cluster);
        c.sort(Double::compareTo);
        while (c.size() > 5 && c.size() <= 9) {
            List<Double> gaps = new ArrayList<>(c.size() - 1);
            for (int i = 0; i < c.size() - 1; i++) {
                gaps.add(c.get(i + 1) - c.get(i));
            }
            List<Double> sortedGaps = new ArrayList<>(gaps);
            sortedGaps.sort(Double::compareTo);
            double medianGap = sortedGaps.get(sortedGaps.size() / 2);
            double topGap = gaps.getFirst();
            double botGap = gaps.getLast();
            if (topGap > medianGap * 1.35 && topGap >= botGap) {
                c.removeFirst();
            } else if (botGap > medianGap * 1.35) {
                c.removeLast();
            } else {
                break;
            }
        }
        if (c.size() >= 4 && c.size() <= 8) {
            double top = c.getFirst();
            double bot = c.getLast();
            double h = bot - top;
            if (h >= 8.0 && h <= 46.0) {
                return List.of(new double[]{top, bot, c.size()});
            }
        }
        if (c.size() >= 9) {
            int maxGapIdx = 0;
            double maxGap = -1.0;
            for (int i = 0; i < c.size() - 1; i++) {
                double gap = c.get(i + 1) - c.get(i);
                if (gap > maxGap) {
                    maxGap = gap;
                    maxGapIdx = i;
                }
            }
            double meanGap = (c.getLast() - c.getFirst()) / (c.size() - 1);
            if (maxGap > meanGap * 1.6) {
                List<double[]> out = new ArrayList<>();
                out.addAll(cleanSingleStaffCluster(c.subList(0, maxGapIdx + 1)));
                out.addAll(cleanSingleStaffCluster(c.subList(maxGapIdx + 1, c.size())));
                return out;
            }
        }
        return List.of();
    }

    private static List<StaffSystem> detectStaffSystems(BufferedImage img, double widthPt, double heightPt) {
        int imgW = img.getWidth();
        int imgH = img.getHeight();
        int xStart = (int) (imgW * 0.12);
        int xEnd = (int) (imgW * 0.88);
        int spanW = Math.max(1, xEnd - xStart);

        int numSlices = 6;
        int sliceW = Math.max(1, spanW / numSlices);
        double[] rowDarkRatio = new double[imgH];

        for (int y = 0; y < imgH; y++) {
            double bestPairRatio = 0.0;
            double totalDark = 0;
            double[] sliceRatios = new double[numSlices];
            for (int s = 0; s < numSlices; s++) {
                int sx0 = xStart + s * sliceW;
                int sx1 = (s == numSlices - 1) ? xEnd : (sx0 + sliceW);
                int darkCount = 0;
                for (int x = sx0; x < sx1; x++) {
                    int rgb = img.getRGB(x, y);
                    int r = (rgb >> 16) & 0xFF;
                    int g = (rgb >> 8) & 0xFF;
                    int b = rgb & 0xFF;
                    int lum = (r * 77 + g * 150 + b * 29) >> 8;
                    if (lum < 185) {
                        darkCount++;
                        totalDark++;
                    }
                }
                sliceRatios[s] = (double) darkCount / Math.max(1, sx1 - sx0);
            }
            for (int s = 0; s < numSlices - 1; s++) {
                double pairAvg = 0.5 * (sliceRatios[s] + sliceRatios[s + 1]);
                if (pairAvg > bestPairRatio) {
                    bestPairRatio = pairAvg;
                }
            }
            double fullRatio = totalDark / spanW;
            rowDarkRatio[y] = Math.max(fullRatio, bestPairRatio * 0.88);
        }

        List<Double> lineCentersPt = new ArrayList<>();
        int y = 0;
        while (y < imgH) {
            if (rowDarkRatio[y] >= 0.43) {
                int y0 = y;
                while (y < imgH && rowDarkRatio[y] >= 0.38) {
                    y++;
                }
                int y1 = y - 1;
                int thickness = y1 - y0 + 1;
                if (thickness <= Math.max(8, (int) (4.5 * SCALE))) {
                    double centerPx = 0.5 * (y0 + y1);
                    double yPtFromTop = centerPx / SCALE;
                    lineCentersPt.add(yPtFromTop);
                }
            } else {
                y++;
            }
        }

        List<List<Double>> rawClusters = new ArrayList<>();
        for (double yTopDist : lineCentersPt) {
            if (rawClusters.isEmpty()) {
                List<Double> c = new ArrayList<>();
                c.add(yTopDist);
                rawClusters.add(c);
            } else {
                List<Double> last = rawClusters.getLast();
                double gap = yTopDist - last.getLast();
                if (gap <= 13.5) {
                    last.add(yTopDist);
                } else {
                    List<Double> c = new ArrayList<>();
                    c.add(yTopDist);
                    rawClusters.add(c);
                }
            }
        }

        List<double[]> stavesFromTop = new ArrayList<>();
        for (List<Double> cl : rawClusters) {
            stavesFromTop.addAll(cleanSingleStaffCluster(cl));
        }

        List<StaffSystem> systems = new ArrayList<>();
        int idx = 0;
        while (idx < stavesFromTop.size()) {
            double[] st = stavesFromTop.get(idx);
            double topDist = st[0];
            double botDist = st[1];
            double trebleH = Math.max(12.0, botDist - topDist);

            if (idx + 1 < stavesFromTop.size()) {
                double[] nextSt = stavesFromTop.get(idx + 1);
                double gapToNext = nextSt[0] - botDist;
                boolean nextIsTab = ((int) Math.round(nextSt[2])) == 6;
                if (nextIsTab && gapToNext <= trebleH * 2.8) {
                    botDist = nextSt[1];
                    idx += 2;
                } else {
                    idx++;
                }
            } else {
                idx++;
            }

            double yTopPt = heightPt - topDist;
            double yBottomPt = heightPt - botDist;
            double chordYPt = Math.min(heightPt - 14.0, yTopPt + Math.max(10.0, trebleH * 0.55));
            systems.add(new StaffSystem(
                    systems.size() + 1,
                    round1(yTopPt),
                    round1(yBottomPt),
                    round1(chordYPt),
                    round1(trebleH)
            ));
        }

        return systems;
    }

    private record InkGridData(String b64, int cols, int rows, byte[] raw) {}

    private static InkGridData computeInkGrid2pt(BufferedImage img, double widthPt, double heightPt) {
        int cols = Math.max(1, (int) Math.ceil(widthPt / 2.0));
        int rows = Math.max(1, (int) Math.ceil(heightPt / 2.0));
        byte[] raw = new byte[cols * rows];
        int imgW = img.getWidth();
        int imgH = img.getHeight();

        for (int r = 0; r < rows; r++) {
            double yTopPt = (r + 1) * 2.0;
            double yBotPt = r * 2.0;
            int py0 = Math.clamp((int) Math.floor((heightPt - yTopPt) * SCALE), 0, imgH - 1);
            int py1 = Math.clamp((int) Math.ceil((heightPt - yBotPt) * SCALE), py0 + 1, imgH);

            for (int c = 0; c < cols; c++) {
                int px0 = Math.clamp((int) Math.floor((c * 2.0) * SCALE), 0, imgW - 1);
                int px1 = Math.clamp((int) Math.ceil(((c + 1) * 2.0) * SCALE), px0 + 1, imgW);
                int dark = 0;
                int total = 0;
                for (int py = py0; py < py1; py++) {
                    for (int px = px0; px < px1; px++) {
                        int rgb = img.getRGB(px, py);
                        int red = (rgb >> 16) & 0xFF;
                        int grn = (rgb >> 8) & 0xFF;
                        int blu = rgb & 0xFF;
                        int lum = (red * 77 + grn * 150 + blu * 29) >> 8;
                        if (lum < 215) {
                            dark++;
                        }
                        total++;
                    }
                }
                int val = total > 0 ? Math.min(255, (dark * 255) / total) : 0;
                raw[r * cols + c] = (byte) val;
            }
        }

        try {
            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            try (DeflaterOutputStream dos = new DeflaterOutputStream(baos)) {
                dos.write(raw);
            }
            String b64 = Base64.getEncoder().encodeToString(baos.toByteArray());
            return new InkGridData(b64, cols, rows, raw);
        } catch (IOException e) {
            return new InkGridData("", cols, rows, raw);
        }
    }

    private static void renderGuideImage(BufferedImage cleanImg, List<StaffSystem> systems, double widthPt, double heightPt, File outFile) throws IOException {
        int w = cleanImg.getWidth();
        int h = cleanImg.getHeight();
        BufferedImage guide = new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = guide.createGraphics();
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
        g.drawImage(cleanImg, 0, 0, null);

        g.setStroke(new BasicStroke(1.2f));
        g.setFont(new Font("SansSerif", Font.BOLD, 16));
        for (int xPt = 50; xPt < (int) widthPt; xPt += 50) {
            int px = (int) Math.round(xPt * SCALE);
            g.setColor(new Color(220, 38, 38, 95));
            g.drawLine(px, 0, px, h);
            g.setColor(new Color(185, 28, 28, 220));
            g.drawString(String.valueOf(xPt), px + 3, 22);
        }

        Color[] palette = {
                new Color(37, 99, 235),
                new Color(16, 185, 129),
                new Color(217, 119, 6),
                new Color(147, 51, 234)
        };
        g.setFont(new Font("SansSerif", Font.BOLD, 20));
        for (StaffSystem sys : systems) {
            Color col = palette[(sys.index() - 1) % palette.length];
            int yTopPx = (int) Math.round((heightPt - sys.yTopPt()) * SCALE);
            int yBotPx = (int) Math.round((heightPt - sys.yBottomPt()) * SCALE);
            int bandH = Math.max(8, yBotPx - yTopPx);

            g.setColor(new Color(col.getRed(), col.getGreen(), col.getBlue(), 38));
            g.fillRect(0, yTopPx, w, bandH);
            g.setColor(new Color(col.getRed(), col.getGreen(), col.getBlue(), 210));
            g.drawRect(2, yTopPx, w - 4, bandH);
            g.fillRect(4, yTopPx, 48, 26);
            g.setColor(Color.WHITE);
            g.drawString("S" + sys.index(), 10, yTopPx + 20);
        }
        g.dispose();
        ImageIO.write(guide, "PNG", outFile);
    }

    private record PageTokenHarvest(String titleCandidate, List<ExtractedTextToken> chordTokens) {}

    private static PageTokenHarvest extractPageTokens(PDDocument doc, int pageNum, double heightPt) throws IOException {
        record RawWord(double xPt, double yPt, String text) {}
        List<RawWord> words = new ArrayList<>();

        PDFTextStripper stripper = new PDFTextStripper() {
            @Override
            protected void writeString(String text, List<TextPosition> textPositions) throws IOException {
                if (textPositions == null || textPositions.isEmpty()) {
                    return;
                }
                StringBuilder cur = new StringBuilder();
                double startX = textPositions.getFirst().getXDirAdj();
                double startYTop = textPositions.getFirst().getYDirAdj();
                double prevEndX = startX;

                for (TextPosition tp : textPositions) {
                    String ch = tp.getUnicode();
                    if (ch == null || ch.isBlank()) {
                        if (!cur.isEmpty()) {
                            words.add(new RawWord(startX, heightPt - startYTop, cur.toString().trim()));
                            cur.setLength(0);
                        }
                        continue;
                    }
                    double x = tp.getXDirAdj();
                    if (cur.isEmpty()) {
                        startX = x;
                        startYTop = tp.getYDirAdj();
                    } else if (Math.abs(x - prevEndX) > tp.getWidthDirAdj() * 1.4) {
                        words.add(new RawWord(startX, heightPt - startYTop, cur.toString().trim()));
                        cur.setLength(0);
                        startX = x;
                        startYTop = tp.getYDirAdj();
                    }
                    cur.append(ch);
                    prevEndX = x + tp.getWidthDirAdj();
                }
                if (!cur.isEmpty()) {
                    words.add(new RawWord(startX, heightPt - startYTop, cur.toString().trim()));
                }
            }
        };
        stripper.setStartPage(pageNum);
        stripper.setEndPage(pageNum);
        stripper.getText(doc);

        words.sort(Comparator.comparingDouble((RawWord w) -> -w.yPt).thenComparingDouble(w -> w.xPt));

        StringBuilder titleSb = new StringBuilder();
        for (RawWord w : words) {
            if (w.yPt > heightPt * 0.78 && titleSb.length() < 90) {
                if (!titleSb.isEmpty()) {
                    titleSb.append(' ');
                }
                titleSb.append(w.text);
            }
        }

        List<ExtractedTextToken> chordTokens = new ArrayList<>();
        int i = 0;
        while (i < words.size()) {
            RawWord w = words.get(i);
            String tok = w.text.replaceAll("^[,.;:()\\[\\]]+|[,.;:()\\[\\]]+$", "");
            if (i + 1 < words.size()) {
                RawWord next = words.get(i + 1);
                if (Math.abs(next.yPt - w.yPt) <= 3.5 && (next.xPt - w.xPt) > 0 && (next.xPt - w.xPt) <= 22.0) {
                    if (tok.matches("^[A-G][#b♯♭]?$") && next.text.matches("^(m|m7|7|maj7|dim)$")) {
                        tok = tok + next.text;
                        i++;
                    }
                }
            }
            if (isLikelyChordToken(tok)) {
                chordTokens.add(new ExtractedTextToken(pageNum, round1(w.xPt), round1(w.yPt), tok));
            }
            i++;
        }

        return new PageTokenHarvest(titleSb.toString().trim(), chordTokens);
    }

    public static boolean isLikelyChordToken(String tok) {
        if (tok == null || tok.isEmpty() || tok.length() > 12) {
            return false;
        }
        if (tok.equals("I") || tok.equals("V") || tok.equals("X") || tok.equals("TAB")) {
            return false;
        }
        return CHORD_TOKEN_RE.matcher(tok).matches();
    }

    private static double round1(double v) {
        return Math.round(v * 10.0) / 10.0;
    }
}
