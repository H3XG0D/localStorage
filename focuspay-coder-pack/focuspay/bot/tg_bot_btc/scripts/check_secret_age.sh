#!/usr/bin/env bash
# Проверка возраста секретов и алерт если давно не ротировали
# Использование: ./check_secret_age.sh [--alert]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="$(dirname "$SCRIPT_DIR")"
TIMESTAMP_FILE="$BOT_DIR/.secrets_rotated_at"
ENV_FILE="$BOT_DIR/.env"

ALERT_MODE=0
if [[ "${1:-}" == "--alert" ]]; then
    ALERT_MODE=1
fi

# Максимальный возраст секретов (90 дней в секундах)
MAX_AGE_SECONDS=$((90 * 24 * 60 * 60))
WARNING_AGE_SECONDS=$((75 * 24 * 60 * 60))  # Предупреждение за 15 дней

# Определить дату последней ротации
if [[ -f "$TIMESTAMP_FILE" ]]; then
    LAST_ROTATION=$(cat "$TIMESTAMP_FILE")
else
    # Если timestamp файла нет — использовать mtime .env
    if [[ -f "$ENV_FILE" ]]; then
        LAST_ROTATION=$(stat -c %Y "$ENV_FILE" 2>/dev/null || stat -f %m "$ENV_FILE" 2>/dev/null || echo 0)
        echo "⚠️  Timestamp файл не найден, используем mtime .env"
    else
        echo "❌ Ни timestamp, ни .env файл не найдены"
        exit 1
    fi
fi

NOW=$(date +%s)
AGE_SECONDS=$((NOW - LAST_ROTATION))
AGE_DAYS=$((AGE_SECONDS / 86400))

LAST_ROTATION_DATE=$(date -d "@$LAST_ROTATION" +"%Y-%m-%d %H:%M:%S" 2>/dev/null || date -r "$LAST_ROTATION" +"%Y-%m-%d %H:%M:%S" 2>/dev/null)

echo "🔐 Проверка возраста секретов FocusPay"
echo "📅 Последняя ротация: $LAST_ROTATION_DATE"
echo "⏰ Возраст: $AGE_DAYS дней"
echo ""

# Проверка статуса
if [[ $AGE_SECONDS -gt $MAX_AGE_SECONDS ]]; then
    STATUS="❌ CRITICAL"
    MESSAGE="Секреты не ротировались $AGE_DAYS дней (лимит 90)! Требуется срочная ротация."
    EXIT_CODE=2
elif [[ $AGE_SECONDS -gt $WARNING_AGE_SECONDS ]]; then
    STATUS="⚠️  WARNING"
    MESSAGE="Секреты не ротировались $AGE_DAYS дней. Рекомендуется ротация в ближайшие 15 дней."
    EXIT_CODE=1
else
    STATUS="✅ OK"
    MESSAGE="Секреты актуальны ($AGE_DAYS дней)."
    EXIT_CODE=0
fi

echo "$STATUS"
echo "$MESSAGE"

# Отправка алерта в Telegram если режим --alert и есть проблема
if [[ $ALERT_MODE -eq 1 && $EXIT_CODE -gt 0 ]]; then
    echo ""
    echo "📤 Отправка алерта в Telegram..."
    
    # Load only the two required values without evaluating shell from .env.
    read_env_value() {
        local name="$1" line
        line="$(grep -m1 -E "^[[:space:]]*${name}=" "$ENV_FILE" || true)"
        line="${line#*=}"
        if [[ "$line" == \"*\" && "$line" == *\" ]]; then
            line="${line:1:${#line}-2}"
        elif [[ "$line" == \'*\' && "$line" == *\' ]]; then
            line="${line:1:${#line}-2}"
        fi
        printf '%s' "$line"
    }
    TELEGRAM_BOT_TOKEN="$(read_env_value TELEGRAM_BOT_TOKEN)"
    SECURITY_TELEGRAM_CHAT_ID="$(read_env_value SECURITY_TELEGRAM_CHAT_ID)"

    if [[ -n "$TELEGRAM_BOT_TOKEN" && -n "$SECURITY_TELEGRAM_CHAT_ID" ]]; then
        ALERT_TEXT="🔐 <b>Secret Age Alert</b>

$STATUS $MESSAGE

Последняя ротация: $LAST_ROTATION_DATE
Возраст: $AGE_DAYS дней

Запустите в согласованное окно обслуживания: <code>cd /opt/tg_bot_btc &amp;&amp; ./scripts/rotate_secrets.sh --restart-services</code>"
        
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${SECURITY_TELEGRAM_CHAT_ID}" \
            -d "text=${ALERT_TEXT}" \
            -d "parse_mode=HTML" \
            > /dev/null
        
        echo "✅ Алерт отправлен в Telegram"
    else
        echo "⚠️  TELEGRAM_BOT_TOKEN или SECURITY_TELEGRAM_CHAT_ID не заданы в .env"
    fi
fi

exit $EXIT_CODE
