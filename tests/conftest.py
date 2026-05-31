"""Pytest fixtures for transcript downloader tests."""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_csv(temp_dir: Path) -> Path:
    """Create a sample CSV file with video URLs."""
    csv_path = temp_dir / "videos.csv"
    
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["url", "title", "transcript_downloaded"],
        )
        writer.writeheader()
        writer.writerows([
            {
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "title": "Test Video 1",
                "transcript_downloaded": "",
            },
            {
                "url": "https://www.youtube.com/watch?v=abc123xyz45",
                "title": "Test Video 2",
                "transcript_downloaded": "success",
            },
            {
                "url": "https://www.youtube.com/watch?v=xyz789abc12",
                "title": "Test Video 3",
                "transcript_downloaded": "error: not found",
            },
        ])
    
    return csv_path


@pytest.fixture
def sample_video_ids() -> list[str]:
    """Sample valid YouTube video IDs."""
    return [
        "dQw4w9WgXcQ",
        "abc123xyz45",
        "xyz789-_abc",
    ]


@pytest.fixture
def sample_urls() -> list[str]:
    """Sample valid YouTube URLs."""
    return [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/abc123xyz45",
        "https://www.youtube.com/embed/xyz789-_abc",
    ]


@pytest.fixture
def invalid_urls() -> list[str]:
    """Sample invalid URLs."""
    return [
        "https://example.com/video",
        "https://vimeo.com/123456789",
        "not-a-url",
        "",
    ]


@pytest.fixture
def sample_transcript(temp_dir: Path) -> Path:
    """Create a sample transcript file."""
    content = '''---
video_id: test123abc
video_url: https://www.youtube.com/watch?v=test123abc
title: Test Video Title
author: Test Channel
published_date: 2025-01-01
length_minutes: 5.5
views: 1000
description: "A test video about testing."
is_generated: True
is_translatable: True
---

This is the transcript content. It talks about various topics
that should be summarized by the AI model. The content includes
multiple paragraphs and detailed explanations about the subject
matter. This test content is designed to verify that the
summarization feature works correctly.
'''
    transcript_path = temp_dir / "2025-01-01-test123abc.md"
    transcript_path.write_text(content)
    return transcript_path


@pytest.fixture
def sample_transcript_with_summary(temp_dir: Path) -> Path:
    """Create a sample transcript file that already has a summary."""
    content = '''---
video_id: existing123
video_url: https://www.youtube.com/watch?v=existing123
title: Existing Summary Video
author: Test Channel
published_date: 2025-01-02
summary: |
  This is an existing summary that was already generated.
  It should be skipped during processing.
---

This is the transcript content.
'''
    transcript_path = temp_dir / "2025-01-02-existing123.md"
    transcript_path.write_text(content)
    return transcript_path


@pytest.fixture
def sample_folder_structure(temp_dir: Path) -> Path:
    """Create a sample channel folder structure."""
    channel_dir = temp_dir / "TestChannel"
    transcripts_dir = channel_dir / "transcripts"
    transcripts_dir.mkdir(parents=True)
    
    # Create a transcript file
    transcript_content = '''---
video_id: folder123
video_url: https://www.youtube.com/watch?v=folder123
title: Folder Test Video
author: Test Channel
---

This is transcript content for folder testing.
'''
    (transcripts_dir / "2025-01-03-folder123.md").write_text(transcript_content)
    
    # Create CSV file
    csv_path = channel_dir / "videos.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["url", "title", "transcript_downloaded", "summary_done"],
        )
        writer.writeheader()
        writer.writerows([
            {
                "url": "https://www.youtube.com/watch?v=folder123",
                "title": "Folder Test Video",
                "transcript_downloaded": "success",
                "summary_done": "",
            },
        ])
    
    return channel_dir


class MockResponse:
    """Mock response object for requests."""
    
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json_data = json_data
        self.status_code = status_code
    
    def json(self) -> dict:
        return self._json_data
    
    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            from requests import HTTPError
            raise HTTPError(response=self)


@pytest.fixture
def mock_openrouter_response() -> dict:
    """Sample OpenRouter API response (OpenAI chat completions format)."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "This is a test summary generated by the mock API. It contains approximately the right number of words to simulate a real summary response from the OpenRouter API."
                }
            }
        ],
        "usage": {
            "prompt_tokens": 500,
            "completion_tokens": 100,
            "total_tokens": 600
        }
    }


@pytest.fixture
def mock_zai_response() -> dict:
    """Sample Z.AI API response (Anthropic Messages format)."""
    return {
        "content": [
            {
                "type": "text",
                "text": "This is a test summary generated by the mock API. It contains approximately the right number of words to simulate a real summary response from the Z.AI API."
            }
        ],
        "model": "GLM-5.1",
        "usage": {
            "input_tokens": 500,
            "output_tokens": 100,
        }
    }

