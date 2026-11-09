package memory

import (
	"context"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

func (s *Store) SubLinks() store.SubLinkStore { return s }

func (s *Store) CreateSubLink(_ context.Context, l store.SubLink) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.subLinks == nil {
		s.subLinks = make(map[string]store.SubLink)
	}
	if _, ok := s.subLinks[l.ID]; ok {
		return store.ErrConflict
	}
	for _, ex := range s.subLinks {
		if ex.TokenHash == l.TokenHash {
			return store.ErrConflict
		}
		if ex.RevokedAt == nil && l.RevokedAt == nil && ex.UserID == l.UserID {
			return store.ErrConflict
		}
	}
	cp := l
	cp.TokenEnc = append([]byte(nil), l.TokenEnc...)
	s.subLinks[l.ID] = cp
	return nil
}

func (s *Store) GetLiveSubLinkByUser(_ context.Context, userID string) (store.SubLink, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, l := range s.subLinks {
		if l.UserID == userID && l.RevokedAt == nil {
			l.TokenEnc = append([]byte(nil), l.TokenEnc...)
			return l, nil
		}
	}
	return store.SubLink{}, store.ErrNotFound
}

func (s *Store) GetLiveSubLinkByTokenHash(_ context.Context, hash string) (store.SubLink, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, l := range s.subLinks {
		if l.TokenHash == hash && l.RevokedAt == nil {
			l.TokenEnc = append([]byte(nil), l.TokenEnc...)
			return l, nil
		}
	}
	return store.SubLink{}, store.ErrNotFound
}

func (s *Store) RevokeSubLink(_ context.Context, id string, at time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	l, ok := s.subLinks[id]
	if !ok || l.RevokedAt != nil {
		return store.ErrNotFound
	}
	l.RevokedAt = &at
	s.subLinks[id] = l
	return nil
}
