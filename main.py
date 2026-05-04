import asyncio
import logging
import os
import re
import time
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.types import FSInputFile, KeyboardButton, Message, ReplyKeyboardMarkup

from downloader import DownloadError, download_video

URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
BTN_DOWNLOAD = "⬇️ Yuklash"
BTN_CANCEL = "🛑 Bekor qilish"

MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_DOWNLOAD), KeyboardButton(text=BTN_CANCEL)]],
    resize_keyboard=True,
    is_persistent=True,
)

GUIDE_TEXT = (
    "📎 Iltimos, video link yuboring.\n"
    "Qo‘llab-quvvatlanadigan platformalar: TikTok, Instagram, YouTube."
)
GENERIC_FAIL_TEXT = "❌ Video yuklab bo‘lmadi. Linkni tekshirib qayta urinib ko‘ring."

# In-memory runtime state (database yo'q)
active_tasks: dict[int, asyncio.Task] = {}
awaiting_link: set[int] = set()


async def _download_and_send(message: Message, url: str) -> None:
    chat_id = message.chat.id
    await message.answer("⏳ Yuklanmoqda...", reply_markup=MENU)
    await message.answer("🔍 Link tekshirildi. Yuklab olish boshlandi...", reply_markup=MENU)

    result = await download_video(url)
    try:
        file_size = os.path.getsize(result.file_path)
        media = FSInputFile(result.file_path)
        if file_size > 49 * 1024 * 1024:
            await message.answer("📦 Fayl katta, document sifatida yuborilyapti...", reply_markup=MENU)
            await message.answer_document(media, caption="✅ Yuklandi", reply_markup=MENU)
        else:
            await message.answer_video(media, caption="✅ Yuklandi", reply_markup=MENU)
    finally:
        if os.path.exists(result.file_path):
            os.remove(result.file_path)


async def process_message(message: Message) -> None:
    chat_id = message.chat.id
    text = (message.text or message.caption or "").strip()

    try:
        if text == BTN_CANCEL:
            task = active_tasks.get(chat_id)
            if task and not task.done():
                task.cancel()
                await message.answer("🛑 Jarayon bekor qilindi.", reply_markup=MENU)
            else:
                await message.answer("ℹ️ Hozir faol jarayon yo‘q.", reply_markup=MENU)
            awaiting_link.discard(chat_id)
            return

        if text == BTN_DOWNLOAD:
            awaiting_link.add(chat_id)
            await message.answer("🔗 Link yuboring (TikTok, Instagram, YouTube).", reply_markup=MENU)
            return

        match = URL_PATTERN.search(text)
        if not match:
            if chat_id in awaiting_link:
                await message.answer("❗ Link topilmadi. Iltimos, to‘liq URL yuboring.", reply_markup=MENU)
            else:
                await message.answer(GUIDE_TEXT, reply_markup=MENU)
            return

        awaiting_link.discard(chat_id)
        url = match.group(0)

        old_task = active_tasks.get(chat_id)
        if old_task and not old_task.done():
            old_task.cancel()
            with suppress(asyncio.CancelledError):
                await old_task

        task = asyncio.create_task(_download_and_send(message, url))
        active_tasks[chat_id] = task

        try:
            await task
        except asyncio.CancelledError:
            await message.answer("🛑 Yuklash bekor qilindi.", reply_markup=MENU)
        except DownloadError as exc:
            await message.answer(f"❌ {str(exc)}", reply_markup=MENU)
        except Exception:
            logging.exception("Message processing failed")
            await message.answer(GENERIC_FAIL_TEXT, reply_markup=MENU)
        finally:
            if active_tasks.get(chat_id) is task:
                active_tasks.pop(chat_id, None)

    except Exception:
        logging.exception("Outer handler error")
        await message.answer(GENERIC_FAIL_TEXT, reply_markup=MENU)


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
