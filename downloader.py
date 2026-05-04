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
    pass


def _quality_format(quality: str) -> str:
    quality_map = {
        "360": "bestvideo[height<=360]+bestaudio/best[height<=360]/best",
        "720": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    }
    return quality_map.get(quality, "bestvideo+bestaudio/best")


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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        },
        "merge_output_format": "mp4",
    }


def _find_downloaded_file(base_path: str) -> Optional[str]:
    for ext in ("", ".mp4", ".mkv", ".webm"):
        p = base_path if not ext else os.path.splitext(base_path)[0] + ext
        if os.path.exists(p):
            return p
    return None


def _download_once(url: str, output_template: str, format_selector: str) -> str:
    with yt_dlp.YoutubeDL(_build_opts(output_template, format_selector)) as ydl:
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
    if "requested format" in msg:
        return "Format topilmadi"
    if "ffmpeg" in msg:
        return "FFmpeg topilmadi"
    if "unable to download" in msg or "forbidden" in msg or "http" in msg:
        return "Platforma blokladi"
    if "not available" in msg or "private" in msg:
        return "Video mavjud emas"
    return "Video yuklab bo‘lmadi"


def _download_sync(url: str, quality: str) -> DownloadResult:
    with tempfile.TemporaryDirectory() as temp_dir:
        output_template = os.path.join(temp_dir, f"{uuid.uuid4()}.%(ext)s")
        primary_format = _quality_format(quality)
        fallback_format = "best"
        try:
            return DownloadResult(_download_once(url, output_template, primary_format), False)
        except (YtDlpDownloadError, DownloadError, Exception) as first_exc:
            logger.exception("Primary failed: %s", first_exc)
            print(f"[yt-dlp][primary-error] {first_exc}")
            try:
                return DownloadResult(_download_once(url, output_template, fallback_format), True)
            except Exception as second_exc:
                logger.exception("Fallback failed: %s", second_exc)
                print(f"[yt-dlp][fallback-error] {second_exc}")
                raise DownloadError(_classify_error(second_exc)) from second_exc


async def download_video(url: str, quality: str = "720") -> DownloadResult:
    try:
        result = await asyncio.to_thread(_download_sync, url, quality)
        if not result or not result.file_path or not os.path.exists(result.file_path):
            raise DownloadError("Fayl topilmadi")
        return result
    except DownloadError:
        raise
    except Exception as exc:
        raise DownloadError(_classify_error(exc)) from exc
