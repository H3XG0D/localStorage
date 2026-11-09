#!/usr/bin/env bash
# Wrapper для полного цикла бэкапа: pg_dump + offsite sync
# Вызывается из systemd timer

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🚀 FocusPay Full Backup Cycle"
echo "=============================="
echo ""

# 1. Выполнить локальный pg_dump
echo "📊 Шаг 1/2: Локальный pg_dump"
echo "------------------------------"
if ! "$SCRIPT_DIR/backup_db.sh"; then
    echo ""
    echo "❌ Локальный бэкап failed"
    exit 1
fi

echo ""
echo "📤 Шаг 2/2: Offsite sync"
echo "------------------------------"
# 2. Синхронизировать на offsite
if ! "$SCRIPT_DIR/backup_offsite_sync.sh"; then
    echo ""
    echo "⚠️  Offsite sync failed (локальный бэкап сохранён)"
    exit 1
fi

echo ""
echo "=============================="
echo "✅ Full backup cycle completed"
echo "📅 $(date -Iseconds)"
