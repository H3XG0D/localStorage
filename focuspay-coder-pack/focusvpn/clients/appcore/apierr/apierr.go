// Package apierr turns Control Plane error envelopes into the same Russian
// text the Android client shows.
package apierr

import (
	"encoding/json"
	"errors"
	"fmt"
)

// Error is a non-2xx API response. Error() is user-facing Russian.
type Error struct {
	Status int
	Code   string
	Body   string
}

func (e *Error) Error() string {
	if e == nil {
		return ""
	}
	switch e.Code {
	case "too_many_devices":
		return "Достигнут лимит устройств для тарифа"
	case "invalid_code", "expired":
		return "Код неверный или устарел — запросите новый в боте"
	case "invalid_token", "expired_token", "unauthorized":
		return "Сессия истекла — войдите снова"
	case "subscription_expired":
		return "Подписка не активна — продлите в Telegram-боте"
	case "rate_limited":
		return "Слишком много попыток — подождите минуту"
	case "node_unavailable":
		return "Сервер недоступен — выберите другую локацию"
	}
	var env struct {
		Error struct {
			Message string `json:"message"`
		} `json:"error"`
	}
	if json.Unmarshal([]byte(e.Body), &env) == nil && env.Error.Message != "" {
		return env.Error.Message
	}
	if e.Status > 0 {
		return fmt.Sprintf("Ошибка сервера (%d)", e.Status)
	}
	return "Ошибка сервера"
}

// FromBody parses an error envelope. Status is the HTTP code.
func FromBody(status int, body []byte) *Error {
	e := &Error{Status: status, Body: string(body)}
	var env struct {
		Error struct {
			Code string `json:"code"`
		} `json:"error"`
	}
	if json.Unmarshal(body, &env) == nil {
		e.Code = env.Error.Code
	}
	return e
}

// IsAccessRejected reports a dead or expired access token (401).
// A reused refresh token is the same shape and must not be retried.
func IsAccessRejected(err error) bool {
	var e *Error
	if !errors.As(err, &e) || e.Status != 401 {
		return false
	}
	return e.Code == "expired_token" || e.Code == "invalid_token"
}
