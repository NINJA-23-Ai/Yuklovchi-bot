import asyncio
import os
import tempfile
import uuid
from typing import Optional

import yt_dlp


class DownloadError(Exception):
    """Video yuklab olishdagi maxsus xatolik."""


def _download_sync(url: str) -> str:
    """Blocking yt-dlp download function, thread ichida ishlaydi."""
    with tempfile.TemporaryDirectory() as temp_dir:
        unique_name = f"{uuid.uuid4()}.%(ext)s"
        output_template = os.path.join(temp_dir, unique_name)

        ydl_opts = {
            "format": "mp4/bestvideo+bestaudio/best",
            "outtmpl": output_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise DownloadError("No metadata from yt-dlp")

            downloaded_path = ydl.prepare_filename(info)

        # prepare_filename va postprocess nomlari farq qilishi mumkin.
        final_candidates = [
            downloaded_path,
            os.path.splitext(downloaded_path)[0] + ".mp4",
        ]

        real_path: Optional[str] = next((p for p in final_candidates if os.path.exists(p)), None)
        if not real_path:
            raise DownloadError("Downloaded file not found")

        persistent_path = os.path.join(tempfile.gettempdir(), f"video_{uuid.uuid4()}.mp4")
        os.replace(real_path, persistent_path)
        return persistent_path


async def download_video(url: str) -> str:
    """yt-dlp downloadni event-loopni bloklamasdan bajaradi."""
    try:
        return await asyncio.to_thread(_download_sync, url)
    except Exception as exc:
        raise DownloadError(str(exc)) from exc
