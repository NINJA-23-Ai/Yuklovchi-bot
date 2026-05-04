import asyncio
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass
from typing import Optional

import yt_dlp
from yt_dlp.utils import DownloadError as YtDlpDownloadError


logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    file_path: str
    used_fallback: bool


class DownloadError(Exception):
    """Video yuklab olishdagi maxsus xatolik."""


def _build_opts(output_template: str, format_selector: str) -> dict:
    return {
        "format": format_selector,
        "outtmpl": output_template,
        "noplaylist": True,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "geo_bypass": True,
        "quiet": False,
        "no_warnings": False,
        "verbose": True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
        "merge_output_format": "mp4",
    }


def _find_downloaded_file(base_path: str) -> Optional[str]:
    candidates = [
        base_path,
        os.path.splitext(base_path)[0] + ".mp4",
        os.path.splitext(base_path)[0] + ".mkv",
        os.path.splitext(base_path)[0] + ".webm",
    ]
    return next((p for p in candidates if os.path.exists(p)), None)


def _download_once(url: str, output_template: str, format_selector: str) -> str:
    opts = _build_opts(output_template, format_selector)
    logger.info("Starting yt-dlp download with format: %s", format_selector)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            raise DownloadError("Video mavjud emas")
        base_path = ydl.prepare_filename(info)

    real_path = _find_downloaded_file(base_path)
    if not real_path:
        raise DownloadError("Format topilmadi yoki fayl yaratilmadi")

    persistent_path = os.path.join(tempfile.gettempdir(), f"video_{uuid.uuid4()}{os.path.splitext(real_path)[1]}")
    os.replace(real_path, persistent_path)
    return persistent_path


def _classify_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "requested format is not available" in msg:
        return "Format topilmadi"
    if "ffmpeg" in msg:
        return "FFmpeg topilmadi"
    if "unable to download" in msg or "http error" in msg or "forbidden" in msg:
        return "Platforma blokladi"
    if "not available" in msg or "private" in msg:
        return "Video mavjud emas"
    return "Video yuklab bo‘lmadi"


def _download_sync(url: str) -> DownloadResult:
    with tempfile.TemporaryDirectory() as temp_dir:
        output_template = os.path.join(temp_dir, f"{uuid.uuid4()}.%(ext)s")

        primary_format = "bestvideo+bestaudio/best"
        fallback_format = "best"

        try:
            file_path = _download_once(url, output_template, primary_format)
            return DownloadResult(file_path=file_path, used_fallback=False)
        except (YtDlpDownloadError, DownloadError, Exception) as first_exc:
            logger.exception("Primary format failed: %s", first_exc)
            print(f"[yt-dlp][primary-error] {first_exc}")

            try:
                file_path = _download_once(url, output_template, fallback_format)
                return DownloadResult(file_path=file_path, used_fallback=True)
            except Exception as second_exc:
                logger.exception("Fallback format failed: %s", second_exc)
                print(f"[yt-dlp][fallback-error] {second_exc}")
                reason = _classify_error(second_exc)
                raise DownloadError(reason) from second_exc


async def download_video(url: str) -> DownloadResult:
    try:
        result = await asyncio.to_thread(_download_sync, url)
        if not result or not result.file_path:
            raise DownloadError("Fayl yaratilmadi")
        if not os.path.exists(result.file_path):
            raise DownloadError("Fayl topilmadi")
        return result
    except DownloadError:
        raise
    except Exception as exc:
        logger.exception("Unexpected downloader error: %s", exc)
        raise DownloadError(_classify_error(exc)) from exc
