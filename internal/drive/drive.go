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

// Package drive provides Google Drive API v3 and local filesystem connectors for music sheets.
package drive

import (
	"bytes"
	"encoding/json"
	"fmt"
	"html"
	"io"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/alexismp/akkord/internal/store"
)

var (
	driveFolderRegex = regexp.MustCompile(`/folders/([a-zA-Z0-9_-]+)`)
	driveIDParamRe   = regexp.MustCompile(`[?&]id=([a-zA-Z0-9_-]+)`)
	driveFileLinkRe  = regexp.MustCompile(`/file/d/([a-zA-Z0-9_-]+)`)
	driveRawIDRe     = regexp.MustCompile(`^[a-zA-Z0-9_-]{15,}$`)
	publicDrivePDFRe = regexp.MustCompile(`\["([a-zA-Z0-9_-]{25,45})"\s*,\s*\["[a-zA-Z0-9_-]+"\]\s*,\s*"([^"]+\.pdf)"`)
	publicDriveAltRe = regexp.MustCompile(`"([a-zA-Z0-9_-]{25,45})"[^[]{0,160}"([^"]+\.pdf)"`)
)

var GeneratedSuffixes = []string{
	"-avec-accords.pdf",
	"-analyse-accords.pdf",
	"-with-chords.pdf",
	"-chord-analysis.pdf",
}

// SheetFile represents a PDF music sheet from Google Drive or a local folder.
type SheetFile struct {
	ID            string `json:"id"`
	Name          string `json:"name"`
	LocalPath     string `json:"local_path,omitempty"`
	DriveParentID string `json:"drive_parent_id,omitempty"`
	WebViewLink   string `json:"web_view_link,omitempty"`
}

// IsGeneratedOutput returns true if filename already ends with an Akkord output suffix.
func IsGeneratedOutput(filename string) bool {
	lower := strings.ToLower(filename)
	for _, s := range GeneratedSuffixes {
		if strings.HasSuffix(lower, s) {
			return true
		}
	}
	return false
}

// ExtractFolderID extracts a Google Drive folder or file ID from a URL or ID string.
func ExtractFolderID(folderInput string) string {
	cleaned := strings.TrimSpace(folderInput)
	for _, re := range []*regexp.Regexp{driveFolderRegex, driveFileLinkRe, driveIDParamRe} {
		if m := re.FindStringSubmatch(cleaned); len(m) > 1 {
			return m[1]
		}
	}
	return cleaned
}

// DriveConnector lists, downloads, and uploads PDF files from Google Drive or local directories.
type DriveConnector struct {
	CredentialsPath  string
	OAuthAccessToken string
}

// NewDriveConnector creates a DriveConnector.
func NewDriveConnector(credentialsPath, oauthAccessToken string) *DriveConnector {
	return &DriveConnector{
		CredentialsPath:  credentialsPath,
		OAuthAccessToken: strings.TrimSpace(oauthAccessToken),
	}
}

func (d *DriveConnector) bearerToken() string {
	if d.OAuthAccessToken != "" {
		return d.OAuthAccessToken
	}
	return store.GlobalADC.GetAccessToken()
}

// ListPDFs lists all original music sheet PDFs in a local path or Google Drive folder/file.
func (d *DriveConnector) ListPDFs(folderOrPath string) ([]SheetFile, error) {
	cleaned := strings.TrimSpace(folderOrPath)
	if st, err := os.Stat(cleaned); err == nil {
		if !st.IsDir() && strings.HasSuffix(strings.ToLower(cleaned), ".pdf") {
			abs, _ := filepath.Abs(cleaned)
			return []SheetFile{
				{
					ID:        filepath.Base(cleaned),
					Name:      filepath.Base(cleaned),
					LocalPath: abs,
				},
			}, nil
		}
		if st.IsDir() {
			entries, err := os.ReadDir(cleaned)
			if err != nil {
				return nil, err
			}
			var names []string
			for _, e := range entries {
				if !e.IsDir() && strings.HasSuffix(strings.ToLower(e.Name()), ".pdf") && !IsGeneratedOutput(e.Name()) {
					names = append(names, e.Name())
				}
			}
			sort.Strings(names)
			out := make([]SheetFile, 0, len(names))
			for _, name := range names {
				abs, _ := filepath.Abs(filepath.Join(cleaned, name))
				out = append(out, SheetFile{
					ID:        name,
					Name:      name,
					LocalPath: abs,
				})
			}
			return out, nil
		}
	}

	if m := driveFileLinkRe.FindStringSubmatch(cleaned); len(m) > 1 {
		return d.getSingleDriveFile(m[1])
	}
	folderID := ExtractFolderID(cleaned)
	return d.listDriveFolder(folderID)
}

func (d *DriveConnector) driveGetJSON(endpoint string, params url.Values) (map[string]any, int, error) {
	token := d.bearerToken()
	if token == "" {
		return nil, 0, fmt.Errorf("no Google OAuth/ADC access token available")
	}
	fullURL := endpoint
	if len(params) > 0 {
		fullURL += "?" + params.Encode()
	}
	req, err := http.NewRequest("GET", fullURL, nil)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	client := &http.Client{Timeout: 20 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, resp.StatusCode, fmt.Errorf("Drive API HTTP %d: %s", resp.StatusCode, string(body))
	}
	var out map[string]any
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, resp.StatusCode, err
	}
	return out, resp.StatusCode, nil
}

func (d *DriveConnector) getSingleDriveFile(fileID string) ([]SheetFile, error) {
	params := url.Values{}
	params.Set("fields", "id, name, mimeType, parents, webViewLink")
	params.Set("supportsAllDrives", "true")
	meta, _, err := d.driveGetJSON("https://www.googleapis.com/drive/v3/files/"+url.PathEscape(fileID), params)
	if err == nil && meta != nil {
		mimeType, _ := meta["mimeType"].(string)
		if mimeType == "application/vnd.google-apps.folder" {
			return d.listDriveFolder(fileID)
		}
		name, _ := meta["name"].(string)
		if name == "" {
			name = fileID + ".pdf"
		}
		if !strings.HasSuffix(strings.ToLower(name), ".pdf") {
			name += ".pdf"
		}
		var parentID string
		if parents, ok := meta["parents"].([]any); ok && len(parents) > 0 {
			parentID, _ = parents[0].(string)
		}
		webLink, _ := meta["webViewLink"].(string)
		idStr, _ := meta["id"].(string)
		if idStr == "" {
			idStr = fileID
		}
		return []SheetFile{
			{
				ID:            idStr,
				Name:          name,
				DriveParentID: parentID,
				WebViewLink:   webLink,
			},
		}, nil
	}
	return []SheetFile{
		{
			ID:   fileID,
			Name: fileID + ".pdf",
		},
	}, nil
}

func (d *DriveConnector) listDriveFolder(folderID string) ([]SheetFile, error) {
	if token := d.bearerToken(); token != "" {
		metaParams := url.Values{}
		metaParams.Set("fields", "id, name, mimeType, parents, webViewLink, shortcutDetails")
		metaParams.Set("supportsAllDrives", "true")
		if meta, _, err := d.driveGetJSON("https://www.googleapis.com/drive/v3/files/"+url.PathEscape(folderID), metaParams); err == nil && meta != nil {
			mimeType, _ := meta["mimeType"].(string)
			if mimeType == "application/vnd.google-apps.shortcut" {
				if sc, ok := meta["shortcutDetails"].(map[string]any); ok {
					targetID, _ := sc["targetId"].(string)
					targetMime, _ := sc["targetMimeType"].(string)
					if targetID != "" {
						if targetMime == "application/vnd.google-apps.folder" {
							folderID = targetID
						} else {
							return d.getSingleDriveFile(targetID)
						}
					}
				}
			} else if mimeType != "" && mimeType != "application/vnd.google-apps.folder" {
				return d.getSingleDriveFile(folderID)
			}
		}

		items, err := d.listFolderChildrenAPI(folderID)
		if err == nil {
			var files []SheetFile
			var subfolders []string
			seen := make(map[string]bool)

			for _, item := range items {
				id, _ := item["id"].(string)
				name, _ := item["name"].(string)
				mime, _ := item["mimeType"].(string)
				webLink, _ := item["webViewLink"].(string)

				if mime == "application/vnd.google-apps.shortcut" {
					if sc, ok := item["shortcutDetails"].(map[string]any); ok {
						tid, _ := sc["targetId"].(string)
						tmime, _ := sc["targetMimeType"].(string)
						if tid != "" {
							id = tid
							mime = tmime
						}
					}
				}
				if mime == "application/vnd.google-apps.folder" && id != "" {
					subfolders = append(subfolders, id)
					continue
				}
				isPDF := mime == "application/pdf" || strings.HasSuffix(strings.ToLower(name), ".pdf")
				if isPDF && !IsGeneratedOutput(name) && id != "" && !seen[id] {
					seen[id] = true
					if !strings.HasSuffix(strings.ToLower(name), ".pdf") {
						name += ".pdf"
					}
					files = append(files, SheetFile{
						ID:            id,
						Name:          name,
						DriveParentID: folderID,
						WebViewLink:   webLink,
					})
				}
			}

			if len(files) == 0 && len(subfolders) > 0 {
				maxSub := len(subfolders)
				if maxSub > 10 {
					maxSub = 10
				}
				for _, subID := range subfolders[:maxSub] {
					subItems, err := d.listFolderChildrenAPI(subID)
					if err != nil {
						continue
					}
					for _, item := range subItems {
						id, _ := item["id"].(string)
						name, _ := item["name"].(string)
						mime, _ := item["mimeType"].(string)
						webLink, _ := item["webViewLink"].(string)
						isPDF := mime == "application/pdf" || strings.HasSuffix(strings.ToLower(name), ".pdf")
						if isPDF && !IsGeneratedOutput(name) && id != "" && !seen[id] {
							seen[id] = true
							if !strings.HasSuffix(strings.ToLower(name), ".pdf") {
								name += ".pdf"
							}
							files = append(files, SheetFile{
								ID:            id,
								Name:          name,
								DriveParentID: subID,
								WebViewLink:   webLink,
							})
						}
					}
				}
			}
			if len(files) > 0 || d.OAuthAccessToken != "" {
				return files, nil
			}
		}
	}

	return d.listPublicDriveFolder(folderID)
}

func (d *DriveConnector) listFolderChildrenAPI(parentID string) ([]map[string]any, error) {
	var all []map[string]any
	pageToken := ""
	q := fmt.Sprintf("'%s' in parents and trashed = false", parentID)
	for {
		params := url.Values{}
		params.Set("q", q)
		params.Set("fields", "nextPageToken, files(id, name, mimeType, webViewLink, shortcutDetails)")
		params.Set("orderBy", "name")
		params.Set("pageSize", "200")
		params.Set("supportsAllDrives", "true")
		params.Set("includeItemsFromAllDrives", "true")
		if pageToken != "" {
			params.Set("pageToken", pageToken)
		}
		resp, _, err := d.driveGetJSON("https://www.googleapis.com/drive/v3/files", params)
		if err != nil {
			return all, err
		}
		if rawFiles, ok := resp["files"].([]any); ok {
			for _, rf := range rawFiles {
				if m, ok := rf.(map[string]any); ok {
					all = append(all, m)
				}
			}
		}
		next, _ := resp["nextPageToken"].(string)
		if next == "" {
			break
		}
		pageToken = next
	}
	return all, nil
}

func (d *DriveConnector) listPublicDriveFolder(folderID string) ([]SheetFile, error) {
	if !driveRawIDRe.MatchString(folderID) {
		return nil, fmt.Errorf("local path or Drive folder not found: '%s'", folderID)
	}
	urls := []string{
		fmt.Sprintf("https://drive.google.com/embeddedfolderview?id=%s#list", folderID),
		fmt.Sprintf("https://drive.google.com/drive/folders/%s", folderID),
	}
	seen := make(map[string]bool)
	var files []SheetFile
	client := &http.Client{Timeout: 15 * time.Second}

	for _, u := range urls {
		req, err := http.NewRequest("GET", u, nil)
		if err != nil {
			continue
		}
		req.Header.Set("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
		resp, err := client.Do(req)
		if err != nil {
			continue
		}
		bodyBytes, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		pageHTML := html.UnescapeString(string(bodyBytes))

		for _, re := range []*regexp.Regexp{publicDrivePDFRe, publicDriveAltRe} {
			matches := re.FindAllStringSubmatch(pageHTML, -1)
			for _, m := range matches {
				if len(m) < 3 {
					continue
				}
				fid := m[1]
				fname := strings.ReplaceAll(m[2], `\u0026`, "&")
				if fid != folderID && !seen[fid] && !IsGeneratedOutput(fname) {
					seen[fid] = true
					files = append(files, SheetFile{
						ID:            fid,
						Name:          fname,
						DriveParentID: folderID,
						WebViewLink:   fmt.Sprintf("https://drive.google.com/file/d/%s/view", fid),
					})
				}
			}
		}
		if len(files) > 0 {
			break
		}
	}
	sort.Slice(files, func(i, j int) bool {
		return strings.ToLower(files[i].Name) < strings.ToLower(files[j].Name)
	})
	return files, nil
}

// BrowseDriveFolder returns subfolders, PDF files, and breadcrumb metadata for the interactive Drive picker.
func (d *DriveConnector) BrowseDriveFolder(folderID, searchQuery string) (map[string]any, error) {
	targetID := strings.TrimSpace(folderID)
	if targetID == "" {
		targetID = "root"
	} else if targetID != "root" && targetID != "shared" {
		targetID = ExtractFolderID(targetID)
	}

	currentFolder := map[string]any{
		"id":        targetID,
		"name":      "Mon Drive",
		"parent_id": nil,
	}
	if targetID == "shared" {
		currentFolder["name"] = "Partagés avec moi"
	} else if targetID != "root" {
		params := url.Values{}
		params.Set("fields", "id, name, parents")
		params.Set("supportsAllDrives", "true")
		if meta, _, err := d.driveGetJSON("https://www.googleapis.com/drive/v3/files/"+url.PathEscape(targetID), params); err == nil && meta != nil {
			name, _ := meta["name"].(string)
			if name == "" {
				name = targetID
			}
			var parentID any
			if parents, ok := meta["parents"].([]any); ok && len(parents) > 0 {
				parentID = parents[0]
			}
			currentFolder = map[string]any{
				"id":        meta["id"],
				"name":      name,
				"parent_id": parentID,
			}
		}
	}

	var q string
	if strings.TrimSpace(searchQuery) != "" {
		safeQ := strings.ReplaceAll(strings.TrimSpace(searchQuery), "'", "\\'")
		q = fmt.Sprintf("trashed = false and name contains '%s' and (mimeType = 'application/vnd.google-apps.folder' or mimeType = 'application/pdf')", safeQ)
	} else if targetID == "shared" {
		q = "sharedWithMe = true and trashed = false"
	} else {
		q = fmt.Sprintf("'%s' in parents and trashed = false", targetID)
	}

	params := url.Values{}
	params.Set("q", q)
	params.Set("fields", "files(id, name, mimeType, webViewLink, shortcutDetails, modifiedTime)")
	params.Set("orderBy", "folder,name")
	params.Set("pageSize", "150")
	params.Set("supportsAllDrives", "true")
	params.Set("includeItemsFromAllDrives", "true")

	resp, _, err := d.driveGetJSON("https://www.googleapis.com/drive/v3/files", params)
	if err != nil {
		return nil, err
	}

	var folders []map[string]any
	var pdfFiles []map[string]any
	rawFiles, _ := resp["files"].([]any)
	for _, rf := range rawFiles {
		item, ok := rf.(map[string]any)
		if !ok {
			continue
		}
		id, _ := item["id"].(string)
		name, _ := item["name"].(string)
		mime, _ := item["mimeType"].(string)
		if mime == "application/vnd.google-apps.shortcut" {
			if sc, ok := item["shortcutDetails"].(map[string]any); ok {
				tid, _ := sc["targetId"].(string)
				tmime, _ := sc["targetMimeType"].(string)
				if tid != "" {
					id = tid
					mime = tmime
				}
			}
		}
		if mime == "application/vnd.google-apps.folder" {
			folders = append(folders, map[string]any{
				"id":   id,
				"name": name,
			})
		} else if (mime == "application/pdf" || strings.HasSuffix(strings.ToLower(name), ".pdf")) && !IsGeneratedOutput(name) {
			pdfFiles = append(pdfFiles, map[string]any{
				"id":            id,
				"name":          name,
				"web_view_link": item["webViewLink"],
			})
		}
	}

	return map[string]any{
		"current_folder": currentFolder,
		"folders":        folders,
		"pdf_files":      pdfFiles,
		"total_pdfs":     len(pdfFiles),
	}, nil
}

// DownloadPDF downloads a SheetFile to destDir and returns the local PDF path.
func (d *DriveConnector) DownloadPDF(sheet SheetFile, destDir string) (string, error) {
	if sheet.LocalPath != "" {
		if _, err := os.Stat(sheet.LocalPath); err == nil {
			return sheet.LocalPath, nil
		}
	}
	_ = os.MkdirAll(destDir, 0o755)
	destPath := filepath.Join(destDir, filepath.Base(sheet.Name))

	if token := d.bearerToken(); token != "" {
		dlURL := fmt.Sprintf("https://www.googleapis.com/drive/v3/files/%s?alt=media&supportsAllDrives=true", url.PathEscape(sheet.ID))
		req, err := http.NewRequest("GET", dlURL, nil)
		if err == nil {
			req.Header.Set("Authorization", "Bearer "+token)
			client := &http.Client{Timeout: 45 * time.Second}
			if resp, err := client.Do(req); err == nil {
				defer resp.Body.Close()
				if resp.StatusCode == http.StatusOK {
					data, err := io.ReadAll(resp.Body)
					if err == nil && bytes.HasPrefix(data, []byte("%PDF")) {
						if err := os.WriteFile(destPath, data, 0o644); err == nil {
							return destPath, nil
						}
					}
				}
			}
		}
	}

	// Fallback to public Drive download URL
	pubURL := fmt.Sprintf("https://drive.google.com/uc?export=download&id=%s", url.QueryEscape(sheet.ID))
	req, err := http.NewRequest("GET", pubURL, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	if !bytes.HasPrefix(data, []byte("%PDF")) {
		return "", fmt.Errorf("downloaded file '%s' is not a valid PDF (check Drive sharing permissions)", sheet.Name)
	}
	if err := os.WriteFile(destPath, data, 0o644); err != nil {
		return "", err
	}
	return destPath, nil
}

// UploadPDF uploads an annotated PDF back to a Google Drive folder using multipart upload.
func (d *DriveConnector) UploadPDF(localPDFPath, parentFolderID, outputFilename string) (map[string]string, error) {
	if parentFolderID == "" {
		return nil, nil
	}
	token := d.bearerToken()
	if token == "" {
		return nil, fmt.Errorf("no OAuth/ADC token available to upload to Google Drive")
	}
	if outputFilename == "" {
		outputFilename = filepath.Base(localPDFPath)
	}
	pdfBytes, err := os.ReadFile(localPDFPath)
	if err != nil {
		return nil, err
	}

	var body bytes.Buffer
	mw := multipart.NewWriter(&body)

	metaHeader := make(textproto.MIMEHeader)
	metaHeader.Set("Content-Type", "application/json; charset=UTF-8")
	metaPart, err := mw.CreatePart(metaHeader)
	if err != nil {
		return nil, err
	}
	metaJSON, _ := json.Marshal(map[string]any{
		"name":     outputFilename,
		"parents":  []string{parentFolderID},
		"mimeType": "application/pdf",
	})
	_, _ = metaPart.Write(metaJSON)

	mediaHeader := make(textproto.MIMEHeader)
	mediaHeader.Set("Content-Type", "application/pdf")
	mediaPart, err := mw.CreatePart(mediaHeader)
	if err != nil {
		return nil, err
	}
	_, _ = mediaPart.Write(pdfBytes)
	_ = mw.Close()

	uploadURL := "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,webViewLink&supportsAllDrives=true"
	req, err := http.NewRequest("POST", uploadURL, &body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "multipart/related; boundary="+mw.Boundary())

	client := &http.Client{Timeout: 60 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	respBytes, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("Drive upload HTTP %d: %s", resp.StatusCode, string(respBytes))
	}
	var created struct {
		ID          string `json:"id"`
		WebViewLink string `json:"webViewLink"`
	}
	if err := json.Unmarshal(respBytes, &created); err != nil {
		return nil, err
	}
	return map[string]string{
		"id":          created.ID,
		"webViewLink": created.WebViewLink,
	}, nil
}
