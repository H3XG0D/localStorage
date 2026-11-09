# FocusVPN

Закрытый коммерческий VPN-сервис: собственный control plane, собственная VPN-инфраструктура,
клиенты для Android, iOS, macOS, Windows, Linux на пермиссивных open-source движках
(AmneziaWG, WireGuard, Xray/VLESS+REALITY).

Рабочий каталог может называться `focusvpn`; продукт — **FocusVPN**.

## Документация

- [CLAUDE.md](CLAUDE.md) — краткий контекст для агентов
- [docs/OPEN_SOURCE.md](docs/OPEN_SOURCE.md) — верифицированное исследование open-source компонентов и лицензий
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — общая архитектура (control plane, data plane, flows)
- [docs/API.md](docs/API.md) — спецификация REST API
- [docs/DATABASE.md](docs/DATABASE.md) — модель PostgreSQL
- [docs/SECURITY.md](docs/SECURITY.md) — модель безопасности и threat model
- [docs/CLIENT_ARCHITECTURE.md](docs/CLIENT_ARCHITECTURE.md) — архитектура клиентов и абстракция VPNEngine
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — локальный dev-окружение и деплой VPN-нод
- [docs/ROADMAP.md](docs/ROADMAP.md) — MVP vertical slice и фазы
- [docs/adr/](docs/adr/) — архитектурные решения (ADR)
- [docs/research/](docs/research/) — краткие заметки по внешним источникам

## Статус

**PHASE 1 (архитектура) — завершена**, включая context-audit правки документации.

**PHASE 2 (код) не начата** — ждёт явного утверждения. Vertical slice Phase 2 доказывается
через CLI harness, не через UI клиентов (см. ROADMAP).
