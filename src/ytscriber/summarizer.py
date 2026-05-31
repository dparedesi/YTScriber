"""AI-powered transcript summarization."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
import yaml

from ytscriber.csv_handler import (
    get_url_from_row,
    read_video_urls,
    update_csv_status,
)
from ytscriber.logging_config import get_logger

logger = get_logger("summarizer")

# Default configuration
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
DEFAULT_DELAY = 4.0
DEFAULT_MAX_WORDS = 500
API_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# Prompt template embedded in code for simplicity
SUMMARIZE_PROMPT_TEMPLATE = """You are an expert content summarizer. Your task is to create a comprehensive, 
information-dense summary of the following YouTube video transcript.

VIDEO TITLE: {title}
VIDEO AUTHOR: {author}

TRANSCRIPT:
{transcript}

---

INSTRUCTIONS:
1. Write a summary of approximately {max_words} words ({min_words}-{max_words_upper} words acceptable)
2. Focus on the key ideas, insights, and takeaways
3. Preserve important technical details, names, and specific examples
4. Write in a neutral, informative tone
5. Structure the summary with clear logical flow
6. Do NOT include phrases like "This video discusses..." or "The speaker talks about..."
7. Write as if summarizing the content itself, not describing the video

OUTPUT FORMAT:
Write the summary as one flowing continuous paragraph. Do not use bullet points or headers. Do not use em-dashes.
Start directly with the content - no preamble."""


@dataclass
class SummarizeResult:
    """Result of a summarization attempt."""

    video_id: str
    success: bool
    summary: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class BatchSummarizeProgress:
    """Progress tracking for batch summarization."""

    total: int
    processed: int = 0
    success: int = 0
    skipped: int = 0
    errors: int = 0

    @property
    def remaining(self) -> int:
        """Get remaining items to process."""
        return self.total - self.processed


def extract_video_id_from_filename(filename: str) -> str:
    """
    Extract video ID from transcript filename.
    
    Filename format: {YYYY-MM-DD}-{video_id}.md
    Example: 2025-05-12-i_cskqmWA3U.md -> i_cskqmWA3U
    
    Args:
        filename: Transcript filename (with or without .md extension)
    
    Returns:
        YouTube video ID
    """
    stem = Path(filename).stem
    # Split on first 3 hyphens (date parts), take the rest
    parts = stem.split("-", 3)
    if len(parts) == 4:
        return parts[3]
    # Fallback: return the whole stem if format doesn't match
    return stem


def parse_frontmatter(file_content: str) -> tuple[dict, str]:
    """
    Parse YAML frontmatter and body from markdown file.
    
    Args:
        file_content: Full file content
    
    Returns:
        Tuple of (frontmatter dict, body content)
    """
    if not file_content.startswith("---"):
        return {}, file_content
    
    # Find the closing ---
    end_match = re.search(r'\n---\s*\n', file_content[3:])
    if not end_match:
        return {}, file_content
    
    frontmatter_end = end_match.end() + 3
    frontmatter_str = file_content[4:end_match.start() + 3]
    body = file_content[frontmatter_end:]
    
    try:
        frontmatter = yaml.safe_load(frontmatter_str)
        return frontmatter or {}, body
    except yaml.YAMLError:
        return {}, file_content


def has_summary(file_path: Path) -> bool:
    """
    Check if a transcript file already has a summary.
    
    Args:
        file_path: Path to transcript file
    
    Returns:
        True if summary field exists in frontmatter
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        frontmatter, _ = parse_frontmatter(content)
        return bool(frontmatter.get("summary"))
    except Exception:
        return False


def update_frontmatter_with_summary(file_path: Path, summary: str) -> None:
    """
    Add summary field to frontmatter and save file.
    
    Uses YAML literal block scalar (|) for multiline summary.
    
    Args:
        file_path: Path to transcript file
        summary: Summary text to add
    """
    content = file_path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(content)
    
    # Add summary to frontmatter
    frontmatter["summary"] = summary
    
    # Custom YAML dump that uses literal block scalar for summary
    # This preserves readability in the markdown file
    yaml_lines = ["---"]
    for key, value in frontmatter.items():
        if key == "summary":
            # Use literal block scalar for multiline summary
            yaml_lines.append(f"{key}: |")
            for line in value.split("\n"):
                yaml_lines.append(f"  {line}")
        elif isinstance(value, str) and ('"' in value or '\n' in value or ':' in value):
            # Quote strings that need escaping
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            yaml_lines.append(f'{key}: "{escaped}"')
        elif isinstance(value, bool):
            yaml_lines.append(f"{key}: {str(value)}")
        elif value is None:
            yaml_lines.append(f"{key}: ")
        else:
            yaml_lines.append(f"{key}: {value}")
    yaml_lines.append("---")
    yaml_lines.append("")
    
    new_content = "\n".join(yaml_lines) + body
    file_path.write_text(new_content, encoding="utf-8")


def summarize_transcript(
    content: str,
    title: str,
    author: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    max_words: int = DEFAULT_MAX_WORDS,
) -> str:
    """
    Send transcript to OpenRouter and get summary.
    
    Args:
        content: Transcript text
        title: Video title
        author: Video author/channel
        api_key: OpenRouter API key
        model: Model identifier
        max_words: Target word count
    
    Returns:
        Summary text
    
    Raises:
        requests.RequestException: On API errors
    """
    prompt = SUMMARIZE_PROMPT_TEMPLATE.format(
        title=title,
        author=author or "Unknown",
        transcript=content,
        max_words=max_words,
        min_words=max_words - 50,
        max_words_upper=max_words + 50,
    )
    
    response = requests.post(
        API_BASE_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "reasoning": {"effort": "high"},  # Enable deeper thinking
        },
        timeout=120.0,
    )
    response.raise_for_status()
    
    data = response.json()
    content = data["choices"][0]["message"]["content"].strip()
    # Post-process to ensure single continuous paragraph by replacing newlines/spaces with single space
    return " ".join(content.split())


def find_row_by_video_id(rows: list[dict], video_id: str) -> Optional[dict]:
    """
    Find a CSV row by video ID extracted from URL.
    
    Args:
        rows: List of CSV row dictionaries
        video_id: YouTube video ID to find
    
    Returns:
        Row dictionary or None if not found
    """
    for row in rows:
        url = get_url_from_row(row)
        if url and video_id in url:
            return row
    return None


def process_transcript(
    file_path: Path,
    api_key: str,
    model: str = DEFAULT_MODEL,
    max_words: int = DEFAULT_MAX_WORDS,
    delay: float = DEFAULT_DELAY,
    force: bool = False,
    dry_run: bool = False,
) -> SummarizeResult:
    """
    Process a single transcript file.
    
    Args:
        file_path: Path to transcript file
        api_key: OpenRouter API key
        model: Model identifier
        max_words: Target word count
        delay: Delay after processing (for rate limiting)
        force: Force re-summarization even if summary exists
        dry_run: If True, don't make changes
    
    Returns:
        SummarizeResult with status
    """
    video_id = extract_video_id_from_filename(file_path.name)
    
    # Check if already has summary
    if not force and has_summary(file_path):
        return SummarizeResult(
            video_id=video_id,
            success=True,
            error_message="skipped (already has summary)",
        )
    
    if dry_run:
        return SummarizeResult(
            video_id=video_id,
            success=True,
            error_message="dry-run (would process)",
        )
    
    # Parse file content before try block so variables are available in except
    try:
        content = file_path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(content)
    except Exception as read_error:
        return SummarizeResult(
            video_id=video_id,
            success=False,
            error_message=f"failed to read file: {read_error}",
        )

    if not body.strip():
        return SummarizeResult(
            video_id=video_id,
            success=False,
            error_message="empty transcript",
        )

    title = frontmatter.get("title", "Unknown Title")
    author = frontmatter.get("author", "Unknown")

    try:
        # Call API
        summary = summarize_transcript(
            content=body,
            title=title,
            author=author,
            api_key=api_key,
            model=model,
            max_words=max_words,
        )
        
        # Update file
        update_frontmatter_with_summary(file_path, summary)
        
        # Rate limiting delay
        if delay > 0:
            time.sleep(delay)
        
        return SummarizeResult(
            video_id=video_id,
            success=True,
            summary=summary,
        )
        
    except requests.HTTPError as e:
        if e.response.status_code == 429:
            # Rate limited - wait and retry once
            logger.warning("Rate limited, waiting 60 seconds...")
            time.sleep(60)
            try:
                summary = summarize_transcript(
                    content=body,
                    title=title,
                    author=author,
                    api_key=api_key,
                    model=model,
                    max_words=max_words,
                )
                update_frontmatter_with_summary(file_path, summary)
                return SummarizeResult(video_id=video_id, success=True, summary=summary)
            except Exception as retry_error:
                return SummarizeResult(
                    video_id=video_id,
                    success=False,
                    error_message=f"retry failed: {retry_error}",
                )
        status = e.response.status_code
        if status == 404:
            detail = f"model '{model}' not found or not available to your key (HTTP 404)"
        elif status in (401, 403):
            detail = f"unauthorized: check your API key (HTTP {status})"
        else:
            detail = f"API error: HTTP {status}"
        return SummarizeResult(
            video_id=video_id,
            success=False,
            error_message=detail,
        )
    except Exception as e:
        return SummarizeResult(
            video_id=video_id,
            success=False,
            error_message=str(e),
        )


def process_folder(
    folder_path: Path,
    api_key: str,
    model: str = DEFAULT_MODEL,
    max_words: int = DEFAULT_MAX_WORDS,
    delay: float = DEFAULT_DELAY,
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> BatchSummarizeProgress:
    """
    Process all transcripts in a folder.
    
    Args:
        folder_path: Path to channel folder (e.g., data/OpenAI)
        api_key: OpenRouter API key
        model: Model identifier
        max_words: Target word count
        delay: Delay between requests
        force: Force re-summarization
        dry_run: Preview mode
        verbose: Enable verbose output
    
    Returns:
        BatchSummarizeProgress with results
    """
    transcripts_dir = folder_path / "transcripts"
    csv_path = folder_path / "videos.csv"
    
    if not transcripts_dir.exists():
        logger.warning(f"No transcripts directory: {transcripts_dir}")
        return BatchSummarizeProgress(total=0)
    
    # Get transcript files (sorted for deterministic order)
    transcript_files = sorted(transcripts_dir.glob("*.md"))
    
    if not transcript_files:
        logger.info(f"No transcript files in {transcripts_dir}")
        return BatchSummarizeProgress(total=0)
    
    # Load CSV for status updates
    rows: list[dict] = []
    fieldnames: list[str] = []
    if csv_path.exists():
        try:
            rows = read_video_urls(str(csv_path))
            fieldnames = list(rows[0].keys()) if rows else []
            # Ensure summary_done column exists
            if "summary_done" not in fieldnames:
                fieldnames.append("summary_done")
                for row in rows:
                    row["summary_done"] = ""
        except Exception as e:
            logger.warning(f"Could not read CSV: {e}")
    
    progress = BatchSummarizeProgress(total=len(transcript_files))
    
    for i, file_path in enumerate(transcript_files, 1):
        video_id = extract_video_id_from_filename(file_path.name)
        
        if verbose:
            logger.info(f"[{i}/{progress.total}] Processing: {video_id}")
        
        result = process_transcript(
            file_path=file_path,
            api_key=api_key,
            model=model,
            max_words=max_words,
            delay=delay,
            force=force,
            dry_run=dry_run,
        )
        
        progress.processed += 1
        
        if result.error_message and "skipped" in result.error_message:
            progress.skipped += 1
            if verbose:
                logger.info(f"  ⊘ {result.error_message}")
        elif result.success:
            progress.success += 1
            logger.info(f"[{i}/{progress.total}] ✓ Summarized: {video_id}")
            
            # Update CSV
            if rows and not dry_run:
                row = find_row_by_video_id(rows, video_id)
                if row:
                    row["summary_done"] = "success"
                    try:
                        update_csv_status(str(csv_path), rows, fieldnames)
                    except Exception as e:
                        logger.warning(f"Could not update CSV: {e}")
        else:
            progress.errors += 1
            logger.warning(f"[{i}/{progress.total}] ✗ Error: {video_id} - {result.error_message}")
            
            # Update CSV with error
            if rows and not dry_run:
                row = find_row_by_video_id(rows, video_id)
                if row:
                    row["summary_done"] = f"error: {result.error_message}"
                    try:
                        update_csv_status(str(csv_path), rows, fieldnames)
                    except Exception as e:
                        logger.warning(f"Could not update CSV: {e}")
    
    return progress


def get_data_folders(data_dir: Path) -> list[Path]:
    """
    Get all channel/collection folders in data directory.
    
    Args:
        data_dir: Path to data/ directory
    
    Returns:
        List of folder paths that have a transcripts/ subdirectory
    """
    folders = []
    for item in sorted(data_dir.iterdir()):
        if item.is_dir() and (item / "transcripts").exists():
            folders.append(item)
    return folders
