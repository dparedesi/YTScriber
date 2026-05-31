"""Tests for transcript summarizer module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytscriber.summarizer import (
    extract_video_id_from_filename,
    parse_frontmatter,
    has_summary,
    update_frontmatter_with_summary,
    find_row_by_video_id,
    process_transcript,
    SummarizeResult,
)


class TestExtractVideoIdFromFilename:
    """Tests for extract_video_id_from_filename function."""

    def test_standard_format(self):
        """Test standard filename format."""
        assert extract_video_id_from_filename("2025-05-12-i_cskqmWA3U.md") == "i_cskqmWA3U"

    def test_with_hyphens_in_id(self):
        """Test video ID that contains hyphens."""
        assert extract_video_id_from_filename("2025-01-01-abc-def-ghi.md") == "abc-def-ghi"

    def test_without_extension(self):
        """Test filename without .md extension."""
        assert extract_video_id_from_filename("2025-05-12-i_cskqmWA3U") == "i_cskqmWA3U"

    def test_path_object(self):
        """Test with Path object converted to string."""
        path = Path("data/OpenAI/transcripts/2025-05-12-i_cskqmWA3U.md")
        assert extract_video_id_from_filename(path.name) == "i_cskqmWA3U"

    def test_fallback_non_standard(self):
        """Test fallback for non-standard filename."""
        assert extract_video_id_from_filename("just_video_id.md") == "just_video_id"


class TestParseFrontmatter:
    """Tests for parse_frontmatter function."""

    def test_basic_frontmatter(self):
        """Test parsing basic frontmatter."""
        content = """---
video_id: test123
title: Test Title
---

Body content here.
"""
        frontmatter, body = parse_frontmatter(content)
        assert frontmatter["video_id"] == "test123"
        assert frontmatter["title"] == "Test Title"
        assert "Body content here." in body

    def test_no_frontmatter(self):
        """Test content without frontmatter."""
        content = "Just plain text content."
        frontmatter, body = parse_frontmatter(content)
        assert frontmatter == {}
        assert body == content

    def test_with_summary_field(self):
        """Test frontmatter that includes summary."""
        content = """---
video_id: test123
summary: |
  This is a multiline
  summary field.
---

Body content.
"""
        frontmatter, body = parse_frontmatter(content)
        assert "summary" in frontmatter
        assert "multiline" in frontmatter["summary"]

    def test_malformed_frontmatter(self):
        """Test handling of malformed frontmatter."""
        content = """---
video_id: test123
title: [invalid yaml
---

Body content.
"""
        frontmatter, body = parse_frontmatter(content)
        # Should return empty dict on parse error but not crash
        assert frontmatter == {}


class TestHasSummary:
    """Tests for has_summary function."""

    def test_no_summary(self, sample_transcript: Path):
        """Test file without summary."""
        assert has_summary(sample_transcript) is False

    def test_with_summary(self, sample_transcript_with_summary: Path):
        """Test file with summary."""
        assert has_summary(sample_transcript_with_summary) is True

    def test_nonexistent_file(self, temp_dir: Path):
        """Test nonexistent file returns False."""
        assert has_summary(temp_dir / "nonexistent.md") is False


class TestUpdateFrontmatterWithSummary:
    """Tests for update_frontmatter_with_summary function."""

    def test_adds_summary(self, sample_transcript: Path):
        """Test adding summary to file."""
        summary = "This is a test summary."
        update_frontmatter_with_summary(sample_transcript, summary)
        
        content = sample_transcript.read_text()
        assert "summary: |" in content
        assert "This is a test summary." in content

    def test_preserves_other_fields(self, sample_transcript: Path):
        """Test that other frontmatter fields are preserved."""
        summary = "Test summary."
        update_frontmatter_with_summary(sample_transcript, summary)
        
        frontmatter, _ = parse_frontmatter(sample_transcript.read_text())
        assert frontmatter["video_id"] == "test123abc"
        assert frontmatter["title"] == "Test Video Title"
        assert frontmatter["author"] == "Test Channel"
        assert "summary" in frontmatter

    def test_preserves_body(self, sample_transcript: Path):
        """Test that body content is preserved."""
        original_content = sample_transcript.read_text()
        _, original_body = parse_frontmatter(original_content)
        
        update_frontmatter_with_summary(sample_transcript, "Test summary.")
        
        new_content = sample_transcript.read_text()
        _, new_body = parse_frontmatter(new_content)
        
        # Body should be identical
        assert original_body.strip() == new_body.strip()


class TestFindRowByVideoId:
    """Tests for find_row_by_video_id function."""

    def test_find_existing(self):
        """Test finding an existing video ID."""
        rows = [
            {"url": "https://www.youtube.com/watch?v=abc123"},
            {"url": "https://www.youtube.com/watch?v=xyz789"},
        ]
        row = find_row_by_video_id(rows, "abc123")
        assert row is not None
        assert "abc123" in row["url"]

    def test_not_found(self):
        """Test when video ID is not found."""
        rows = [
            {"url": "https://www.youtube.com/watch?v=abc123"},
        ]
        row = find_row_by_video_id(rows, "notfound")
        assert row is None

    def test_empty_rows(self):
        """Test with empty rows list."""
        row = find_row_by_video_id([], "abc123")
        assert row is None


class TestProcessTranscript:
    """Tests for process_transcript function."""

    def test_dry_run(self, sample_transcript: Path):
        """Test dry run mode doesn't modify file."""
        original_content = sample_transcript.read_text()

        result = process_transcript(
            file_path=sample_transcript,
            api_key="test_key",
            dry_run=True,
        )

        assert result.success is True
        assert "dry-run" in result.error_message
        assert sample_transcript.read_text() == original_content

    def test_skip_existing_summary(self, sample_transcript_with_summary: Path):
        """Test skipping files that already have summaries."""
        result = process_transcript(
            file_path=sample_transcript_with_summary,
            api_key="test_key",
        )

        assert result.success is True
        assert "skipped" in result.error_message

    @patch("ytscriber.auth.requests.post")
    def test_successful_summary_zai(
        self,
        mock_post: MagicMock,
        sample_transcript: Path,
        mock_zai_response: dict,
    ):
        """Test successful summarization with Z.AI provider."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_zai_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = process_transcript(
            file_path=sample_transcript,
            api_key="test_key",
            delay=0,
        )

        assert result.success is True
        assert result.summary is not None
        assert has_summary(sample_transcript) is True

    @patch("ytscriber.auth.requests.post")
    def test_successful_summary_openrouter(
        self,
        mock_post: MagicMock,
        sample_transcript: Path,
        mock_openrouter_response: dict,
    ):
        """Test successful summarization with OpenRouter provider."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_openrouter_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = process_transcript(
            file_path=sample_transcript,
            api_key="test_key",
            delay=0,
            provider="openrouter",
        )

        assert result.success is True
        assert result.summary is not None

    @patch("ytscriber.auth.requests.post")
    def test_force_resummary(
        self,
        mock_post: MagicMock,
        sample_transcript_with_summary: Path,
        mock_zai_response: dict,
    ):
        """Test force flag re-summarizes existing summaries."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_zai_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = process_transcript(
            file_path=sample_transcript_with_summary,
            api_key="test_key",
            force=True,
            delay=0,
        )

        assert result.success is True
        assert mock_post.called

    def test_empty_transcript(self, temp_dir: Path):
        """Test handling of empty transcript."""
        empty_file = temp_dir / "2025-01-01-empty123.md"
        empty_file.write_text("""---
video_id: empty123
title: Empty Video
---

""")

        result = process_transcript(
            file_path=empty_file,
            api_key="test_key",
        )

        assert result.success is False
        assert "empty" in result.error_message


class TestIntegration:
    """Integration tests for summarizer."""

    @patch("ytscriber.auth.requests.post")
    def test_process_folder(
        self,
        mock_post: MagicMock,
        sample_folder_structure: Path,
        mock_zai_response: dict,
    ):
        """Test processing an entire folder."""
        from ytscriber.summarizer import process_folder

        mock_response = MagicMock()
        mock_response.json.return_value = mock_zai_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        progress = process_folder(
            folder_path=sample_folder_structure,
            api_key="test_key",
            delay=0,
        )

        assert progress.total == 1
        assert progress.success == 1
        assert progress.errors == 0

    @patch("ytscriber.auth.requests.post")
    def test_csv_updated_after_summary(
        self,
        mock_post: MagicMock,
        sample_folder_structure: Path,
        mock_zai_response: dict,
    ):
        """Test that CSV is updated after successful summary."""
        from ytscriber.summarizer import process_folder
        import csv

        mock_response = MagicMock()
        mock_response.json.return_value = mock_zai_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        process_folder(
            folder_path=sample_folder_structure,
            api_key="test_key",
            delay=0,
        )

        # Check CSV was updated
        csv_path = sample_folder_structure / "videos.csv"
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert rows[0]["summary_done"] == "success"

    def test_idempotency(
        self,
        sample_folder_structure: Path,
        mock_zai_response: dict,
    ):
        """Test that re-running skips already processed files."""
        from ytscriber.summarizer import process_folder

        with patch("ytscriber.auth.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_zai_response
            mock_response.raise_for_status.return_value = None
            mock_post.return_value = mock_response

            # First run - should process
            progress1 = process_folder(
                folder_path=sample_folder_structure,
                api_key="test_key",
                delay=0,
            )
            assert progress1.success == 1

        with patch("ytscriber.auth.requests.post") as mock_post2:
            # Second run - should skip
            progress2 = process_folder(
                folder_path=sample_folder_structure,
                api_key="test_key",
                delay=0,
            )
            assert progress2.skipped == 1
            assert progress2.success == 0
            # API should NOT have been called on second run
            assert mock_post2.call_count == 0
