# Ручная приёмка: PNG-карточка профиля FocusCasino

Дата: 2026-08-27  
Scope: Telegram-бот казино, команда `/profile`, кнопка `👤 Профиль`, callback `profile:refresh`

---

## Реализовано

### Backend (internal API)

1. **`GET /api/internal/casino/users/{telegram_id}/profile`**
   - Добавлено поле `identity: {first_name, username}`
   - Источник: таблица `bot_users`
   - Test: `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`

2. **`GET /api/internal/casino/users/{telegram_id}/avatar`** (новый endpoint)
   - Отдаёт кешированный Telegram-аватар через `X-Internal-Token`
   - Fallback на `fetch_and_cache_bot_user_avatar` при cache miss
   - 404 если аватар недоступен
   - Форматы: `.jpg`, `.jpeg`, `.png`, `.webp`
   - `Cache-Control: private, max-age=86400`
   - Test: `ProfileAvatarEndpointTests` (3 теста)

### Casino bot

1. **`casino_profile_card.py`** (новый файл)
   - Renderer из присланного макета `casinoprofiledesgn.zip`
   - HTML/CSS + headless Chromium → PNG 2000×1280
   - Поля: имя, username, баланс, недельный оборот, проигрыш, отыгрыш, tier, кешбэк, прогресс, обратный отсчёт
   - Круглая аватарка или fallback с первой буквой имени
   - Экранирование HTML
   - Переменные окружения: `CHROMIUM_PATH`, `CHROME_PATH`
   - Test: `CasinoProfileCardTests` (2 теста)

2. **`assets/logo_f.svg`** (новый файл)
   - Логотип из присланного архива

3. **`bot.py`**
   - `_profile_card_player()` — маппинг internal API → поля карточки
   - `_render_profile_card()` — загружает аватар через `client.get_profile_avatar()`, рендерит PNG, fallback при ошибке
   - `_send_profile_card()` — отправляет `send_photo` с PNG
   - `/profile` → `_send_profile_card()`
   - `menu:profile` → `_send_profile_card()`
   - `profile:refresh` → `edit_message_media(InputMediaPhoto)`
   - Test: `ProfileHandlersTests` (4 теста)

4. **`focuspay_client.py`**
   - `get_profile_avatar()` — GET `/api/internal/casino/users/{telegram_id}/avatar` с `X-Internal-Token`
   - 404 → `None`
   - Валидация: `Content-Type: image/*`, размер 64 байт – 5 МБ
   - Test: `test_profile_avatar_contract_and_not_found_fallback`

5. **`tests/telebot_stub.py`**
   - Добавлен `InputMediaPhoto` stub
   - Добавлен `edit_message_media` stub

### Docker runtime

**`focussite/docker/casino-bot-runtime.Dockerfile`**
   - Добавлена установка `chromium`
   - `ENV CHROMIUM_PATH=/usr/bin/chromium`
   - Изменение не собрано и не развёрнуто

---

## Тесты (локально пройдены)

✅ **Casino bot** (7 тестов)
- `tests/test_casino_profile_card.py` — renderer, HTML escape, avatar fallback
- `tests/test_focuspay_client.py::test_profile_avatar_contract_and_not_found_fallback` — HTTP-клиент avatar endpoint
- `tests/test_profile.py` — handlers `/profile`, `menu:profile`, `profile:refresh`, avatar error fallback, группа reject

✅ **Backend** (4 теста)
- `tests/test_internal_casino.py::ProfileEndpointTests` — profile identity field
- `tests/test_internal_casino.py::ProfileAvatarEndpointTests` — avatar cache hit/miss/404, token check

✅ **Staging UI compatibility**
- `tests/test_staging_ui.py` — menu:profile, группа reject

---

## Ручные проверки

### Обязательные (до выкладки)

#### 1. Профиль с Telegram-аватаром

- [ ] Открыть личный чат с casino-ботом
- [ ] Отправить `/profile`
- [ ] Убедиться, что пришла PNG-карточка (не текст)
- [ ] Проверить, что аватарка круглая и соответствует фото пользователя в Telegram
- [ ] Проверить поля:
  - [ ] Имя совпадает с Telegram first_name
  - [ ] Username показан с `@` (если есть) или скрыт (если нет)
  - [ ] Доступный баланс корректный
  - [ ] Недельный оборот ставок
  - [ ] Учтённый проигрыш
  - [ ] Нужно поставить
  - [ ] Уровень кешбэка и процент
  - [ ] Ожидаемый кешбэк
  - [ ] Прогресс-бар до следующего уровня
  - [ ] Обратный отсчёт до понедельника 06:00 МСК (формат: "X д · YY ч · ZZ мин")

#### 2. Профиль без Telegram-аватарки

- [ ] Открыть профиль пользователем, у которого нет фото в Telegram
- [ ] Убедиться, что показан круглый placeholder с первой буквой имени
- [ ] Все остальные поля заполнены

#### 3. Обновление профиля

- [ ] Нажать кнопку `🔄 Обновить` под карточкой профиля
- [ ] Убедиться, что сообщение обновилось (не создано новое)
- [ ] Проверить, что данные актуальные
- [ ] Проверить, что аватар не исчез после обновления

#### 4. Ограничения доступа

- [ ] Открыть профиль в групповом чате
- [ ] Убедиться, что бот ответил "Профиль доступен только в личке с ботом"
- [ ] Убедиться, что карточка НЕ отправлена в группу

#### 5. Staging menu

- [ ] Если `CASINO_STAGING_UI_V2=true`, нажать кнопку `👤 Профиль` из staging-меню
- [ ] Убедиться, что карточка отправлена

#### 6. Безопасность (критично!)

- [ ] Открыть network logs Telegram (desktop или web)
- [ ] Открыть профиль с аватаркой
- [ ] Убедиться, что в URL фото **НЕТ** параметра `?access=`
- [ ] Проверить логи бота — убедиться, что подписанный URL не попал в логи
- [ ] Проверить callback_data кнопки "Обновить" — не должно быть signed URL

#### 7. Fallback при ошибке загрузки аватара

- [ ] Временно сломать доступ к internal avatar endpoint (например, остановить backend)
- [ ] Открыть профиль
- [ ] Убедиться, что карточка всё равно показалась с fallback-аватаром (круг с буквой)
- [ ] Проверить, что остальные данные на месте

#### 8. HTML-инъекция

- [ ] Создать тестового пользователя с именем `<script>alert('xss')</script>` или `<Анна>`
- [ ] Открыть профиль этого пользователя
- [ ] Убедиться, что имя экранировано: `&lt;Анна&gt;` или `&lt;script&gt;...`

#### 9. Chromium runtime (на staging)

- [ ] Выложить изменения на staging
- [ ] Пересобрать casino-bot runtime с Chromium (новый Dockerfile)
- [ ] Запустить контейнер
- [ ] Проверить, что `/profile` работает без ошибки "Не найден Chrome/Chromium"
- [ ] Проверить логи контейнера — не должно быть Chrome warnings

---

## Изменённые/новые файлы

### Casino bot (`/home/qwe/Desktop/focuspay-casino`)

**Новые:**
- `casino_profile_card.py`
- `assets/logo_f.svg`
- `tests/test_casino_profile_card.py`
- `tests/test_profile.py`

**Изменённые:**
- `bot.py` (+150 строк: render, handlers)
- `focuspay_client.py` (+20 строк: avatar endpoint)
- `tests/telebot_stub.py` (+2 строки: stubs)
- `tests/test_focuspay_client.py` (+15 строк: avatar test)

### Backend (`/home/qwe/Desktop/focuspay/site/exchange-backend`)

**Изменённые:**
- `routers/internal_casino.py` (+30 строк: identity field, avatar endpoint)
- `tests/test_internal_casino.py` (+55 строк: identity assertion, avatar tests)

### Docker

**Изменённые:**
- `focussite/docker/casino-bot-runtime.Dockerfile` (+1 строка: chromium install)

---

## Не затронуто

- Платежи (депозиты, выплаты)
- Игровая логика (PVP, Cub, карточные игры)
- Production backend и бот
- Публичный avatar URL (не изменён, не используется в casino bot)
- Staging config (без изменений runtime secrets)

---

## Риски

1. **Runtime без Chromium** — если Dockerfile не пересобран, `/profile` упадёт с ошибкой "Не найден Chrome/Chromium". Фикс: пересборка образа.
2. **Отсутствие аватара** — при недоступности Telegram API показывается fallback, но профиль всегда работает.
3. **Большие PNG** — карточка 2000×1280 весит ~200–400 КБ. Telegram справляется, но при массовом открытии профиля будет трафик.

---

## Что делать перед выкладкой

1. Убедиться, что локальные тесты прошли (выше ✅)
2. Пройти все пункты ручной приёмки
3. Пересобрать casino-bot runtime с Chromium
4. Развернуть изменения на staging
5. Повторить ручную приёмку на staging
6. Только после подтверждения — выложить на production

---

## Команды для деплоя (НЕ ВЫПОЛНЯТЬ без разрешения)

### Backend (production)

```bash
cd /home/qwe/Desktop/focuspay/site/exchange-backend
# (изменения уже на сервере, нужен только restart uvicorn, если меняли код)
```

### Casino bot (staging)

```bash
cd /home/qwe/Desktop/focuspay
# 1. Собрать новый runtime с Chromium
docker build -f focussite/docker/casino-bot-runtime.Dockerfile -t focuspay-casino-runtime:profile .

# 2. Развернуть на staging через docker-compose
ssh focuspay-test "cd /opt/staging-releases/casino && docker-compose down casino-bot && docker-compose up -d casino-bot"
```

---

**Статус:** Реализация завершена, тесты прошли локально. Ожидается ручная приёмка перед выкладкой.
