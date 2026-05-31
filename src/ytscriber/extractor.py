"""YouTube channel video extractor."""

from __future__ import annotations

from typing import Optional

from ytscriber.exceptions import ChannelExtractionError
from ytscriber.logging_config import get_logger
from ytscriber.models import VideoMetadata
from ytscriber.utils import (
    ensure_videos_endpoint,
    is_playlist_url,
    normalize_channel_url,
    normalize_playlist_url,
)

logger = get_logger("extractor")

# Try to import yt-dlp (preferred)
try:
    import yt_dlp

    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False
    logger.debug("yt-dlp not available")

# Try to import pytube (fallback)
try:
    from pytube import Channel

    PYTUBE_AVAILABLE = True
except ImportError:
    PYTUBE_AVAILABLE = False
    logger.debug("pytube not available")

if not YT_DLP_AVAILABLE and not PYTUBE_AVAILABLE:
    raise ImportError(
        "Either yt-dlp or pytube is required. Install with: pip install yt-dlp"
    )


class ChannelExtractor:
    """
    Extracts video metadata from YouTube channels.

    Uses yt-dlp as the primary method with pytube as fallback.
    """

    def __init__(self, quiet: bool = True):
        """
        Initialize the channel extractor.

        Args:
            quiet: Suppress yt-dlp output (default: True)
        """
        self.quiet = quiet

    def extract_videos(
        self,
        channel_url: str,
        max_videos: Optional[int] = None,
    ) -> list[VideoMetadata]:
        """
        Extract video metadata from a YouTube channel or playlist.

        Args:
            channel_url: YouTube channel or playlist URL
            max_videos: Maximum number of videos to extract (None for all)

        Returns:
            List of VideoMetadata objects

        Raises:
            ChannelExtractionError: If extraction fails
        """
        is_playlist = is_playlist_url(channel_url)
        kind = "playlist" if is_playlist else "channel"
        logger.info(f"Extracting videos from {kind}: {channel_url}")

        if YT_DLP_AVAILABLE:
            videos = self._extract_with_ytdlp(channel_url, max_videos)
            if videos:
                return videos

        if PYTUBE_AVAILABLE and not is_playlist:
            videos = self._extract_with_pytube(channel_url, max_videos)
            if videos:
                return videos

        raise ChannelExtractionError(channel_url, "No videos found")

    def _extract_with_ytdlp(
        self,
        channel_url: str,
        max_videos: Optional[int],
    ) -> list[VideoMetadata]:
        """Extract videos using yt-dlp."""
        if is_playlist_url(channel_url):
            url = normalize_playlist_url(channel_url)
        else:
            url = ensure_videos_endpoint(channel_url)
        videos: list[VideoMetadata] = []

        ydl_opts = {
            "quiet": self.quiet,
            "no_warnings": self.quiet,
            "extract_flat": True,
            "playlistend": max_videos,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.debug(f"Fetching channel: {url}")
                info = ydl.extract_info(url, download=False)

                if "entries" not in info:
                    return videos

                for entry in info["entries"]:
                    if not entry or not isinstance(entry, dict):
                        continue

                    video_id = entry.get("id")

                    # Filter out channel IDs (start with UC and are longer)
                    if not video_id or len(video_id) != 11 or video_id.startswith("UC"):
                        continue

                    metadata = self._parse_ytdlp_entry(video_id, entry)
                    videos.append(metadata)

                logger.info(f"Found {len(videos)} videos")

        except Exception as e:
            logger.error(f"yt-dlp extraction failed: {e}")

        return videos

    def _parse_ytdlp_entry(self, video_id: str, entry: dict) -> VideoMetadata:
        """Parse a yt-dlp entry into VideoMetadata."""
        url = f"https://www.youtube.com/watch?v={video_id}"

        duration_seconds = None
        duration_minutes = None
        if entry.get("duration") is not None:
            duration_seconds = int(entry["duration"])
            duration_minutes = round(entry["duration"] / 60, 2)

        view_count = None
        if entry.get("view_count") is not None:
            view_count = int(entry["view_count"])

        description = entry.get("description")
        if description and len(description) > 500:
            description = description[:500] + "..."

        # Extract upload date (yt-dlp returns YYYYMMDD format)
        published_date = None
        upload_date = entry.get("upload_date")
        if upload_date:
            try:
                raw = str(upload_date)
                published_date = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
            except (ValueError, IndexError):
                pass

        return VideoMetadata(
            video_id=video_id,
            url=url,
            title=entry.get("title"),
            duration_seconds=duration_seconds,
            duration_minutes=duration_minutes,
            view_count=view_count,
            description=description,
            published_date=published_date,
        )

    def _extract_with_pytube(
        self,
        channel_url: str,
        max_videos: Optional[int],
    ) -> list[VideoMetadata]:
        """Extract videos using pytube (fallback method)."""
        videos: list[VideoMetadata] = []

        try:
            channel = Channel(normalize_channel_url(channel_url))
            logger.debug(f"Fetching channel: {channel.channel_name or channel_url}")

            video_urls = channel.video_urls
            if max_videos:
                video_urls = video_urls[:max_videos]

            for video_url in video_urls:
                video_id = self._extract_id_from_url(video_url)
                if video_id:
                    videos.append(
                        VideoMetadata(
                            video_id=video_id,
                            url=video_url,
                        )
                    )

            logger.info(f"Found {len(videos)} videos (pytube)")

        except Exception as e:
            logger.error(f"pytube extraction failed: {e}")

        return videos

    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """Extract video ID from URL."""
        if "watch?v=" in url:
            return url.split("watch?v=")[1].split("&")[0]
        elif "youtu.be/" in url:
            return url.split("youtu.be/")[1].split("?")[0]
        return None
