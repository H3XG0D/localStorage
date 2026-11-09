# Семафоры для ограничения одновременного выполнения тяжёлых операций.
# Число в Semaphore(N) — макс. сколько действий выполняется одновременно; остальные ждут в очереди.
import asyncio

SEM_START = asyncio.Semaphore(30)          # /start — макс. одновременных
SEM_CREATE_ORDER = asyncio.Semaphore(15)   # создание заявки (BUY/SELL)
SEM_ATTACH_CHECK = asyncio.Semaphore(10)   # прикрепление чека
