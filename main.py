"""Local development entrypoint — always runs polling mode, regardless
of USE_WEBHOOK, since polling needs no public URL. For deployment, the
bot runs inside web.py instead (see USE_WEBHOOK there).
"""

import asyncio
import logging

from dotenv import load_dotenv

from app.bot_setup import build_bot_and_dispatcher

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    bot, dp = build_bot_and_dispatcher()
    logger.info("Starting polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
