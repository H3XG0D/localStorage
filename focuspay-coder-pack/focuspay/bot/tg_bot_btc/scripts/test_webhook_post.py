"""
Ручной тест вебхука (новый мерчант — POST с JSON).

Подставь:
  - BASE_URL — твой ngrok или localhost (например https://61b7aa666db6.ngrok-free.app)
  - ORDER_ID — реальный order_id заявки из БД (наш, не uuid мерча)
  - при необходимости поменяй status / status_check в body.

Запуск: python scripts/test_webhook_post.py
"""
import requests
import json

BASE_URL = "https://a3df-185-72-187-51.ngrok-free.app"  # без слэша в конце
ORDER_ID = "19224200"   # замени на свой order_id из заявки в боте

# Успешное подтверждение оплаты (как от мерча после проверки чека)
body_completed = {
    "status_pending": "ok",
    "status": "PAID",
    "status_check": 1,
    "data_order": {
        "client_transaction_id": ORDER_ID,
        "amount": 4300,
    },
}

# НЕ завершает заявку: только смена статуса (status_pending=ok, без status_check=1)
body_status_changed_only = {
    "status_pending": "ok",
    "status": "ACCEPTED",
    "data_order": {
        "client_transaction_id": ORDER_ID,
        "amount": 4300,
    },
}

# Вариант: запрос чека (status_check 2 = нужен PDF или видео)
body_need_check = {
    "status": "ACCEPTED",
    "status_check": 3,
    "data_order": {
        "client_transaction_id": ORDER_ID,
        "amount": 4300,
    },
}

# Вариант: отмена
body_canceled = {
    "status": "CANCELED",
    "data_order": {"client_transaction_id": ORDER_ID},
}

if __name__ == "__main__":
    url = f"{BASE_URL}/callback"
    body = body_need_check  # или body_need_check / body_canceled

    print(f"POST {url}")
    print(f"Body: {json.dumps(body, ensure_ascii=False, indent=2)}")
    print()

    r = requests.post(url, json=body, timeout=10)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
