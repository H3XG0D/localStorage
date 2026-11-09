"""Minimal isolated telebot modules for game and startup tests."""
from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace


_MISSING = object()


class AsyncTeleBotStub:
    def __init__(self, *args, **kwargs):
        pass

    async def send_dice(self, *args, **kwargs):
        return SimpleNamespace(dice=SimpleNamespace(emoji="🎲", value=4), message_id=1)

    async def send_message(self, *args, **kwargs):
        return SimpleNamespace(message_id=1)

    async def send_chat_action(self, *args, **kwargs):
        return True

    async def reply_to(self, *args, **kwargs):
        return SimpleNamespace(message_id=1)

    async def send_photo(self, *args, **kwargs):
        return None

    async def edit_message_text(self, *args, **kwargs):
        return None

    async def edit_message_media(self, *args, **kwargs):
        return None

    async def edit_message_reply_markup(self, *args, **kwargs):
        return None

    async def delete_message(self, *args, **kwargs):
        return None

    async def answer_callback_query(self, *args, **kwargs):
        return None

    async def infinity_polling(self, *args, **kwargs):
        return None

    async def delete_my_commands(self, *args, **kwargs):
        return True

    async def set_my_commands(self, *args, **kwargs):
        return True

    async def get_me(self):
        return SimpleNamespace(id=1)

    async def get_chat_member(self, *args, **kwargs):
        return SimpleNamespace(status="administrator")

    def message_handler(self, *args, **kwargs):
        return lambda handler: handler

    def register_message_handler(self, *args, **kwargs):
        return None

    def callback_query_handler(self, *args, **kwargs):
        return lambda handler: handler


class KeyboardButtonStub:
    def __init__(self, text, **kwargs):
        self.text = text
        self.web_app = kwargs.get("web_app")


class ReplyKeyboardMarkupStub:
    def __init__(self, *args, **kwargs):
        self.keyboard: list[list[KeyboardButtonStub]] = []

    def row(self, *buttons):
        self.keyboard.append(list(buttons))
        return self

    def add(self, *buttons):
        self.keyboard.append(list(buttons))
        return self


class WebAppInfoStub:
    def __init__(self, url: str):
        self.url = url


class InlineKeyboardButtonStub:
    def __init__(self, text, callback_data=None, **kwargs):
        self.text = text
        self.callback_data = callback_data
        self.url = kwargs.get("url")
        self.web_app = kwargs.get("web_app")


class InlineKeyboardMarkupStub:
    def __init__(self, *args, **kwargs):
        self.keyboard: list[list[InlineKeyboardButtonStub]] = []

    def row(self, *buttons):
        self.keyboard.append(list(buttons))
        return self

    def add(self, *buttons):
        self.keyboard.append(list(buttons))
        return self


class TelebotModules:
    """Temporarily replace telebot and import selected modules against the stub."""

    def __init__(self, *module_names: str):
        self.module_names = module_names

    def __enter__(self):
        names = ("telebot", "telebot.async_telebot", *self.module_names)
        self.previous = {
            name: sys.modules.get(name, _MISSING)
            for name in names
        }
        telebot_module = ModuleType("telebot")
        telebot_module.types = SimpleNamespace(
            InlineKeyboardMarkup=InlineKeyboardMarkupStub,
            InlineKeyboardButton=InlineKeyboardButtonStub,
            InputMediaPhoto=lambda photo: photo,
            ReplyKeyboardMarkup=ReplyKeyboardMarkupStub,
            KeyboardButton=KeyboardButtonStub,
            WebAppInfo=WebAppInfoStub,
            BotCommand=type("BotCommand", (), {"__init__": lambda self, command, description: (setattr(self, "command", command), setattr(self, "description", description), None)[-1]}),
            BotCommandScopeAllPrivateChats=type("BotCommandScopeAllPrivateChats", (), {}),
            BotCommandScopeAllGroupChats=type("BotCommandScopeAllGroupChats", (), {}),
            BotCommandScopeAllChatAdministrators=type(
                "BotCommandScopeAllChatAdministrators", (), {}
            ),
        )
        async_telebot_module = ModuleType("telebot.async_telebot")
        async_telebot_module.AsyncTeleBot = AsyncTeleBotStub
        sys.modules["telebot"] = telebot_module
        sys.modules["telebot.async_telebot"] = async_telebot_module
        for name in self.module_names:
            sys.modules.pop(name, None)
        return self

    def __exit__(self, *args):
        for name, module in self.previous.items():
            # Keep the stub if this process never had real telebot. Handlers
            # lazy-import games.* after the `with` block, and pytest files share
            # one interpreter.
            if name in ("telebot", "telebot.async_telebot") and module is _MISSING:
                continue
            if module is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        return False
