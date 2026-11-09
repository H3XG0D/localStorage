# FocusVPN Launch-L1 — production templates (2 VPS sideload)

Do **not** commit real secrets. Copy examples → server `/etc/focusvpn/` or use `wizard-launch-l1.sh`.

## Layout

| File | Purpose |
|---|---|
| `env.cp.example` | Control plane environment |
| `env.node.example` | Node-agent environment |
| `Caddyfile.example` | TLS termination for public API |
| `focusvpn-backend.service` | systemd unit for CP |
| `focusvpn-agent.service` | systemd unit for node-agent |
| `docker-compose.cp.yml` | Optional: Postgres+Redis on CP host |

## Minimal topology

1. **CP VPS:** Caddy (:443) → backend (:8080); agent listener (:8443 mTLS); Postgres; Redis.
2. **VPN VPS:** node-agent + `awg`/`awg-quick`; UDP 51820 open to world; outbound to CP:8443.
