package xrayapplier

import (
	"context"
	"testing"
	"time"

	"focusvpn.example/focusvpn/node-agent/internal/poller"
)

type fakeAPI struct {
	users   map[string][]User // tag -> users
	added   []string
	removed []string
}

func (f *fakeAPI) ListUsers(_ context.Context, tag string) ([]User, error) {
	return append([]User(nil), f.users[tag]...), nil
}

func (f *fakeAPI) AddUser(_ context.Context, tag Tag, email, id string) error {
	f.users[tag.Name] = append(f.users[tag.Name], User{Email: email, UUID: id})
	f.added = append(f.added, tag.Name+":"+email)
	return nil
}

func (f *fakeAPI) RemoveUser(_ context.Context, tag, email string) error {
	cur := f.users[tag]
	next := cur[:0]
	for _, u := range cur {
		if u.Email != email {
			next = append(next, u)
		}
	}
	f.users[tag] = next
	f.removed = append(f.removed, tag+":"+email)
	return nil
}

func (f *fakeAPI) OnlineCount(context.Context) (int, error) { return 2, nil }
func (f *fakeAPI) Traffic(context.Context) (int64, int64, error) {
	return 100, 40, nil
}

func TestApplyAddsRemovesAndKeepsManualUser(t *testing.T) {
	alloc := "11111111-1111-1111-1111-111111111111"
	stale := "22222222-2222-2222-2222-222222222222"
	api := &fakeAPI{users: map[string][]User{
		"vless-ws": {
			{Email: "test-1@focusvpn", UUID: "manual"},
			{Email: stale, UUID: "old"},
		},
		"vless-xhttp": {
			{Email: "test-1@focusvpn", UUID: "manual"},
		},
	}}
	a := New(api, []Tag{{Name: "vless-ws", Port: 10000}, {Name: "vless-xhttp", Port: 10001}})
	applied, err := a.Apply(context.Background(), poller.StateResponse{Peers: []poller.PeerState{{
		AllocationID: alloc, VLESSUUID: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
	}}})
	if err != nil {
		t.Fatal(err)
	}
	if len(applied) != 1 || applied[0] != alloc {
		t.Fatalf("applied: %v", applied)
	}
	for _, tag := range []string{"vless-ws", "vless-xhttp"} {
		got := map[string]bool{}
		for _, u := range api.users[tag] {
			got[u.Email] = true
		}
		if !got[alloc] || !got["test-1@focusvpn"] || got[stale] {
			t.Fatalf("%s users: %+v", tag, api.users[tag])
		}
	}
}

func TestParseXrayAPIPayloads(t *testing.T) {
	users, err := parseUsers([]byte(`{"users":[{"email":"a@b","account":{"_TypedMessage_":"xray.proxy.vless.Account","id":"u-1"}}]}`))
	if err != nil || len(users) != 1 || users[0].UUID != "u-1" {
		t.Fatalf("%+v %v", users, err)
	}
	n, err := parseOnline([]byte(`{}`))
	if err != nil || n != 0 {
		t.Fatalf("empty online: %d %v", n, err)
	}
	n, err = parseOnline([]byte(`{"users":["a@b","a@b","c@d"]}`))
	if err != nil || n != 2 {
		t.Fatalf("online: %d %v", n, err)
	}
	down, up, err := parseTraffic([]byte(`{"stat":[
		{"name":"user>>>a@focusvpn>>>traffic>>>downlink","value":10},
		{"name":"user>>>a@focusvpn>>>traffic>>>uplink","value":3},
		{"name":"user>>>b@focusvpn>>>traffic>>>downlink","value":7}
	]}`))
	if err != nil || down != 17 || up != 3 {
		t.Fatalf("traffic down=%d up=%d err=%v", down, up, err)
	}
	ips, err := parseOnlineIPList([]byte(`{"name":"user>>>a>>>online","ips":{"203.0.113.8":1710000000,"203.0.113.9":1710000001}}`))
	if err != nil || len(ips) != 2 {
		t.Fatalf("ips: %v %v", ips, err)
	}
}

func TestResyncRestoresUsersLostByXray(t *testing.T) {
	api := &fakeAPI{users: map[string][]User{}}
	a := New(api, []Tag{{Name: "vless-ws", Port: 10000}})
	email := "6f1c3a4e-0d7b-4b8e-9a52-1f0c2d3e4b5a"
	state := poller.StateResponse{Version: 1, Peers: []poller.PeerState{{AllocationID: email, VLESSUUID: "11111111-2222-4333-8444-555555555555"}}}
	if _, err := a.Apply(context.Background(), state); err != nil {
		t.Fatal(err)
	}
	api.users["vless-ws"] = nil // Xray restarted with an empty user table

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan []string, 1)
	go a.Resync(ctx, 5*time.Millisecond, func(ids []string) {
		select {
		case done <- ids:
		default:
		}
	})
	select {
	case ids := <-done:
		if len(ids) != 1 || ids[0] != email {
			t.Fatalf("resync applied %v", ids)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("resync did not run")
	}
	cancel()
	a.mu.Lock()
	n := len(api.users["vless-ws"])
	a.mu.Unlock()
	if n != 1 {
		t.Fatalf("user not restored: %d", n)
	}
}
