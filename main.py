import asyncio
import logging
import os
import re

from aiogram import Bot, Dispatcher
from aiogram.types import FSInputFile, Message

from downloader import download_video

URL_PATTERN = re.compile(r"https?://\\S+", re.IGNORECASE)
GUIDE_TEXT = (
    "📎 Iltimos, video link yuboring.\n"
    "Qo‘llab-quvvatlanadigan platformalar: TikTok, Instagram, YouTube."
)
DOWNLOAD_FAIL_TEXT = "❌ Video yuklab bo‘lmadi. Linkni tekshirib qayta urinib ko‘ring."


async def process_message(message: Message) -> None:
    """Universal handler: har qanday xabarga javob beradi."""
    try:
        text = message.text or message.caption or ""
        match = URL_PATTERN.search(text)

        if not match:
            await message.answer(GUIDE_TEXT)
            return

        url = match.group(0)
        await message.answer("⏳ Yuklanmoqda...")

        file_path = await download_video(url)
        try:
            await message.answer_video(FSInputFile(file_path))
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

    except Exception:
        logging.exception("Message processing failed")
        try:
            await message.answer(DOWNLOAD_FAIL_TEXT)
        except Exception:
            logging.exception("Failed to send failure message")


async def run_bot() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is required")

    bot = Bot(token=token)
    dp = Dispatcher()
    dp.message.register(process_message)

    # Restart/redeployga chidamli startup:
    # 1) webhook o'chirish, 2) pending update tozalash, 3) pollingni ishga tushirish.
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    while True:
        try:
            asyncio.run(run_bot())
            break
        except KeyboardInterrupt:
            logging.info("Bot stopped by user")
            break
        except Exception:
            logging.exception("Bot crashed, restarting in 3 seconds")
            import time

            time.sleep(3)
