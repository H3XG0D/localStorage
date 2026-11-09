#!/bin/zsh
cd ~/focuspay_partner_bot
source .venv/bin/activate
pkill -f "cloudflared tunnel" 2>/dev/null
pkill -f "bot.py" 2>/dev/null; lsof -ti tcp:8080 | xargs kill -9 2>/dev/null
sleep 1
rm -f tunnel.log
./cloudflared tunnel --url http://localhost:8080 > tunnel.log 2>&1 &
TUN=$!
trap "kill $TUN 2>/dev/null" EXIT
echo "⏳ Запускаю туннель..."
URL=""
for i in {1..60}; do
  URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' tunnel.log | grep -v '://api\.' | head -1)
  [ -n "$URL" ] && break
  sleep 1
done
if [ -z "$URL" ]; then echo "❌ Туннель не дал ссылку. Пришли вывод: cat tunnel.log"; exit 1; fi
sed -i '' "s|^WEBAPP_URL=.*|WEBAPP_URL=$URL|" .env
echo "✅ Приложение: $URL"
echo "✅ Бот запускается. Напиши ему /start в Telegram. Остановить — Ctrl+C"
python3 bot.py
