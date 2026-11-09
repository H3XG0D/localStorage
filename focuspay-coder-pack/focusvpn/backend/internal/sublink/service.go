// Package sublink issues a stable HTTPS key for Happ and similar clients.
// The Focus app keeps the login code; this URL is a device seat whose fetch
// returns the current VLESS server list.
package sublink

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"focusvpn.example/focusvpn/backend/internal/connections"
	"focusvpn.example/focusvpn/backend/internal/devices"
	mycrypto "focusvpn.example/focusvpn/backend/internal/platform/crypto"
	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

const (
	linkDeviceName = "Ключ"
	linkPlatform   = "link"
	defaultPublic  = "https://focuspay.org/vpn-api"
)

var (
	ErrBadRequest     = errors.New("bad_request")
	ErrNotFound       = errors.New("not_found")
	ErrNoSubscription = errors.New("no_subscription")
	ErrTooManyDevices = errors.New("too_many_devices")
	ErrNoNodes        = errors.New("no_nodes")
)

type deviceRegistrar interface {
	Create(ctx context.Context, userID, name, platform, appVersion, publicKeyB64 string) (store.Device, string, error)
	Revoke(ctx context.Context, deviceID, userID string) error
}

type connector interface {
	Create(ctx context.Context, userID, deviceID, protocol, country, region, preferredNode string) (connections.CreateResult, error)
}

// Service issues and renders subscription links.
type Service struct {
	links    store.SubLinkStore
	users    store.UserStore
	subs     store.SubscriptionStore
	devStore store.DeviceStore
	reg      deviceRegistrar
	conns    connector
	kek      mycrypto.KEK
	hasher   func(string) string
	public   string
	botUser  string
	now      func() time.Time
}

// Issued is the URL the bot shows.
type Issued struct {
	URL      string
	EndsAt   time.Time
	DeviceID string
}

// Page is the body Happ fetches.
type Page struct {
	Body    string
	Expires time.Time
	Support string
}

// NewService wires the link issuer. publicBase is the API origin without a
// trailing slash. An empty base falls back to the production origin.
func NewService(
	links store.SubLinkStore,
	users store.UserStore,
	subs store.SubscriptionStore,
	devs store.DeviceStore,
	reg deviceRegistrar,
	conns connector,
	kek mycrypto.KEK,
	hasher func(string) string,
	publicBase, botUsername string,
) *Service {
	base := strings.TrimRight(strings.TrimSpace(publicBase), "/")
	if base == "" {
		base = defaultPublic
	}
	return &Service{
		links: links, users: users, subs: subs, devStore: devs, reg: reg, conns: conns,
		kek: kek, hasher: hasher, public: base,
		botUser: strings.TrimPrefix(strings.TrimSpace(botUsername), "@"),
		now:     time.Now,
	}
}

// Issue returns the user's subscription URL, creating the link device when
// they do not have a live one. rotate revokes the current link first.
func (s *Service) Issue(ctx context.Context, telegramID int64, rotate bool) (Issued, error) {
	if telegramID <= 0 {
		return Issued{}, ErrBadRequest
	}
	user, err := s.users.GetUserByTelegramID(ctx, telegramID)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			return Issued{}, ErrNotFound
		}
		return Issued{}, err
	}
	sub, _, err := s.subs.GetActiveByUser(ctx, user.ID)
	if err != nil {
		if errors.Is(err, store.ErrNoSubscription) {
			return Issued{}, ErrNoSubscription
		}
		return Issued{}, err
	}
	if !rotate {
		if issued, ok, err := s.existing(ctx, user.ID, sub.EndsAt); err != nil {
			return Issued{}, err
		} else if ok {
			return issued, nil
		}
	} else if err := s.dropLive(ctx, user.ID); err != nil {
		return Issued{}, err
	}
	return s.create(ctx, user.ID, sub.EndsAt)
}

// Render answers a Happ fetch. A revoked device, a dead token, or a lapsed
// subscription does not return server lines.
func (s *Service) Render(ctx context.Context, token string) (Page, error) {
	token = strings.TrimSpace(token)
	if token == "" || len(token) > 128 {
		return Page{}, ErrNotFound
	}
	link, err := s.links.GetLiveSubLinkByTokenHash(ctx, s.hasher("sub:"+token))
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			return Page{}, ErrNotFound
		}
		return Page{}, err
	}
	dev, err := s.devStore.GetDeviceByID(ctx, link.DeviceID)
	if err != nil || dev.Status != "active" || dev.UserID != link.UserID {
		return Page{}, ErrNotFound
	}
	sub, _, err := s.subs.GetActiveByUser(ctx, link.UserID)
	if err != nil {
		if errors.Is(err, store.ErrNoSubscription) {
			return Page{}, ErrNoSubscription
		}
		return Page{}, err
	}
	res, err := s.conns.Create(ctx, link.UserID, link.DeviceID, store.ProtocolVLESS, "", "", "")
	if err != nil {
		return Page{}, mapConn(err)
	}
	servers, uuid, err := serversFromConfig(s.kek, res.Configuration)
	if err != nil {
		return Page{}, err
	}
	lines := ShareLinks(uuid, servers)
	if len(lines) == 0 {
		return Page{}, ErrNoNodes
	}
	raw := strings.Join(lines, "\n") + "\n"
	return Page{
		Body:    base64.StdEncoding.EncodeToString([]byte(raw)),
		Expires: sub.EndsAt,
		Support: s.supportURL(),
	}, nil
}

func (s *Service) supportURL() string {
	if s.botUser == "" {
		return ""
	}
	return "https://t.me/" + s.botUser
}

func (s *Service) existing(ctx context.Context, userID string, ends time.Time) (Issued, bool, error) {
	link, err := s.links.GetLiveSubLinkByUser(ctx, userID)
	if errors.Is(err, store.ErrNotFound) {
		return Issued{}, false, nil
	}
	if err != nil {
		return Issued{}, false, err
	}
	dev, err := s.devStore.GetDeviceByID(ctx, link.DeviceID)
	if err != nil || dev.Status != "active" || dev.UserID != userID {
		if err := s.drop(ctx, link, userID); err != nil {
			return Issued{}, false, err
		}
		return Issued{}, false, nil
	}
	plain, err := mycrypto.OpenEnvelope(map[string]mycrypto.KEK{s.kek.ID: s.kek}, link.TokenEnc)
	if err != nil {
		return Issued{}, false, err
	}
	return Issued{URL: s.public + "/v1/sub/" + string(plain), EndsAt: ends, DeviceID: link.DeviceID}, true, nil
}

func (s *Service) dropLive(ctx context.Context, userID string) error {
	link, err := s.links.GetLiveSubLinkByUser(ctx, userID)
	if errors.Is(err, store.ErrNotFound) {
		return nil
	}
	if err != nil {
		return err
	}
	return s.drop(ctx, link, userID)
}

func (s *Service) drop(ctx context.Context, link store.SubLink, userID string) error {
	dev, err := s.devStore.GetDeviceByID(ctx, link.DeviceID)
	if err == nil && dev.Status == "active" && dev.UserID == userID {
		if err := s.reg.Revoke(ctx, link.DeviceID, userID); err != nil && !errors.Is(err, devices.ErrNotFound) {
			return err
		}
	}
	if err := s.links.RevokeSubLink(ctx, link.ID, s.now()); err != nil && !errors.Is(err, store.ErrNotFound) {
		return err
	}
	return nil
}

func (s *Service) create(ctx context.Context, userID string, ends time.Time) (Issued, error) {
	key, err := randomKey()
	if err != nil {
		return Issued{}, err
	}
	dev, _, err := s.reg.Create(ctx, userID, linkDeviceName, linkPlatform, "", key)
	if errors.Is(err, devices.ErrTooManyDevs) {
		if issued, ok, eerr := s.existing(ctx, userID, ends); eerr != nil {
			return Issued{}, eerr
		} else if ok {
			return issued, nil
		}
		return Issued{}, ErrTooManyDevices
	}
	if err != nil {
		return Issued{}, err
	}
	if _, err := s.conns.Create(ctx, userID, dev.ID, store.ProtocolVLESS, "", "", ""); err != nil {
		_ = s.reg.Revoke(ctx, dev.ID, userID)
		return Issued{}, mapConn(err)
	}
	token, err := randomToken()
	if err != nil {
		_ = s.reg.Revoke(ctx, dev.ID, userID)
		return Issued{}, err
	}
	blob, _, err := mycrypto.Envelope(s.kek, []byte(token))
	if err != nil {
		_ = s.reg.Revoke(ctx, dev.ID, userID)
		return Issued{}, err
	}
	now := s.now()
	link := store.SubLink{
		ID: id.NewUUID(), UserID: userID, DeviceID: dev.ID,
		TokenHash: s.hasher("sub:" + token), TokenEnc: blob, CreatedAt: now,
	}
	if err := s.links.CreateSubLink(ctx, link); err != nil {
		_ = s.reg.Revoke(ctx, dev.ID, userID)
		if errors.Is(err, store.ErrConflict) {
			if issued, ok, eerr := s.existing(ctx, userID, ends); eerr != nil {
				return Issued{}, eerr
			} else if ok {
				return issued, nil
			}
		}
		return Issued{}, err
	}
	return Issued{URL: s.public + "/v1/sub/" + token, EndsAt: ends, DeviceID: dev.ID}, nil
}

func mapConn(err error) error {
	switch {
	case err == nil:
		return nil
	case errors.Is(err, connections.ErrSubscriptionExpired), errors.Is(err, store.ErrSubscriptionExpired), errors.Is(err, store.ErrNoSubscription):
		return ErrNoSubscription
	case errors.Is(err, connections.ErrNodeUnavailable):
		return ErrNoNodes
	case errors.Is(err, connections.ErrTooManyDevices):
		return ErrTooManyDevices
	default:
		return err
	}
}

type xrayServer struct {
	Node      string `json:"node"`
	Country   string `json:"country"`
	Address   string `json:"address"`
	Port      int    `json:"port"`
	SNI       string `json:"sni"`
	Host      string `json:"host"`
	Path      string `json:"path"`
	Transport string `json:"transport"`
	Network   string `json:"network"`
	Mode      string `json:"mode"`
}

func serversFromConfig(kek mycrypto.KEK, cfg store.Configuration) ([]Server, string, error) {
	plain, err := mycrypto.OpenEnvelope(map[string]mycrypto.KEK{kek.ID: kek}, cfg.ContentEncrypted)
	if err != nil {
		return nil, "", err
	}
	var parts struct {
		Xray struct {
			UUID    string       `json:"uuid"`
			Servers []xrayServer `json:"servers"`
		} `json:"xray"`
	}
	if err := json.Unmarshal(plain, &parts); err != nil {
		return nil, "", err
	}
	if parts.Xray.UUID == "" {
		return nil, "", ErrNoNodes
	}
	var out []Server
	for _, srv := range parts.Xray.Servers {
		tr := srv.Transport
		if tr == "" {
			tr = srv.Network
		}
		host := srv.Host
		if host == "" {
			host = srv.Address
		}
		sni := srv.SNI
		if sni == "" {
			sni = host
		}
		out = append(out, Server{
			Node: srv.Node, Country: srv.Country, Address: srv.Address, Port: srv.Port,
			SNI: sni, Host: host, Path: srv.Path, Transport: tr, Mode: srv.Mode,
		})
	}
	if len(out) == 0 {
		return nil, "", ErrNoNodes
	}
	return out, parts.Xray.UUID, nil
}

func randomKey() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(b), nil
}

func randomToken() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}
