# Исторический снимок FocusPay monorepo (ночь 11→12.08.2026)

> Этот файл фиксирует состояние рабочей копии на 11–12 августа 2026 года. Он **не является актуальной картой проекта, инструкцией по развёртыванию или источником текущих production-настроек**.
>
> Новый разработчик начинает с [`README.md`](README.md), [`docs/DEVELOPER_ONBOARDING.md`](docs/DEVELOPER_ONBOARDING.md) и [`AGENTS.md`](AGENTS.md). Перед любым operational-действием сверяйте текущий код, systemd unit-файлы и правила проекта.

Снято с `ssh focuspay` / Gitea `developer1/focus-project-main` @ `48b411e`.

Живой сайт: https://focuspay.org (новый `focussite`, light/dark).

## Что выкатили ночью

| Коммит / патч | Суть |
|---|---|
| `cfb80f3`…`78e33c1` | payroll по ролям, layout ops |
| `df68a23` `7001a20` `a262a23` | модерн profile / promo / broadcast |
| `2102e16` | скидки оператора из grants |
| `6342c8e` | role coverage + доставка notify бота |
| `48b411e` | калькулятор курса при создании заявки ops |
| **после git** | captcha на логине: крупнее/читаемее картинка (`math_captcha.py`, `CaptchaField`) |

## Структура

- `focussite/` — новый React-сайт + admin/ops panel (то, что на focuspay.org)
- `site/exchange-backend/` — API сайта
- `bot/tg_bot_btc/` — бот
- `focus-panel/` — старая Vue-панель (не прод)

Локальная копия дизайна также лежит в `~/Desktop/exchange/focussite/`  
(старый `~/Desktop/exchange/frontend` + `doliv_bridge` не трогали).

Прод: docker `focuspay-prod-*`, static `/var/www/focuspay.org`.
