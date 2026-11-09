package nodereg_test

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"focusvpn.example/focusvpn/backend/internal/nodereg"
	"focusvpn.example/focusvpn/backend/internal/platform/store/memory"
)

func TestRegisterIdempotentAndReport(t *testing.T) {
	st := memory.New()
	h := nodereg.NewHandler(st.Nodes(), st.NodeTokens(), st.Reports(), "secret")
	mux := http.NewServeMux()
	h.Routes(mux)

	body := []byte(`{"name":"DE1","country":"DE","region":"eu-central","hostname":"de1.example","capacity":400,"xray":{"transport":"xhttp","path":"/cdn/a","port":443}}`)
	post := func(token string, issue bool) *httptest.ResponseRecorder {
		b := body
		if issue {
			b = []byte(`{"name":"DE1","country":"DE","hostname":"de1.example","capacity":400,"issue_token":true,"xray":{"transport":"xhttp","path":"/cdn/a"}}`)
		}
		req := httptest.NewRequest(http.MethodPost, "/v1/internal/nodes", bytes.NewReader(b))
		req.Header.Set("X-Internal-Token", token)
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, req)
		return w
	}
	if w := post("", false); w.Code != http.StatusUnauthorized {
		t.Fatalf("no token: %d", w.Code)
	}
	w := post("secret", true)
	if w.Code != http.StatusOK {
		t.Fatalf("register: %d %s", w.Code, w.Body.String())
	}
	var first map[string]string
	if err := json.Unmarshal(w.Body.Bytes(), &first); err != nil {
		t.Fatal(err)
	}
	if first["node_id"] == "" || first["agent_token"] == "" {
		t.Fatalf("response: %v", first)
	}
	w = post("secret", false)
	var second map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &second)
	if second["node_id"] != first["node_id"] || second["endpoint_id"] != first["endpoint_id"] {
		t.Fatalf("not idempotent: %v vs %v", first, second)
	}
	if _, ok := second["agent_token"]; ok {
		t.Fatal("token issued without issue_token")
	}
	eps, _ := st.ListEndpoints(context.Background())
	if len(eps) != 1 || eps[0].State != "OFFLINE" || eps[0].Subnet != "10.210.1.0/24" {
		t.Fatalf("endpoint: %+v", eps)
	}

	req := httptest.NewRequest(http.MethodGet, "/v1/internal/reports/summary", nil)
	req.Header.Set("X-Internal-Token", "secret")
	w = httptest.NewRecorder()
	mux.ServeHTTP(w, req)
	if w.Code != http.StatusOK || !bytes.Contains(w.Body.Bytes(), []byte(`"name":"DE1"`)) {
		t.Fatalf("report: %d %s", w.Code, w.Body.String())
	}
}
