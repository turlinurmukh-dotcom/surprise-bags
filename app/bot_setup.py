"""Shared bot/dispatcher construction, used by both main.py (local
polling) and web.py (deployed webhook mode) so routers are registered
in exactly one place.
"""

from __future__ import annotations

import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.handlers import consumer, fallback, merchant


def build_bot_and_dispatcher() -> tuple[Bot, Dispatcher]:
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    bot = Bot(token=bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(merchant.router)
    dp.include_router(consumer.router)
    dp.include_router(fallback.router)

    return bot, dp
