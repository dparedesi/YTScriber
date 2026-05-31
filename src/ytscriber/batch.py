"""Batch operations for transcript downloads."""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from ytscriber.csv_handler import (
    ensure_csv_columns,
    get_url_from_row,
    is_already_downloaded,
    read_video_urls,
    update_csv_status,
)
from ytscriber.downloader import TranscriptDownloader
from ytscriber.exceptions import CSVError, IPBlockedError, InvalidURLError
from ytscriber.logging_config import get_logger
from ytscriber.models import BatchProgress
from ytscriber.progress import Spinner
from ytscriber.summarizer import (
    DEFAULT_MODEL as SUMMARIZE_DEFAULT_MODEL,
    DEFAULT_MAX_WORDS as SUMMARIZE_DEFAULT_MAX_WORDS,
    process_transcript,
)
from ytscriber.utils import extract_video_id

logger = get_logger("batch")


def find_video_csv_files(data_dir: Path) -> list[Path]:
    """Find all videos.csv files in the data directory."""
    if not data_dir.exists():
        return []
    return sorted(data_dir.rglob("videos.csv"))


def download_from_csv(
    csv_path: Path,
    output_dir: Path,
    languages: Optional[list[str]] = None,
    delay: float = 60.0,
    summarize: bool = False,
    api_key: Optional[str] = None,
    summarize_model: str = SUMMARIZE_DEFAULT_MODEL,
    summarize_max_words: int = SUMMARIZE_DEFAULT_MAX_WORDS,
) -> BatchProgress:
    """Download transcripts for a single CSV file.

    When ``summarize`` is enabled and an ``api_key`` is provided, each freshly
    downloaded transcript is summarized in a background worker so the LLM call
    overlaps the rate-limiting delay before the next download. Summarization
    never blocks or delays downloads: pending summaries are drained only after
    all downloads finish.
    """
    try:
        rows = read_video_urls(str(csv_path))
    except CSVError as e:
        logger.error(str(e))
        return BatchProgress(total=0)

    fieldnames = list(rows[0].keys()) if rows else []
    fieldnames = ensure_csv_columns(fieldnames)

    summarize_enabled = bool(summarize and api_key)
    if summarize_enabled and "summary_done" not in fieldnames:
        fieldnames.append("summary_done")
        for row in rows:
            row.setdefault("summary_done", "")

    progress = BatchProgress(total=len(rows))
    logger.info(f"Found {len(rows)} URLs in {csv_path}.")
    if summarize_enabled:
        logger.info("Summaries will be generated during the delay between downloads.")

    downloader = TranscriptDownloader(
        languages=languages,
        delay=delay,
        output_dir=str(output_dir),
    )

    csv_lock = threading.Lock()
    executor: Optional[ThreadPoolExecutor] = (
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="summarize")
        if summarize_enabled
        else None
    )
    futures: list[Future] = []

    def save_csv() -> None:
        try:
            with csv_lock:
                update_csv_status(str(csv_path), rows, fieldnames)
        except CSVError as e:
            logger.warning(f"Could not save CSV progress: {e}")

    def summarize_in_background(output_path: Path, row: dict) -> None:
        """Summarize a downloaded transcript; never raises."""
        try:
            logger.info(f"  → Summarizing {output_path.stem} in background...")
            res = process_transcript(
                file_path=output_path,
                api_key=api_key,  # type: ignore[arg-type]
                model=summarize_model,
                max_words=summarize_max_words,
                delay=0.0,
            )
            if res.error_message and "skipped" in res.error_message:
                return
            with csv_lock:
                row["summary_done"] = (
                    "success" if res.success else f"error: {res.error_message}"
                )
            save_csv()
            if res.success:
                logger.info(f"✓ Summarized: {res.video_id}")
            else:
                logger.warning(f"✗ Summary failed: {res.video_id} - {res.error_message}")
        except Exception as e:  # pragma: no cover - defensive guard
            logger.warning(f"Summary worker error for {output_path.name}: {e}")

    try:
        for i, row in enumerate(rows, 1):
            url = get_url_from_row(row)

            if not url:
                if not row.get("transcript_downloaded"):
                    row["transcript_downloaded"] = "skipped (no URL)"
                    save_csv()
                progress.processed += 1
                continue

            if is_already_downloaded(row):
                logger.info(f"[{i}/{progress.total}] Skipping (already processed)")
                progress.processed += 1
                progress.skipped += 1
                continue

            try:
                video_id = extract_video_id(url)
            except InvalidURLError:
                logger.warning(f"[{i}/{progress.total}] Invalid URL: {url}")
                row["transcript_downloaded"] = "error: invalid URL"
                progress.processed += 1
                progress.errors += 1
                save_csv()
                continue

            output_dir.mkdir(parents=True, exist_ok=True)
            possible_files = list(output_dir.glob(f"*{video_id}.md"))
            if possible_files:
                logger.info(f"[{i}/{progress.total}] Skipping {video_id} (file exists)")
                row["transcript_downloaded"] = "success (already exists)"
                progress.processed += 1
                progress.success += 1
                save_csv()
                continue

            logger.info(f"[{i}/{progress.total}] Downloading: {video_id}")

            try:
                result = downloader.download(
                    video_id=video_id,
                    video_url=url,
                    apply_delay=i > 1,
                )

                progress.processed += 1
                if result.success:
                    row["transcript_downloaded"] = "success"
                    if result.metadata:
                        if result.metadata.title:
                            row["title"] = result.metadata.title.replace("\n", " ").replace("\r", " ")
                        if result.metadata.duration_minutes is not None:
                            row["duration_minutes"] = str(result.metadata.duration_minutes)
                        if result.metadata.view_count is not None:
                            row["view_count"] = str(result.metadata.view_count)
                        if result.metadata.published_date:
                            row["published_date"] = result.metadata.published_date
                        if result.metadata.description:
                            row["description"] = result.metadata.description.replace("\n", " ").replace("\r", " ")
                    progress.success += 1

                    if summarize_enabled and executor and result.output_path:
                        # Kick off summarization immediately so it runs during
                        # the delay before the next download. Non-blocking.
                        futures.append(
                            executor.submit(
                                summarize_in_background, Path(result.output_path), row
                            )
                        )
                else:
                    row["transcript_downloaded"] = f"error: {result.error_message or 'unknown'}"
                    progress.errors += 1

                save_csv()

            except IPBlockedError:
                logger.error("IP blocked by YouTube. Saving progress and stopping.")
                row["transcript_downloaded"] = "error: IP blocked (stopped)"
                progress.processed += 1
                progress.errors += 1
                save_csv()
                raise
    finally:
        if executor is not None:
            if futures:
                logger.info("Waiting for pending summaries to finish...")
                with Spinner("Generating summaries..."):
                    executor.shutdown(wait=True)
            else:
                executor.shutdown(wait=True)

    save_csv()
    logger.info(f"Updated CSV file: {csv_path}")

    return progress


def download_all_transcripts(
    data_dir: Path,
    delay: float = 60.0,
    languages: Optional[list[str]] = None,
    summarize: bool = False,
    api_key: Optional[str] = None,
    summarize_model: str = SUMMARIZE_DEFAULT_MODEL,
    summarize_max_words: int = SUMMARIZE_DEFAULT_MAX_WORDS,
) -> BatchProgress:
    """Download transcripts for all folders with videos.csv."""
    csv_files = find_video_csv_files(data_dir)
    if not csv_files:
        raise FileNotFoundError(f"No videos.csv files found in {data_dir}")

    total_progress = BatchProgress(total=0)

    for csv_path in csv_files:
        output_dir = csv_path.parent / "transcripts"
        output_dir.mkdir(parents=True, exist_ok=True)

        progress = download_from_csv(
            csv_path=csv_path,
            output_dir=output_dir,
            languages=languages,
            delay=delay,
            summarize=summarize,
            api_key=api_key,
            summarize_model=summarize_model,
            summarize_max_words=summarize_max_words,
        )

        total_progress.total += progress.total
        total_progress.processed += progress.processed
        total_progress.success += progress.success
        total_progress.skipped += progress.skipped
        total_progress.errors += progress.errors

    return total_progress
