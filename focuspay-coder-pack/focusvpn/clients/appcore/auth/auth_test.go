package auth

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"

	"focusvpn.example/focusvpn/clients/appcore/apierr"
	"focusvpn.example/focusvpn/clients/appcore/storage"
	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

func TestEnsureAccessRefreshesInsideLead(t *testing.T) {
	var refreshes atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/auth/login":
			_ = json.NewEncoder(w).Encode(apitypes.AuthResponse{
				User:   apitypes.UserDTO{Email: "a@b.c"},
				Tokens: apitypes.Tokens{AccessToken: "old", RefreshToken: "rt", ExpiresIn: 30},
			})
		case "/v1/auth/refresh":
			refreshes.Add(1)
			if r.Header.Get("Authorization") != "Bearer rt" {
				t.Errorf("refresh bearer %q", r.Header.Get("Authorization"))
			}
			_ = json.NewEncoder(w).Encode(apitypes.RefreshResponse{
				AccessToken: "new", RefreshToken: "rt2", ExpiresIn: 900,
			})
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	s := New(srv.URL, storage.NewMemory())
	if err := s.Login(context.Background(), "a@b.c", "secret-secret"); err != nil {
		t.Fatal(err)
	}
	tok, err := s.EnsureAccess(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if tok != "new" || refreshes.Load() != 1 {
		t.Fatalf("token %q refreshes %d", tok, refreshes.Load())
	}
	tok, err = s.EnsureAccess(context.Background())
	if err != nil || tok != "new" || refreshes.Load() != 1 {
		t.Fatalf("second token %q refreshes %d err %v", tok, refreshes.Load(), err)
	}
}

func TestTelegramWaitThenCode(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/auth/telegram/start":
			_ = json.NewEncoder(w).Encode(TelegramStart{
				DeepLink: "https://t.me/focusvpn1_bot?start=vpnauth_x", WaitToken: "wait", ExpiresIn: 300,
			})
		case r.URL.Path == "/v1/auth/telegram/wait" && r.URL.Query().Get("wait_token") == "wait":
			w.WriteHeader(http.StatusAccepted)
			_, _ = w.Write([]byte(`{"status":"pending"}`))
		case r.URL.Path == "/v1/auth/telegram/code":
			var body struct {
				Code string `json:"code"`
			}
			_ = json.NewDecoder(r.Body).Decode(&body)
			if body.Code != "AB12CD" {
				apiErr(w, http.StatusUnauthorized, "invalid_code", "nope")
				return
			}
			_ = json.NewEncoder(w).Encode(apitypes.AuthResponse{
				User:   apitypes.UserDTO{Email: "tg@focusvpn"},
				Tokens: apitypes.Tokens{AccessToken: "acc", RefreshToken: "ref", ExpiresIn: 900},
			})
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	s := New(srv.URL, storage.NewMemory())
	start, err := s.TelegramStart(context.Background())
	if err != nil || start.WaitToken != "wait" || start.DeepLink == "" {
		t.Fatalf("start %+v %v", start, err)
	}
	_, ready, err := s.TelegramWait(context.Background(), start.WaitToken)
	if err != nil || ready {
		t.Fatalf("pending ready=%v err=%v", ready, err)
	}
	_, err = s.LoginCode(context.Background(), "NOPE")
	if err == nil {
		t.Fatal("expected bad code")
	}
	if apierr.IsAccessRejected(err) {
		t.Fatal("invalid code is not a dead session")
	}
	tok, err := s.AccessToken()
	if err == nil && tok != "" {
		t.Fatal("bad code stored a token")
	}
	resp, err := s.LoginCode(context.Background(), "AB12CD")
	if err != nil || resp.User.Email != "tg@focusvpn" {
		t.Fatalf("code %+v %v", resp, err)
	}
	tok, err = s.AccessToken()
	if err != nil || tok != "acc" {
		t.Fatalf("token %q %v", tok, err)
	}
}

func TestRefreshAfterRejectSkipsSecondPresentation(t *testing.T) {
	var n atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/auth/refresh" {
			http.NotFound(w, r)
			return
		}
		n.Add(1)
		_ = json.NewEncoder(w).Encode(apitypes.RefreshResponse{
			AccessToken: "second", RefreshToken: "rt2", ExpiresIn: 900,
		})
	}))
	defer srv.Close()
	st := storage.NewMemory()
	_ = st.Set(storage.KeyAccessToken, []byte("first"))
	_ = st.Set(storage.KeyRefreshToken, []byte("rt"))
	s := New(srv.URL, st)
	tok, err := s.RefreshAfterReject(context.Background(), "first")
	if err != nil || tok != "second" || n.Load() != 1 {
		t.Fatalf("tok %q n %d err %v", tok, n.Load(), err)
	}
	tok, err = s.RefreshAfterReject(context.Background(), "first")
	if err != nil || tok != "second" || n.Load() != 1 {
		t.Fatalf("replay tok %q n %d err %v", tok, n.Load(), err)
	}
}

func apiErr(w http.ResponseWriter, status int, code, msg string) {
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{
		"error": map[string]string{"code": code, "message": msg},
	})
}
