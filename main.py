import asyncio
import logging
import os
import re
import time
from contextlib import suppress

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from downloader import DownloadError, download_video

URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
BTN_DOWNLOAD = "⬇️ Yuklash"
BTN_CANCEL = "🛑 Bekor qilish"

MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_DOWNLOAD), KeyboardButton(text=BTN_CANCEL)]],
    resize_keyboard=True,
    is_persistent=True,
)

QUALITY_KB = InlineKeyboardMarkup(
    inline_keyboard=[[
        InlineKeyboardButton(text="360p", callback_data="q:360"),
        InlineKeyboardButton(text="720p", callback_data="q:720"),
        InlineKeyboardButton(text="1080p", callback_data="q:1080"),
    ]]
)

GUIDE_TEXT = "📎 Link yuboring yoki ⬇️ Yuklash tugmasini bosing."
GENERIC_FAIL_TEXT = "❌ Video yuklab bo‘lmadi. Linkni tekshirib qayta urinib ko‘ring."

active_tasks: dict[int, asyncio.Task] = {}
awaiting_link: set[int] = set()
pending_links: dict[int, str] = {}


async def _cleanup_msgs(msgs: list[Message]) -> None:
    for msg in msgs:
        with suppress(Exception):
            await msg.delete()


async def _download_and_send(message: Message, url: str, quality: str) -> None:
    progress_msgs: list[Message] = []
    progress_msgs.append(await message.answer("⏳ Yuklanmoqda...", reply_markup=MENU))
    progress_msgs.append(await message.answer(f"🎚 Sifat: {quality}p", reply_markup=MENU))

    result = await download_video(url, quality)
    try:
        file_size = os.path.getsize(result.file_path)
        media = FSInputFile(result.file_path)
        if file_size > 49 * 1024 * 1024:
            await message.answer_document(media, caption="✅ Yuklandi", reply_markup=MENU)
        else:
            await message.answer_video(media, caption="✅ Yuklandi", reply_markup=MENU)
        await _cleanup_msgs(progress_msgs)
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
            pending_links.pop(chat_id, None)
            return

        if text == BTN_DOWNLOAD:
            awaiting_link.add(chat_id)
            await message.answer("🔗 Link yuboring (TikTok, Instagram, YouTube).", reply_markup=MENU)
            return

        match = URL_PATTERN.search(text)
        if not match:
            await message.answer(GUIDE_TEXT, reply_markup=MENU)
            return

        pending_links[chat_id] = match.group(0)
        awaiting_link.discard(chat_id)
        await message.answer("🎛 Sifatni tanlang:", reply_markup=MENU)
        await message.answer("Quyidan formatni bosing.", reply_markup=QUALITY_KB)

    except Exception:
        logging.exception("Message handler error")
        await message.answer(GENERIC_FAIL_TEXT, reply_markup=MENU)


async def on_quality_selected(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    chat_id = callback.message.chat.id
    quality = callback.data.split(":", 1)[1]

    url = pending_links.pop(chat_id, None)
    if not url:
        await callback.answer("Avval link yuboring", show_alert=True)
        return

    with suppress(Exception):
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer(f"{quality}p tanlandi")

    old_task = active_tasks.get(chat_id)
    if old_task and not old_task.done():
        old_task.cancel()
        with suppress(asyncio.CancelledError):
            await old_task

    task = asyncio.create_task(_download_and_send(callback.message, url, quality))
    active_tasks[chat_id] = task
    try:
        await task
    except asyncio.CancelledError:
        await callback.message.answer("🛑 Yuklash bekor qilindi.", reply_markup=MENU)
    except DownloadError as exc:
        await callback.message.answer(f"❌ {str(exc)}", reply_markup=MENU)
    except Exception:
        logging.exception("Download task failed")
        await callback.message.answer(GENERIC_FAIL_TEXT, reply_markup=MENU)
    finally:
        if active_tasks.get(chat_id) is task:
            active_tasks.pop(chat_id, None)


async def run_bot() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is required")
    bot = Bot(token=token)
    dp = Dispatcher()
    dp.message.register(process_message)
    dp.callback_query.register(on_quality_selected, F.data.startswith("q:"))

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
