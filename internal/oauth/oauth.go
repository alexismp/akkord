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

// Package oauth handles Google OAuth 2.0 authorization code flow, token refresh,
// and stateless HMAC-SHA256 + zlib session cookies compatible with the Python server.
package oauth

import (
	"bytes"
	"compress/zlib"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/alexismp/akkord/internal/config"
	"github.com/alexismp/akkord/internal/store"
)

const (
	GoogleAuthURL     = "https://accounts.google.com/o/oauth2/v2/auth"
	GoogleTokenURL    = "https://oauth2.googleapis.com/token"
	GoogleUserInfoURL = "https://www.googleapis.com/oauth2/v2/userinfo"
)

var OAuthScopes = []string{
	"openid",
	"https://www.googleapis.com/auth/userinfo.email",
	"https://www.googleapis.com/auth/userinfo.profile",
	"https://www.googleapis.com/auth/drive",
	"https://www.googleapis.com/auth/gmail.send",
}

// UserSession represents an authenticated Google OAuth 2.0 user session.
type UserSession struct {
	SessionID    string  `json:"session_id"`
	Email        string  `json:"email"`
	Name         string  `json:"name"`
	Picture      string  `json:"picture"`
	AccessToken  string  `json:"access_token"`
	RefreshToken string  `json:"refresh_token"`
	ExpiresAt    float64 `json:"expires_at"`
	CreatedAt    float64 `json:"created_at"`
}

// IsAdmin returns true if the user is the configured administrator (alexis.mp@gmail.com).
func (s *UserSession) IsAdmin() bool {
	return strings.EqualFold(strings.TrimSpace(s.Email), config.AdminEmail)
}

// IsExpired returns true if the access token is within 60 seconds of expiry.
func (s *UserSession) IsExpired() bool {
	return float64(time.Now().Unix()) >= (s.ExpiresAt - 60.0)
}

// ToPublicDict returns the safe public JSON representation of the user session.
func (s *UserSession) ToPublicDict() map[string]any {
	return map[string]any{
		"authenticated": true,
		"email":         s.Email,
		"name":          s.Name,
		"picture":       s.Picture,
		"is_admin":      s.IsAdmin(),
	}
}

func (s *UserSession) toMap() map[string]any {
	return map[string]any{
		"session_id":    s.SessionID,
		"email":         s.Email,
		"name":          s.Name,
		"picture":       s.Picture,
		"access_token":  s.AccessToken,
		"refresh_token": s.RefreshToken,
		"expires_at":    s.ExpiresAt,
		"created_at":    s.CreatedAt,
	}
}

func sessionFromMap(m map[string]any) *UserSession {
	if m == nil {
		return nil
	}
	email, _ := m["email"].(string)
	if email == "" {
		return nil
	}
	sid, _ := m["session_id"].(string)
	name, _ := m["name"].(string)
	pic, _ := m["picture"].(string)
	at, _ := m["access_token"].(string)
	rt, _ := m["refresh_token"].(string)
	var exp, crt float64
	switch v := m["expires_at"].(type) {
	case float64:
		exp = v
	case int:
		exp = float64(v)
	}
	switch v := m["created_at"].(type) {
	case float64:
		crt = v
	case int:
		crt = float64(v)
	}
	return &UserSession{
		SessionID:    sid,
		Email:        email,
		Name:         name,
		Picture:      pic,
		AccessToken:  at,
		RefreshToken: rt,
		ExpiresAt:    exp,
		CreatedAt:    crt,
	}
}

// OAuthManager manages OAuth 2.0 login, callback, token refresh, and stateless cookie encoding.
type OAuthManager struct {
	OutputDir       string
	SessionsPath    string
	ClientID        string
	ClientSecret    string
	RedirectURI     string
	Firestore       *store.FirestoreBackend
	pendingStates   map[string]float64
	sessions        map[string]*UserSession
	mu              sync.Mutex
}

// NewOAuthManager creates an OAuthManager.
func NewOAuthManager(outputDir string, fs *store.FirestoreBackend) *OAuthManager {
	if outputDir == "" {
		outputDir = config.DefaultOutputDir()
	}
	_ = os.MkdirAll(outputDir, 0o755)
	if fs == nil {
		fs = store.NewFirestoreBackend("", filepath.Join(outputDir, "_firestore_mirror"))
	}
	m := &OAuthManager{
		OutputDir:     outputDir,
		SessionsPath:  filepath.Join(outputDir, "oauth_sessions.json"),
		ClientID:      config.EnvOr("AKKORD_OAUTH_CLIENT_ID", config.DefaultOAuthClient),
		ClientSecret:  strings.TrimSpace(os.Getenv("AKKORD_OAUTH_CLIENT_SECRET")),
		RedirectURI:   config.EnvOr("AKKORD_OAUTH_REDIRECT_URI", config.DefaultRedirectURI),
		Firestore:     fs,
		pendingStates: make(map[string]float64),
		sessions:      make(map[string]*UserSession),
	}
	m.loadSessions()
	return m
}

// IsConfigured returns true when both ClientID and ClientSecret are present.
func (m *OAuthManager) IsConfigured() bool {
	return m.ClientID != "" && m.ClientSecret != ""
}

func (m *OAuthManager) signingKey() []byte {
	secret := config.EnvOr("AKKORD_SESSION_SECRET", m.ClientSecret)
	if secret == "" {
		secret = "akkord-default-session-secret-key"
	}
	sum := sha256.Sum256([]byte(secret))
	return sum[:]
}

// EncodeSessionCookie encodes a UserSession into a signed `v1.<b64>.<sig>` cookie token.
func (m *OAuthManager) EncodeSessionCookie(s *UserSession) string {
	payload := map[string]any{
		"sid": s.SessionID,
		"em":  s.Email,
		"nm":  s.Name,
		"pic": s.Picture,
		"at":  s.AccessToken,
		"rt":  s.RefreshToken,
		"exp": s.ExpiresAt,
		"crt": s.CreatedAt,
	}
	rawJSON, err := json.Marshal(payload)
	if err != nil {
		return s.SessionID
	}
	var compressed bytes.Buffer
	zw, err := zlib.NewWriterLevel(&compressed, zlib.BestCompression)
	if err != nil {
		return s.SessionID
	}
	_, _ = zw.Write(rawJSON)
	_ = zw.Close()

	b64 := strings.TrimRight(base64.URLEncoding.EncodeToString(compressed.Bytes()), "=")
	mac := hmac.New(sha256.New, m.signingKey())
	mac.Write([]byte(b64))
	sig := hex.EncodeToString(mac.Sum(nil))[:32]
	token := fmt.Sprintf("v1.%s.%s", b64, sig)
	if len(token) > 3800 {
		return s.SessionID
	}
	return token
}

// DecodeSessionCookie verifies and unpacks a `v1.<b64>.<sig>` stateless cookie token.
func (m *OAuthManager) DecodeSessionCookie(cookieValue string) *UserSession {
	if !strings.HasPrefix(cookieValue, "v1.") {
		return nil
	}
	parts := strings.Split(cookieValue, ".")
	if len(parts) != 3 {
		return nil
	}
	b64 := parts[1]
	sig := parts[2]

	mac := hmac.New(sha256.New, m.signingKey())
	mac.Write([]byte(b64))
	expectedSig := hex.EncodeToString(mac.Sum(nil))[:32]
	if !hmac.Equal([]byte(sig), []byte(expectedSig)) {
		return nil
	}

	padded := b64
	if rem := len(padded) % 4; rem != 0 {
		padded += strings.Repeat("=", 4-rem)
	}
	compressed, err := base64.URLEncoding.DecodeString(padded)
	if err != nil {
		return nil
	}
	zr, err := zlib.NewReader(bytes.NewReader(compressed))
	if err != nil {
		return nil
	}
	defer zr.Close()
	rawJSON, err := io.ReadAll(zr)
	if err != nil {
		return nil
	}
	var data map[string]any
	if json.Unmarshal(rawJSON, &data) != nil {
		return nil
	}
	email, _ := data["em"].(string)
	if email == "" {
		return nil
	}
	sid, _ := data["sid"].(string)
	if sid == "" {
		sid = randToken(16)
	}
	name, _ := data["nm"].(string)
	pic, _ := data["pic"].(string)
	at, _ := data["at"].(string)
	rt, _ := data["rt"].(string)
	exp, _ := data["exp"].(float64)
	crt, _ := data["crt"].(float64)
	return &UserSession{
		SessionID:    sid,
		Email:        email,
		Name:         name,
		Picture:      pic,
		AccessToken:  at,
		RefreshToken: rt,
		ExpiresAt:    exp,
		CreatedAt:    crt,
	}
}

func (m *OAuthManager) loadSessions() {
	m.mu.Lock()
	defer m.mu.Unlock()
	raw, err := os.ReadFile(m.SessionsPath)
	if err != nil {
		return
	}
	var payload struct {
		Sessions map[string]map[string]any `json:"sessions"`
	}
	if json.Unmarshal(raw, &payload) == nil {
		for sid, sm := range payload.Sessions {
			if sess := sessionFromMap(sm); sess != nil {
				m.sessions[sid] = sess
			}
		}
	}
}

func (m *OAuthManager) saveSessionsUnlocked() {
	dump := make(map[string]map[string]any, len(m.sessions))
	for sid, s := range m.sessions {
		dump[sid] = s.toMap()
	}
	if raw, err := json.MarshalIndent(map[string]any{"sessions": dump}, "", "  "); err == nil {
		_ = os.WriteFile(m.SessionsPath, raw, 0o600)
	}
}

func randToken(bytesLen int) string {
	b := make([]byte, bytesLen)
	_, _ = rand.Read(b)
	return base64.RawURLEncoding.EncodeToString(b)
}

// ResolveRedirectURI determines the callback URL dynamically based on the request host.
func (m *OAuthManager) ResolveRedirectURI(requestBaseURL string) string {
	if explicit := strings.TrimSpace(os.Getenv("AKKORD_OAUTH_REDIRECT_URI")); explicit != "" {
		return explicit
	}
	if requestBaseURL != "" {
		return strings.TrimRight(requestBaseURL, "/") + "/auth/callback"
	}
	return m.RedirectURI
}

// BuildAuthorizationURL generates the Google OAuth 2.0 consent URL and CSRF state token.
func (m *OAuthManager) BuildAuthorizationURL(requestBaseURL string) (string, string) {
	state := randToken(24)
	now := float64(time.Now().Unix())
	m.mu.Lock()
	for k, ts := range m.pendingStates {
		if now-ts > 600 {
			delete(m.pendingStates, k)
		}
	}
	m.pendingStates[state] = now
	m.mu.Unlock()

	params := url.Values{}
	params.Set("client_id", m.ClientID)
	params.Set("redirect_uri", m.ResolveRedirectURI(requestBaseURL))
	params.Set("response_type", "code")
	params.Set("scope", strings.Join(OAuthScopes, " "))
	params.Set("access_type", "offline")
	params.Set("include_granted_scopes", "true")
	params.Set("prompt", "consent")
	params.Set("state", state)
	return GoogleAuthURL + "?" + params.Encode(), state
}

// ExchangeCodeForSession exchanges an authorization code for OAuth tokens and user profile.
func (m *OAuthManager) ExchangeCodeForSession(code, state, requestBaseURL string) (*UserSession, error) {
	if !m.IsConfigured() {
		return nil, fmt.Errorf("OAuth client credentials are not configured on this server")
	}
	if state != "" {
		m.mu.Lock()
		delete(m.pendingStates, state)
		m.mu.Unlock()
	}

	form := url.Values{}
	form.Set("code", code)
	form.Set("client_id", m.ClientID)
	form.Set("client_secret", m.ClientSecret)
	form.Set("redirect_uri", m.ResolveRedirectURI(requestBaseURL))
	form.Set("grant_type", "authorization_code")

	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.PostForm(GoogleTokenURL, form)
	if err != nil {
		return nil, fmt.Errorf("OAuth token exchange failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("OAuth token exchange HTTP %d: %s", resp.StatusCode, string(b))
	}

	var tokenPayload struct {
		AccessToken  string  `json:"access_token"`
		RefreshToken string  `json:"refresh_token"`
		ExpiresIn    float64 `json:"expires_in"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&tokenPayload); err != nil {
		return nil, fmt.Errorf("invalid OAuth token JSON: %w", err)
	}
	if tokenPayload.ExpiresIn <= 0 {
		tokenPayload.ExpiresIn = 3600
	}

	uReq, err := http.NewRequest("GET", GoogleUserInfoURL, nil)
	if err != nil {
		return nil, err
	}
	uReq.Header.Set("Authorization", "Bearer "+tokenPayload.AccessToken)
	uResp, err := client.Do(uReq)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch Google userinfo: %w", err)
	}
	defer uResp.Body.Close()
	var userInfo struct {
		Email   string `json:"email"`
		Name    string `json:"name"`
		Picture string `json:"picture"`
	}
	_ = json.NewDecoder(uResp.Body).Decode(&userInfo)

	email := strings.ToLower(strings.TrimSpace(userInfo.Email))
	name := strings.TrimSpace(userInfo.Name)
	if name == "" {
		name = email
	}

	m.mu.Lock()
	var prevRefresh string
	for _, existing := range m.sessions {
		if strings.EqualFold(existing.Email, email) && existing.RefreshToken != "" {
			prevRefresh = existing.RefreshToken
			break
		}
	}
	refreshTok := tokenPayload.RefreshToken
	if refreshTok == "" {
		refreshTok = prevRefresh
	}

	now := float64(time.Now().Unix())
	sess := &UserSession{
		SessionID:    randToken(32),
		Email:        email,
		Name:         name,
		Picture:      userInfo.Picture,
		AccessToken:  tokenPayload.AccessToken,
		RefreshToken: refreshTok,
		ExpiresAt:    now + tokenPayload.ExpiresIn,
		CreatedAt:    now,
	}
	m.sessions[sess.SessionID] = sess
	m.saveSessionsUnlocked()
	m.mu.Unlock()

	m.Firestore.SetDoc("akkord_oauth_sessions", sess.SessionID, sess.toMap())
	if email != "" && refreshTok != "" {
		m.Firestore.SetDoc("akkord_oauth_tokens", email, sess.toMap())
	}
	return sess, nil
}

// RefreshSession refreshes an expired access token using the stored refresh token.
func (m *OAuthManager) RefreshSession(sess *UserSession) bool {
	if sess == nil || sess.RefreshToken == "" || !m.IsConfigured() {
		return false
	}
	form := url.Values{}
	form.Set("client_id", m.ClientID)
	form.Set("client_secret", m.ClientSecret)
	form.Set("refresh_token", sess.RefreshToken)
	form.Set("grant_type", "refresh_token")

	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.PostForm(GoogleTokenURL, form)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return false
	}
	var payload struct {
		AccessToken string  `json:"access_token"`
		ExpiresIn   float64 `json:"expires_in"`
	}
	if json.NewDecoder(resp.Body).Decode(&payload) != nil || payload.AccessToken == "" {
		return false
	}
	if payload.ExpiresIn <= 0 {
		payload.ExpiresIn = 3600
	}
	sess.AccessToken = payload.AccessToken
	sess.ExpiresAt = float64(time.Now().Unix()) + payload.ExpiresIn

	m.mu.Lock()
	m.sessions[sess.SessionID] = sess
	m.saveSessionsUnlocked()
	m.mu.Unlock()

	m.Firestore.SetDoc("akkord_oauth_sessions", sess.SessionID, sess.toMap())
	if sess.Email != "" {
		m.Firestore.SetDoc("akkord_oauth_tokens", sess.Email, sess.toMap())
	}
	return true
}

// GetSession retrieves and validates a session from a cookie value or session ID.
func (m *OAuthManager) GetSession(sessionID string) *UserSession {
	if sessionID == "" {
		return nil
	}
	if decoded := m.DecodeSessionCookie(sessionID); decoded != nil {
		m.mu.Lock()
		m.sessions[decoded.SessionID] = decoded
		m.mu.Unlock()
		if decoded.IsExpired() {
			if !m.RefreshSession(decoded) {
				return nil
			}
		}
		return decoded
	}

	m.mu.Lock()
	sess := m.sessions[sessionID]
	m.mu.Unlock()

	if sess == nil {
		if doc := m.Firestore.GetDoc("akkord_oauth_sessions", sessionID); doc != nil {
			if loaded := sessionFromMap(doc); loaded != nil {
				m.mu.Lock()
				m.sessions[sessionID] = loaded
				m.saveSessionsUnlocked()
				m.mu.Unlock()
				sess = loaded
			}
		}
	}
	if sess == nil {
		return nil
	}
	if sess.IsExpired() {
		if !m.RefreshSession(sess) {
			return nil
		}
	}
	return sess
}

// DeleteSession removes a session from memory and Firestore.
func (m *OAuthManager) DeleteSession(sessionID string) {
	if sessionID == "" {
		return
	}
	realID := sessionID
	if decoded := m.DecodeSessionCookie(sessionID); decoded != nil {
		realID = decoded.SessionID
	}
	m.mu.Lock()
	_, existed := m.sessions[realID]
	delete(m.sessions, realID)
	if existed {
		m.saveSessionsUnlocked()
	}
	m.mu.Unlock()
	m.Firestore.DeleteDoc("akkord_oauth_sessions", realID)
}

// GetAdminAccessToken returns a valid OAuth access token for the admin user if available.
func (m *OAuthManager) GetAdminAccessToken() string {
	m.mu.Lock()
	var candidates []*UserSession
	for _, s := range m.sessions {
		if s.IsAdmin() {
			candidates = append(candidates, s)
		}
	}
	m.mu.Unlock()

	for _, s := range candidates {
		if s.IsExpired() {
			if m.RefreshSession(s) {
				return s.AccessToken
			}
		} else if s.AccessToken != "" {
			return s.AccessToken
		}
	}

	if doc := m.Firestore.GetDoc("akkord_oauth_tokens", config.AdminEmail); doc != nil {
		if loaded := sessionFromMap(doc); loaded != nil {
			m.mu.Lock()
			m.sessions[loaded.SessionID] = loaded
			m.mu.Unlock()
			if loaded.IsExpired() {
				if m.RefreshSession(loaded) {
					return loaded.AccessToken
				}
			} else if loaded.AccessToken != "" {
				return loaded.AccessToken
			}
		}
	}
	return ""
}
