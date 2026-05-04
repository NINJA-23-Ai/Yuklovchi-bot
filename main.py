import asyncio
import logging
import os
import re
import time

from aiogram import Bot, Dispatcher
from aiogram.types import FSInputFile, Message

from downloader import DownloadError, download_video

URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
GUIDE_TEXT = (
    "📎 Iltimos, video link yuboring.\n"
    "Qo‘llab-quvvatlanadigan platformalar: TikTok, Instagram, YouTube."
)
GENERIC_FAIL_TEXT = "❌ Video yuklab bo‘lmadi. Linkni tekshirib qayta urinib ko‘ring."


async def process_message(message: Message) -> None:
    try:
        text = message.text or message.caption or ""
        match = URL_PATTERN.search(text)

        if not match:
            await message.answer(GUIDE_TEXT)
            return

        url = match.group(0)
        await message.answer("⏳ Yuklanmoqda...")

        result = await download_video(url)
        try:
            file_size = os.path.getsize(result.file_path)
            media = FSInputFile(result.file_path)

            if file_size > 49 * 1024 * 1024:
                await message.answer_document(media, caption="📦 Video document sifatida yuborildi")
            else:
                await message.answer_video(media)
        finally:
            if os.path.exists(result.file_path):
                os.remove(result.file_path)

    except DownloadError as exc:
        await message.answer(f"❌ {str(exc)}. Linkni tekshirib qayta urinib ko‘ring.")
    except Exception:
        logging.exception("Message processing failed")
        try:
            await message.answer(GENERIC_FAIL_TEXT)
        except Exception:
            logging.exception("Failed to send failure message")


async def run_bot() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is required")

    bot = Bot(token=token)
    dp = Dispatcher()
    dp.message.register(process_message)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    while True:
        try:
            asyncio.run(run_bot())
            break
        except KeyboardInterrupt:
            logging.info("Bot stopped by user")
            break
        except Exception:
            logging.exception("Bot crashed, restarting in 3 seconds")
            time.sleep(3)
