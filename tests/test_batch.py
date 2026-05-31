"""Tests for batch downloads."""

from __future__ import annotations

import csv

from ytscriber.batch import download_from_csv, find_video_csv_files
from ytscriber.models import DownloadStatus, TranscriptResult, VideoMetadata


def test_find_video_csv_files(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "videos.csv").write_text("url\n", encoding="utf-8")
    (tmp_path / "b" / "videos.csv").write_text("url\n", encoding="utf-8")

    csv_files = find_video_csv_files(tmp_path)
    assert len(csv_files) == 2
    assert csv_files[0].name == "videos.csv"


def test_download_from_csv(monkeypatch, tmp_path):
    csv_path = tmp_path / "videos.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "transcript_downloaded"])
        writer.writeheader()
        writer.writerow({"url": "https://www.youtube.com/watch?v=abc123xyz45"})
        writer.writerow({"url": ""})

    output_dir = tmp_path / "transcripts"

    class DummyDownloader:
        def __init__(self, languages=None, delay=0.0, output_dir=None):
            self.languages = languages
            self.delay = delay
            self.output_dir = output_dir

        def download(self, video_id, video_url=None, output_file=None, apply_delay=False):
            metadata = VideoMetadata(
                video_id=video_id,
                url=video_url or f"https://www.youtube.com/watch?v={video_id}",
                title="Test Video",
                duration_minutes=1.5,
                view_count=100,
                published_date="2025-01-01",
                description="Test description",
            )
            return TranscriptResult(
                video_id=video_id,
                status=DownloadStatus.SUCCESS,
                metadata=metadata,
            )

    monkeypatch.setattr("ytscriber.batch.TranscriptDownloader", DummyDownloader)

    progress = download_from_csv(
        csv_path=csv_path,
        output_dir=output_dir,
        languages=["en"],
        delay=0,
    )

    assert progress.total == 2
    assert progress.processed == 2
    assert progress.success == 1
    assert progress.errors == 0


def test_download_from_csv_with_summarize(monkeypatch, tmp_path):
    csv_path = tmp_path / "videos.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "transcript_downloaded"])
        writer.writeheader()
        writer.writerow({"url": "https://www.youtube.com/watch?v=abc123xyz45"})

    output_dir = tmp_path / "transcripts"

    class WritingDownloader:
        def __init__(self, languages=None, delay=0.0, output_dir=None):
            self.output_dir = output_dir

        def download(self, video_id, video_url=None, output_file=None, apply_delay=False):
            from pathlib import Path

            out = Path(self.output_dir) / f"2025-01-01-{video_id}.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                "---\n"
                f"video_id: {video_id}\n"
                "title: Test Video\n"
                "author: Tester\n"
                "---\n\n"
                "This is the transcript body.",
                encoding="utf-8",
            )
            metadata = VideoMetadata(
                video_id=video_id,
                url=video_url or f"https://www.youtube.com/watch?v={video_id}",
                title="Test Video",
                published_date="2025-01-01",
            )
            return TranscriptResult(
                video_id=video_id,
                status=DownloadStatus.SUCCESS,
                metadata=metadata,
                output_path=str(out),
            )

    monkeypatch.setattr("ytscriber.batch.TranscriptDownloader", WritingDownloader)
    # Avoid any network: stub the LLM call used by process_transcript.
    monkeypatch.setattr(
        "ytscriber.summarizer.summarize_transcript",
        lambda **kwargs: "A concise canned summary.",
    )

    progress = download_from_csv(
        csv_path=csv_path,
        output_dir=output_dir,
        languages=["en"],
        delay=0,
        summarize=True,
        api_key="test-key",
    )

    assert progress.success == 1

    # Summary must be written into the transcript frontmatter.
    transcript = next(output_dir.glob("*abc123xyz45.md")).read_text(encoding="utf-8")
    assert "summary: |" in transcript
    assert "A concise canned summary." in transcript

    # CSV must record summary completion.
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["summary_done"] == "success"


def test_download_from_csv_summarize_disabled_without_key(monkeypatch, tmp_path):
    """summarize=True but no api_key should not enable summarization."""
    csv_path = tmp_path / "videos.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "transcript_downloaded"])
        writer.writeheader()
        writer.writerow({"url": "https://www.youtube.com/watch?v=abc123xyz45"})

    output_dir = tmp_path / "transcripts"

    class DummyDownloader:
        def __init__(self, languages=None, delay=0.0, output_dir=None):
            self.output_dir = output_dir

        def download(self, video_id, video_url=None, output_file=None, apply_delay=False):
            return TranscriptResult(
                video_id=video_id,
                status=DownloadStatus.SUCCESS,
                metadata=VideoMetadata(video_id=video_id, url=video_url or ""),
                output_path="",
            )

    monkeypatch.setattr("ytscriber.batch.TranscriptDownloader", DummyDownloader)

    progress = download_from_csv(
        csv_path=csv_path,
        output_dir=output_dir,
        delay=0,
        summarize=True,
        api_key=None,
    )

    assert progress.success == 1
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # No summarization ran, so summary_done stays blank.
    assert not rows[0].get("summary_done")

