package httpx

import (
	"net/http"

	"focusvpn.example/focusvpn/clients/shared/apitypes"
)

// Health handles GET /v1/health with a static OK payload.
func Health(w http.ResponseWriter, r *http.Request) {
	WriteJSON(w, http.StatusOK, apitypes.HealthResponse{Status: "ok"})
}
