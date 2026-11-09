.PHONY: build test vet smoke smoke-e2e smoke-linux smoke-desktop smoke-windows smoke-xray smoke-e1-billing smoke-e1-full sandbox-up sandbox-down sandbox-reset sandbox-run sandbox-stop sandbox-smoke android-check apple-check windows-check android-native android-native-docker android-native-pack android-native-restore android-native-verify native-libs-check license-check launch-check release-linux release-windows release-android release-all run tidy clean dev-up dev-down dev-logs dev-reset migrate migrate-down migrate-version seed seed-agent-token build-agent db-test-create test-integration


# Dev PostgreSQL URL (matches infra/compose dev credentials).
DB_URL ?= postgres://focusvpn:focusvpn@localhost:5432/focusvpn?sslmode=disable
TEST_DB_URL ?= postgres://focusvpn:focusvpn@localhost:5432/focusvpn_test?sslmode=disable
PG_CONTAINER ?= focusvpn-dev-postgres-1
COMPOSE ?= podman compose -f infra/compose/docker-compose.yml

build:
	go build ./...

test:
	go test ./...

vet:
	go vet ./...

# Reproducible end-to-end vertical-slice check (Milestone 1, memory store).
smoke:
	bash scripts/smoke.sh

# M5 E2E: register → device → tunnel-up(dry-run conf with Jc/Jmin/Jmax) → disconnect.
# Optional real tunnel: FOCUSVPN_E2E_REAL_TUNNEL=1 (requires awg/awg-quick + CAP_NET_ADMIN).
smoke-e2e:
	bash scripts/smoke-e2e.sh

# P3-M1: product Linux CLI via AppCore (persistent session + dry-run conf).
smoke-linux:
	bash scripts/smoke-linux.sh

# P3-M2: desktop AppCore bindings (FocusPay-styled GUI companion; dry-run connect).
smoke-desktop:
	bash scripts/smoke-desktop.sh

# P3-M5: Windows AppCore bindings (FocusPay UI shell + wintun stub; dry-run connect).
smoke-windows:
	bash scripts/smoke-windows.sh

# P4-M3: Xray VLESS+REALITY JSON engine (dry-run; no xray binary required).
smoke-xray:
	bash scripts/smoke-xray.sh

# P3-M3c: Android scaffold tree check (assemble when ANDROID_HOME set).
android-check:
	bash scripts/android-check.sh

# P3 native: build libwg-go.so from amneziawg-android v2.0.2 into jniLibs (needs NDK).
android-native:
	bash scripts/build-android-native.sh

# P4-M10: same build inside podman/docker (smithmicro/android-build:34-ndk26) — no host SDK.
android-native-docker:
	bash scripts/build-android-native-docker.sh

# P4-M9: pack/restore/verify ABI tarball for CI cache (no NDK for restore/verify if .so present).
android-native-pack:
	bash scripts/android-native-abi.sh pack
android-native-restore:
	bash scripts/android-native-abi.sh restore
android-native-verify:
	bash scripts/android-native-abi.sh verify

# P3 native: pin/docs/CI check (no NDK/Xcode required).
native-libs-check:
	bash scripts/native-libs-check.sh

# Launch-L1: sideload path (scripts + templates + linux/windows build smoke).
launch-check:
	bash scripts/launch-check.sh

# Launch-L1 releases (require FOCUSVPN_API_BASE=https://api.example.com).
release-linux:
	bash scripts/release-linux.sh
release-windows:
	bash scripts/release-windows.sh
release-android:
	bash scripts/release-android.sh
release-all:
	bash scripts/release-all.sh

# P3-M4: Apple scaffold tree check (xcodebuild when Xcode present).
apple-check:
	bash scripts/apple-check.sh

# P3-M5: Windows scaffold (unit tests + smoke-windows).
windows-check:
	bash scripts/windows-check.sh

# License / pin gate (amneziawg-go v0.2.19; no forbidden GPL direct requires).
license-check:
	bash scripts/license-check.sh

# E1: internal Telegram upsert + billing extend (FocusPay federation).
smoke-e1-billing:
	bash scripts/smoke-e1-billing.sh

# E1 full: FocusPay wallet stub + FocusVPN billing + bot api (balance + crypto shortfall).
smoke-e1-full:
	bash scripts/smoke-e1-full.sh

# Isolated E1 sandbox (ports 15432/15433 — never production FocusPay).
sandbox-up:
	bash scripts/sandbox-up.sh
sandbox-down:
	bash scripts/sandbox-down.sh
sandbox-reset:
	bash scripts/sandbox-reset.sh
sandbox-run:
	bash scripts/sandbox-run.sh
sandbox-stop:
	bash scripts/sandbox-stop.sh
sandbox-smoke:
	bash scripts/sandbox-smoke.sh

# Run the control plane locally (memory store, ephemeral dev keys).
run:
	FOCUSVPN_STORE=memory go run ./backend/cmd/server

tidy:
	go mod tidy

clean:
	rm -rf bin

# --- Local dev stack (Podman) ---------------------------------------------
dev-up:
	$(COMPOSE) up -d

dev-down:
	$(COMPOSE) down

dev-logs:
	$(COMPOSE) logs -f

# Destroy and recreate the stack (drops all data volumes).
dev-reset:
	$(COMPOSE) down -v
	$(COMPOSE) up -d

# --- Database --------------------------------------------------------------
migrate:
	go run ./backend/cmd/migrate -url "$(DB_URL)" up

migrate-down:
	go run ./backend/cmd/migrate -url "$(DB_URL)" down

migrate-version:
	go run ./backend/cmd/migrate -url "$(DB_URL)" version

seed:
	go run ./backend/cmd/seed -url "$(DB_URL)"

# Generate and print a one-time node registration token for DE-01 (M4).
# Usage: make seed-agent-token DB_URL=postgres://...
# The printed AGENT_NODE_TOKEN must be set as AGENT_NODE_TOKEN in the agent env.
seed-agent-token:
	go run ./backend/cmd/seed -url "$(DB_URL)" -agent-token

# Build the node-agent binary.
build-agent:
	go build -o bin/node-agent ./node-agent/cmd/agent

# Create the disposable integration-test database (idempotent).
db-test-create:
	$(COMPOSE) exec -T postgres psql -U focusvpn -d focusvpn -tc "SELECT 1 FROM pg_database WHERE datname='focusvpn_test'" | grep -q 1 || \
	$(COMPOSE) exec -T postgres psql -U focusvpn -d focusvpn -c "CREATE DATABASE focusvpn_test"

# Run the full suite including the real-PostgreSQL integration tests.
# Requires the dev stack (make dev-up) and the test DB (make db-test-create).
test-integration:
	FOCUSVPN_TEST_DATABASE_URL="$(TEST_DB_URL)" go test ./...
