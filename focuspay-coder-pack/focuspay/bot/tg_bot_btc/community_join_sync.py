"""Обработка висящих заявок на вступление (Bot API не отдаёт список — только approve по user_id).

DEPRECATED: этот файл — shim для обратной совместимости.
Используйте `from services.community_join_sync import ...`
"""
from services.community_join_sync import *  # noqa: F401, F403
