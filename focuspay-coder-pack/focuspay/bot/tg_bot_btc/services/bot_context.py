"""Доступ к Application / Bot из сервисов (webhook, db)."""
_app = None
_bot = None


def set_application(app) -> None:
    global _app
    _app = app


def set_bot(bot) -> None:
    global _bot
    _bot = bot


def get_bot():
    if _bot is not None:
        return _bot
    if _app is None:
        return None
    return _app.bot
