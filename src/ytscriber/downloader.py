"""YouTube transcript downloader."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from ytscriber.exceptions import (
    IPBlockedError,
    TranscriptNotFoundError,
    TranscriptsDisabledError,
    VideoNotFoundError,
)
from ytscriber.logging_config import get_logger
from ytscriber.metadata import fetch_video_metadata
from ytscriber.models import (
    DownloadStatus,
    TranscriptMetadata,
    TranscriptResult,
    VideoMetadata,
)
from ytscriber.progress import Spinner
from ytscriber.utils import escape_yaml_string, extract_video_id

logger = get_logger("downloader")


class TranscriptDownloader:
    """
    Downloads YouTube video transcripts.

    Handles single video downloads and batch processing with
    rate limiting, progress tracking, and resume capability.
    """

    DEFAULT_LANGUAGES = ["en", "en-US", "en-GB"]
    DEFAULT_DELAY = 60.0

    def __init__(
        self,
        languages: Optional[list[str]] = None,
        delay: float = DEFAULT_DELAY,
        output_dir: Optional[str] = None,
    ):
        """
        Initialize the transcript downloader.

        Args:
            languages: Language codes to try (default: en, en-US, en-GB)
            delay: Delay between requests in seconds (default: 60)
            output_dir: Directory to save transcripts (default: outputs)
        """
        self.languages = languages or self.DEFAULT_LANGUAGES
        self.delay = delay
        self.output_dir = Path(output_dir) if output_dir else Path("outputs")
        self._api = YouTubeTranscriptApi()

    def download(
        self,
        video_id: str,
        video_url: Optional[str] = None,
        output_file: Optional[str] = None,
    ) -> TranscriptResult:
        """
        Download transcript for a single video.

        Args:
            video_id: YouTube video ID
            video_url: Original YouTube URL (for metadata)
            output_file: Optional custom output path

        Returns:
            TranscriptResult with download status and content
        """
        url = video_url or f"https://www.youtube.com/watch?v={video_id}"
        logger.info(f"Downloading transcript for: {video_id}")

        try:
            # Get available transcripts
            transcript_list = self._api.list(video_id)

            # Find transcript in preferred languages
            transcript = self._find_best_transcript(transcript_list, video_id)

            # Fetch the transcript data
            with Spinner(f"Fetching transcript for {video_id}..."):
                transcript_data = transcript.fetch()

            # Combine text segments
            full_text = " ".join([item.text for item in transcript_data])

            # Fetch video metadata
            metadata = fetch_video_metadata(video_id, url)

            # Create transcript metadata
            transcript_meta = TranscriptMetadata(
                video_id=video_id,
                video_url=url,
                is_generated=getattr(transcript, "is_generated", None),
                is_translatable=getattr(transcript, "is_translatable", None),
                language=getattr(transcript, "language_code", None),
            )

            # Determine output path
            if output_file:
                output_path = Path(output_file)
            else:
                # Use date-prefixed filename: YYYY-MM-DD-{video_id}.md
                if metadata.published_date:
                    filename = f"{metadata.published_date}-{video_id}.md"
                else:
                    filename = f"{video_id}.md"
                output_path = self.output_dir / filename

            # Save to file
            self._save_transcript(full_text, metadata, transcript_meta, output_path)

            logger.info(f"✓ Saved transcript to: {output_path}")

            return TranscriptResult(
                video_id=video_id,
                status=DownloadStatus.SUCCESS,
                transcript_text=full_text,
                metadata=metadata,
                transcript_metadata=transcript_meta,
                output_path=str(output_path),
            )

        except TranscriptsDisabled:
            error_msg = f"Transcripts disabled for video {video_id}"
            logger.warning(f"✗ {error_msg}")
            return TranscriptResult(
                video_id=video_id,
                status=DownloadStatus.ERROR,
                error_message=error_msg,
            )

        except NoTranscriptFound:
            error_msg = f"No transcript found for video {video_id}"
            logger.warning(f"✗ {error_msg}")
            return TranscriptResult(
                video_id=video_id,
                status=DownloadStatus.ERROR,
                error_message=error_msg,
            )

        except VideoUnavailable:
            error_msg = f"Video {video_id} is unavailable"
            logger.warning(f"✗ {error_msg}")
            return TranscriptResult(
                video_id=video_id,
                status=DownloadStatus.ERROR,
                error_message=error_msg,
            )

        except Exception as e:
            return self._handle_unexpected_error(video_id, e)

    def download_from_url(
        self,
        url: str,
        output_file: Optional[str] = None,
    ) -> TranscriptResult:
        """
        Download transcript from a YouTube URL.

        Args:
            url: YouTube video URL
            output_file: Optional custom output path

        Returns:
            TranscriptResult with download status and content
        """
        video_id = extract_video_id(url)
        return self.download(
            video_id=video_id,
            video_url=url,
            output_file=output_file,
        )

    def _find_best_transcript(self, transcript_list, video_id: str):
        """Find the best available transcript."""
        # Try preferred languages first
        for lang in self.languages:
            try:
                return transcript_list.find_transcript([lang])
            except NoTranscriptFound:
                continue

        # Try manually created English transcript
        try:
            return transcript_list.find_manually_created_transcript(["en"])
        except NoTranscriptFound:
            pass

        # Fall back to first available
        available = list(transcript_list)
        if available:
            logger.debug(f"Using fallback transcript: {available[0].language_code}")
            return available[0]

        raise TranscriptNotFoundError(video_id, self.languages)

    def _save_transcript(
        self,
        text: str,
        metadata: VideoMetadata,
        transcript_meta: TranscriptMetadata,
        output_path: Path,
    ) -> None:
        """Save transcript to file with YAML frontmatter."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            # Write YAML frontmatter
            f.write("---\n")
            f.write(f"video_id: {metadata.video_id}\n")
            f.write(f"video_url: {metadata.url}\n")

            if metadata.title:
                f.write(f"title: {metadata.title}\n")
            if metadata.author:
                f.write(f"author: {metadata.author}\n")
            if metadata.published_date:
                f.write(f"published_date: {metadata.published_date}\n")
            if metadata.duration_minutes:
                f.write(f"length_minutes: {metadata.duration_minutes}\n")
            if metadata.view_count:
                f.write(f"views: {metadata.view_count}\n")
            if metadata.description:
                desc = escape_yaml_string(metadata.description)
                f.write(f'description: "{desc}"\n')
            if metadata.keywords:
                f.write(f"keywords: {metadata.keywords}\n")

            # Transcript metadata
            if transcript_meta.is_generated is not None:
                f.write(f"is_generated: {transcript_meta.is_generated}\n")
            if transcript_meta.is_translatable is not None:
                f.write(f"is_translatable: {transcript_meta.is_translatable}\n")

            f.write("---\n\n")
            f.write(text)

    def _handle_unexpected_error(
        self, video_id: str, error: Exception
    ) -> TranscriptResult:
        """Handle unexpected errors, checking for IP blocking."""
        error_msg = str(error).lower()

        # Check for IP blocking patterns
        ip_block_patterns = [
            "blocked" in error_msg and "ip" in error_msg,
            "youtube is blocking requests" in error_msg,
            "ip has been blocked" in error_msg,
            "requestblocked" in error_msg,
            "ipblocked" in error_msg,
        ]

        if any(ip_block_patterns):
            logger.error("CRITICAL: IP blocked by YouTube! Stopping to avoid ban.")
            raise IPBlockedError(str(error))

        logger.error(f"✗ Unexpected error for {video_id}: {error}")
        return TranscriptResult(
            video_id=video_id,
            status=DownloadStatus.ERROR,
            error_message=f"Unexpected error: {error}",
        )
