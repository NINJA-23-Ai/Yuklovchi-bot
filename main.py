import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
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
    inline_keyboard=[[InlineKeyboardButton(text="360p", callback_data="q:360"), InlineKeyboardButton(text="720p", callback_data="q:720"), InlineKeyboardButton(text="1080p", callback_data="q:1080")]]
)
THUMB_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Yo‘q", callback_data="thumb:no")]])

GUIDE_TEXT = "📎 Link yuboring yoki ⬇️ Yuklash tugmasini bosing."
GENERIC_FAIL_TEXT = "❌ Video yuklab bo‘lmadi. Linkni tekshirib qayta urinib ko‘ring."

active_tasks: dict[int, asyncio.Task] = {}
pending_links: dict[int, str] = {}
awaiting_thumbnail: dict[int, str] = {}
progress_messages: dict[int, list[int]] = {}


async def _delete_messages(bot: Bot, chat_id: int, ids: list[int]) -> None:
    for msg_id in ids:
        with suppress(Exception):
            await bot.delete_message(chat_id, msg_id)


def _overlay_image_on_video(video_path: str, image_path: str) -> str:
    out_path = os.path.join(tempfile.gettempdir(), f"video_thumb_{uuid.uuid4()}.mp4")
    cmd = [
        "ffmpeg", "-y", "-i", video_path, "-i", image_path,
        "-filter_complex", "[1:v]scale=iw*0.25:-1[wm];[0:v][wm]overlay=W-w-20:H-h-20",
        "-c:a", "copy", out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-500:])
    return out_path


async def _send_final_video(message: Message, video_path: str, thumb_path: str | None = None) -> None:
    file_size = os.path.getsize(video_path)
    media = FSInputFile(video_path)
    if file_size > 49 * 1024 * 1024:
        await message.answer_document(media, caption="✅ Yuklandi", reply_markup=MENU)
    else:
        thumbnail = FSInputFile(thumb_path) if thumb_path and os.path.exists(thumb_path) else None
        await message.answer_video(media, caption="✅ Yuklandi", reply_markup=MENU, thumbnail=thumbnail)


async def _download_only(message: Message, url: str, quality: str) -> str:
    bot = message.bot
    chat_id = message.chat.id
    p1 = await message.answer("⏳ Yuklanmoqda...", reply_markup=MENU)
    p2 = await message.answer(f"🎚 Sifat: {quality}p", reply_markup=MENU)
    progress_messages[chat_id] = [p1.message_id, p2.message_id]

    result = await download_video(url, quality)
    return result.file_path


async def process_message(message: Message) -> None:
    chat_id = message.chat.id
    text = (message.text or message.caption or "").strip()

    # thumbnail kutish holati
    if chat_id in awaiting_thumbnail and message.photo:
        try:
            await message.answer("🖼 Rasm qabul qilindi. Videoga qo‘shilmoqda...", reply_markup=MENU)
            video_path = awaiting_thumbnail.pop(chat_id)
            photo = message.photo[-1]
            img_file = await message.bot.get_file(photo.file_id)
            img_path = os.path.join(tempfile.gettempdir(), f"thumb_{uuid.uuid4()}.jpg")
            await message.bot.download_file(img_file.file_path, destination=img_path)
            ffmpeg_exists = shutil.which("ffmpeg") is not None
            if ffmpeg_exists:
                final_path = await asyncio.to_thread(_overlay_image_on_video, video_path, img_path)
                await _send_final_video(message, final_path)
            else:
                await message.answer("ℹ️ Serverda ffmpeg topilmadi. Rasm video thumbnail sifatida qo‘yildi.", reply_markup=MENU)
                final_path = video_path
                await _send_final_video(message, video_path, thumb_path=img_path)

            await _delete_messages(message.bot, chat_id, progress_messages.pop(chat_id, []))
            with suppress(Exception):
                os.remove(video_path)
            with suppress(Exception):
                os.remove(img_path)
            if final_path != video_path:
                with suppress(Exception):
                    os.remove(final_path)
            return
        except Exception as exc:
            logging.exception("Thumbnail apply failed: %s", exc)
            await message.answer("❌ Rasm qo‘shib bo‘lmadi, original video yuborildi.", reply_markup=MENU)
            video_path = awaiting_thumbnail.pop(chat_id, None)
            if video_path and os.path.exists(video_path):
                await _send_final_video(message, video_path)
                with suppress(Exception):
                    os.remove(video_path)
                await _delete_messages(message.bot, chat_id, progress_messages.pop(chat_id, []))
            return

    try:
        if text == BTN_CANCEL:
            task = active_tasks.get(chat_id)
            if task and not task.done():
                task.cancel()
            pending_links.pop(chat_id, None)
            v = awaiting_thumbnail.pop(chat_id, None)
            if v and os.path.exists(v):
                os.remove(v)
            await _delete_messages(message.bot, chat_id, progress_messages.pop(chat_id, []))
            await message.answer("🛑 Jarayon bekor qilindi.", reply_markup=MENU)
            return

        if text == BTN_DOWNLOAD:
            await message.answer("🔗 Link yuboring (TikTok, Instagram, YouTube).", reply_markup=MENU)
            return

        match = URL_PATTERN.search(text)
        if not match:
            await message.answer(GUIDE_TEXT, reply_markup=MENU)
            return

        pending_links[chat_id] = match.group(0)
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

    async def runner() -> None:
        video_path = await _download_only(callback.message, url, quality)
        awaiting_thumbnail[chat_id] = video_path
        await callback.message.answer("🖼 Video yuklandi. Rasm qo‘yamizmi? Rasm yuboring yoki 'Yo‘q' bosing.", reply_markup=THUMB_KB)

    task = asyncio.create_task(runner())
    active_tasks[chat_id] = task
    try:
        await task
    except DownloadError as exc:
        await callback.message.answer(f"❌ {str(exc)}", reply_markup=MENU)
    except asyncio.CancelledError:
        await callback.message.answer("🛑 Yuklash bekor qilindi.", reply_markup=MENU)
    except Exception:
        logging.exception("Download task failed")
        await callback.message.answer(GENERIC_FAIL_TEXT, reply_markup=MENU)
    finally:
        if active_tasks.get(chat_id) is task:
            active_tasks.pop(chat_id, None)


async def on_thumb_skip(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    chat_id = callback.message.chat.id
    video_path = awaiting_thumbnail.pop(chat_id, None)
    with suppress(Exception):
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Jarayon yakunlandi")
    if not video_path or not os.path.exists(video_path):
        await callback.message.answer("❌ Video topilmadi", reply_markup=MENU)
        return
    await _send_final_video(callback.message, video_path)
    await _delete_messages(callback.message.bot, chat_id, progress_messages.pop(chat_id, []))
    with suppress(Exception):
        os.remove(video_path)


async def run_bot() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is required")
    bot = Bot(token=token)
    dp = Dispatcher()
    dp.message.register(process_message)
    dp.callback_query.register(on_quality_selected, F.data.startswith("q:"))
    dp.callback_query.register(on_thumb_skip, F.data == "thumb:no")

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
