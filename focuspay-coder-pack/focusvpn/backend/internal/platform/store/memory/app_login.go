package memory

import (
	"context"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

func (s *Store) CreateAppLogin(_ context.Context, req store.AppLoginRequest) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.appLogins == nil {
		s.appLogins = make(map[string]store.AppLoginRequest)
	}
	if _, ok := s.appLogins[req.ID]; ok {
		return store.ErrConflict
	}
	s.appLogins[req.ID] = req
	return nil
}

func (s *Store) CreatePairCodeLogin(_ context.Context, req store.AppLoginRequest) error {
	return s.CreateAppLogin(context.Background(), req)
}

func (s *Store) GetAppLoginByWaitHash(_ context.Context, hash string) (store.AppLoginRequest, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, r := range s.appLogins {
		if r.WaitTokenHash == hash {
			return r, nil
		}
	}
	return store.AppLoginRequest{}, store.ErrNotFound
}

func (s *Store) GetAppLoginByStartHash(_ context.Context, hash string) (store.AppLoginRequest, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, r := range s.appLogins {
		if r.StartTokenHash == hash {
			return r, nil
		}
	}
	return store.AppLoginRequest{}, store.ErrNotFound
}

func (s *Store) GetAppLoginByPairCodeHash(_ context.Context, hash string) (store.AppLoginRequest, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, r := range s.appLogins {
		if r.PairCodeHash == hash {
			return r, nil
		}
	}
	return store.AppLoginRequest{}, store.ErrNotFound
}

func (s *Store) AttachAppLogin(_ context.Context, startHash string, telegramID int64, userID string, at time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for id, r := range s.appLogins {
		if r.StartTokenHash != startHash {
			continue
		}
		if r.ConsumedAt != nil {
			return store.ErrConflict
		}
		if at.After(r.ExpiresAt) {
			return store.ErrNotFound
		}
		r.TelegramID = &telegramID
		r.UserID = &userID
		r.AttachedAt = &at
		s.appLogins[id] = r
		return nil
	}
	return store.ErrNotFound
}

func (s *Store) ConsumeAppLogin(_ context.Context, id string, at time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	r, ok := s.appLogins[id]
	if !ok {
		return store.ErrNotFound
	}
	if r.ConsumedAt != nil {
		return store.ErrConflict
	}
	r.ConsumedAt = &at
	s.appLogins[id] = r
	return nil
}

func (s *Store) AppLogins() store.AppLoginStore { return s }
