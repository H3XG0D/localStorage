---
type: plan
tags: [plan, infra, ops, launch]
status: active
updated: 2026-10-09
---

# Infra — two-host topology (biz + VPN traffic)

Канон после SSH-рекона 12.08.2026. Сводка обсуждения: biz-хост уже куплен и заселён FocusPay; покупается только FR traffic-нода.

## Топология (зафиксировано)

| Роль | Хост | Что крутится |
|---|---|---|
| **Biz** | `focuspay` → **153.80.249.77** (dhost, **16c / 31 GiB**, EPYC 7763) | FocusPay (bot, webhook, exchange-api, nginx, PG `exchange_bot`, Redis). Далее: FocusVPN CP + **свой** Postgres, VPN TG bot, landing. Чат Ops AI ходит на Олламу ниже |
| **VPN traffic** | dhost **PAR-SM5038ML-H12TRF-21-5** (France) — **заказать** | Только AmneziaWG + node-agent. Без FocusPay / кошельков / Ollama |
| **Оллама** | бывшая **DE1** `94.26.83.74` (Франкфурт, 4c / 16G), ssh `focusvpn-de1` | С 09.10.2026 не VPN. `qwen2.5:7b-instruct`, `:11434` только с focuspay. Заметки лежат на focuspay в `/opt/focus-brain` |
| **VPN traffic (тест E3)** | **DE2** `147.45.39.132` (Франкфурт, 1c / 2G / 30G), ssh `focusvpn-de2` | Та же схема, вторая локация «Германия» с 08.10.2026. Домен `147-45-39-132.sslip.io`, capacity 200. На `:8443` CP пускает и этот IP |
| **VPN traffic (тест E3)** | **NL1** `193.233.82.168` (Амстердам, 1c / 2G / 30G), ssh `focusvpn-nl1` | Та же схема, локация «Нидерланды» с 08.10.2026. Домен `193-233-82-168.sslip.io`, регион `eu-west`, capacity 200 |
| **VPN traffic (тест E3)** | **NL2** `199.91.221.37` (Амстердам, BitLaunch, 1c / 1G / 24G), ssh `focusvpn-nl2` | Вторая «Нидерланды» с 08.10.2026. Домен `199-91-221-37.sslip.io`, регион `eu-west`, capacity 100. На `:8443` CP пускает и этот IP |
| **VPN traffic (тест E3)** | **RO1** `64.7.199.95` (Бухарест, BitLaunch, 1c / 1G / 24G), ssh `focusvpn-ro1` | Первая Румыния с 08.10.2026. Домен `64-7-199-95.sslip.io`, регион `eu-east`, capacity 100. На `:8443` CP пускает и этот IP |
| **VPN traffic (тест E3)** | **GB1** `193.149.189.177` (Лондон, BitLaunch, 1c / 1G / 24G), ssh `focusvpn-gb1` | Первая Великобритания с 08.10.2026. Домен `193-149-189-177.sslip.io`, регион `eu-west`, capacity 100. На `:8443` CP пускает и этот IP |
| **Старый FP** | `216.73.157.10` | SSH **мёртв** (no route). Не использовать как ноду, пока не оживёт; при оживлении — wipe, не mixed с кошельками |

```
Users  --HTTPS-->  153.80.249.77  (FocusPay + FocusVPN CP / bots / site)
                        |
                   mTLS :8443
                        v
Users  --UDP VPN-->  FR dedic (awg + node-agent)   ← 300 Mbit unmetered
```

## Жёсткие правила

1. User VPN traffic **не** идёт через biz-хост.
2. FocusPay / ключи / `.env` обменника **не** ставятся на FR ноду.
3. Две Postgres: `exchange_bot` ≠ FocusVPN DB ([[007-ecosystem-billing-federation|ADR-007]]).
4. Ops AI на biz ходит на Олламу `94.26.83.74` (`qwen2.5:7b-instruct`). Ключи выплат на эту машину не класть.
5. Brain vault / Ollama (если появится) — без доступа к ключам выплат FocusPay.

## Ёмкость FR-ноды (ориентир)

Канал **300 Mbit unmetered** — bottleneck; 4c/32GB для AWG с запасом.

| Режим | Одновременно | Подписчики (пик ~15–25% online) |
|---|---|---|
| Лёгкий | ~100–200 | ~500–1000 |
| Нормальный микс | ~50–100 | ~250–500 |
| Тяжёлый | ~20–40 | ~100–200 |

Практично MVP: **~200–400** человек / **~50–100** в пике. Дальше — вторая нода + NodeSelector / DRAINING ([[ARCHITECTURE]] §9–§10).

## Нагрузка / failover (уже в продукте)

- NodeSelector: score ↓ при высоком `load`; top-3 кандидатов (P4-M4).
- `HEALTHY → DEGRADED → DRAINING → OFFLINE`; DRAINING = без новых аллокаций.
- Клиентский failover + reconnect (P4-M4b).
- С **одной** нодой rebalance на другую локацию невозможен — нужна вторая нода.

## Чеклист cutover / launch

### A. FR traffic node (человек + скрипты)

- [ ] Заказать PAR-SM5038 (France, 300 Mbit unmetered)
- [ ] Ubuntu 24.04, SSH key (`~/.ssh/id_ed25519`), hostname
- [ ] Firewall: UDP **51820** in; SSH; исходящий к CP **:8443**; без лишнего
- [ ] Установить awg tools (отдельный процесс, GPL не в product binary)
- [ ] После живого CP: `sudo bash scripts/provision-node.sh` + agent token
- [ ] Seed/register endpoint FR в CP; telemetry heartbeat OK

### B. Biz host `153.80.249.77` (FocusVPN рядом с FocusPay)

- [ ] Отдельный Postgres (или cluster DB) для FocusVPN — **не** `exchange_bot`
- [ ] `sudo bash scripts/provision-cp.sh` / compose; listener user API + agent **:8443**
- [ ] Firewall: :8443 только с IP FR-ноды (и admin); :443 уже nginx FocusPay
- [ ] DNS `api.<domain>` → 153.80.249.77 (или path на существующем домене)
- [ ] VPN bot `bots/focusvpn-tg` + landing `websites/landing/`
- [ ] `FOCUSVPN_API_BASE=https://api.<domain> make release-all`
- [ ] `make launch-check` + client connect → FR endpoint

### C. Не делать

- [ ] Не wipe / не «освобождать» biz под VPN traffic
- [ ] Не ждать `216.73.157.10` для первого launch
- [ ] Не класть Ollama/FocusPay на FR

## Связано

- [[plans/Launch-L1]] · [[CURRENT_TASK]] · [[DECISIONS]] · [[DEPLOYMENT]] · [[STATUS]] · [[FocusVPN Board]] · [[ARCHITECTURE]] §9–§10
