# С чего начать

Снимок рабочих копий на **8 ноября 2026**. Это диск, а не релизный тег: в `focuspay` лежит незакоммиченная работа. История git есть у `focuspay`, `focuspay-casino`, `doliv-lab` и `focusvpn`. У `doliv`, `qr-pay` и `focuspay-battle-lab` репозитория нет.

Архив не даёт доступа к серверам. Приватных ключей, `.env` и дампов базы здесь нет. Свой `.env` собирается из соседнего `*.example`. Плейсхолдеры вроде `PASSWORD`, `CHANGE_ME`, `777` — не боевые пароли.

`npm run dev` во фронте FocusPay по умолчанию ходит в боевой API. Живые заявки, выплаты и балансы отсюда не трогать. Деплой и рестарт сервисов — только после явного разрешения владельца.

Папки `exchange/`, мёртвая копия бота, parser, stavki, чеки и личные заметки сюда не входили. Живой код обменника — только `focuspay/`.

## Порядок чтения

1. Этот файл.
2. `focuspay/AGENTS.md` — правила, стек, что нельзя делать.
3. `focuspay/docs/DEVELOPER_ONBOARDING.md` — карта кода и потоков.
4. `focuspay/docs/FROZEN.md` — зоны, которые нельзя менять с ходу.
5. `focuspay/docs/PERMISSION_MATRIX.md` — если задача про `/x8`, `/ops`, финансы или права.
6. Дальше — одна папка из таблицы, с указанного файла.

Цепочка, когда уже понятно, какую поверхность трогать: экран или хендлер → сервис → роутер API → запрос к базе. Поля ответа смотреть в роутере, не угадывать.

## Как продукты связаны

```text
Браузер (сайт и панели) ──► FastAPI ──► PostgreSQL
Telegram-бот обменника ──► та же база и внутренний API
Казино-бот ──► API FocusPay, общий баланс
Doliv ──► реквизиты P2P для новых клиентов
Бот обменника ──► ссылка и оплата FocusVPN
```

`qr-pay` — вынутый из бота модуль QR СБП. Сам не запускается: его кладут обратно в кошелёк/бот. `focuspay-battle-lab` — отдельный прототип, к продовой базе не подключается.

## Папки

| Папка | Что это | С чего читать | Статус |
|---|---|---|---|
| `focuspay/` | Обменник: сайт, панели, API, боты | `AGENTS.md`, затем `README.md` | Прод. Это канон |
| `focuspay/focussite/frontend/` | React: публичный сайт, `/x8`, `/ops` | `src/App.tsx`, `src/panel/PanelApp.tsx` | Активный фронт |
| `focuspay/site/exchange-backend/` | FastAPI, права, миграции | `main.py`, потом нужный `routers/*.py` | Контракт API. Менять только с согласия |
| `focuspay/bot/tg_bot_btc/` | Telegram-бот обменника и webhook | `main.py`, затем `handlers/` | Прод |
| `focuspay/bot/focuspay-partner/` | Партнёрский бот | `README.md`, `bot.py` | Рядом с обменником |
| `focuspay/bot/focus-agent/` | Внутренний агент отчётов | `focus_agent/__main__.py` | Отдельный процесс |
| `focuspay/docs/` | Ограничения, права, интеграции | Onboarding выше | Читать до правок |
| `focuspay/focus-panel/` | Старый Vue-макет панели | не как исходник поведения | Только визуальный референс |
| `focuspay-casino/` | Telegram-бот казино | `README.md`, `bot.py` | Код есть. Выкат в прод по README заблокирован, пока нет отдельного разрешения |
| `doliv/` | P2P-панель: трейдеры, депозиты, реквизиты | `README.md`, `AGENTS.md`, `backend/app/main.py` | Прод-дерево |
| `doliv-lab/` | Песочница Doliv | `README.md`, `docs/SANDBOX.md` | Не подменяет `doliv/` |
| `focusvpn/` | VPN: control plane, бот, клиенты | `README.md`, `AGENTS.md`, `docs/ARCHITECTURE.md` | Исходники без сборок |
| `qr-pay/` | Модуль QR СБП | `README.md` | Не самостоятельный сервис |
| `focuspay-battle-lab/` | Прототип баттла | `README.md` | Лаборатория, не прод |

Локальный запуск каждой папки написан в её `README.md`. Зависимости (`npm install`, venv) в архив не входили: их ставят на месте.

## Чего в архиве нет

- Файлы `.env` и прочие runtime-секреты. Оставлены только `*.example`.
- Дамп продовой базы, каталог `backups/`, локальный Postgres.
- `node_modules`, `venv`, `dist`, `build`, кэши Gradle, бинарники `focusvpn/bin` и `ngrok.exe`.
- Ключи, keystore, `secrets/`, `.ssh_run.py`.
- Старое дерево `exchange/` — это дубль бэкенда плюс локальная база. Править его не нужно.
- Parser, stavki, банковские чеки, подписки VPN, личная база заметок.

Нативные библиотеки Android (`focusvpn/clients/android/.../jniLibs`) оставлены, чтобы клиент читался целиком. Каталог `app/build` вырезан.
