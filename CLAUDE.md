# YTScriber - Project Guide

YouTube transcript downloader and organizer for conference channels, podcasts, and educational content.

## Quick Reference

```bash
# Install
pip install -e .

# Core commands
ytscriber extract <channel-url> --count 100 --folder <folder> --register-channel
ytscriber download --folder <folder> --delay 60
ytscriber add <video-url> --folder <folder>
ytscriber summarize <folder> --all
```

## Architecture

```
src/ytscriber/
├── cli.py           # Subcommand entry point
├── paths.py         # Data/config paths (platformdirs)
├── config.py        # Config load/save/merge
├── init.py          # Auto-initialization
├── sync.py          # sync-all implementation
├── batch.py         # download-all implementation
├── extractor.py     # ChannelExtractor - uses yt-dlp (primary) or pytube (fallback)
├── downloader.py    # TranscriptDownloader - uses youtube-transcript-api
├── summarizer.py    # AI summarization via provider APIs (Z.AI or OpenRouter)
├── providers.py     # Provider registry (endpoints, models, wire formats)
├── auth.py          # Credential resolution + provider API call helpers
├── csv_handler.py   # CSV read/write, progress tracking
├── metadata.py      # Video metadata fetching
├── models.py        # Dataclasses: VideoMetadata, TranscriptResult, BatchProgress
├── exceptions.py    # Custom exception hierarchy
└── utils.py         # URL parsing, YAML escaping utilities
```

## Data Organization

```
YTScriber/                      # macOS/Windows: ~/Documents/YTScriber
├── channels.yaml               # Channel registry (see below)
├── <channel-folder>/
│   ├── videos.csv              # Video tracking with download status
│   ├── transcripts/            # YYYY-MM-DD-<video_id>.md files
│   ├── <folder>-consolidated.md  # Merged transcripts (up to 800K tokens)
│   └── <folder>-summary.md     # AI-generated synthesis
└── <collection-folder>/        # Manual collections (library-of-minds, random)
```

Linux default data dir: `~/ytscriber`.

### Other Directories

- `scripts/` - Automation scripts for batch operations
- `prompts/` - AI prompts for transcript analysis
- `.agent/skills/` - Skill definitions for agents (create a `.claude` symlink if your IDE needs it)

### channels.yaml Structure

```yaml
channels:
  - folder: dwarkesh-patel
    url: https://www.youtube.com/@DwarkeshPatel/videos
    count: 20
    enabled: true

collections:
  - library-of-minds
  - random
```

### Transcript File Format

Markdown with YAML frontmatter:

```yaml
---
video_id: abc123XYZ00
video_url: https://www.youtube.com/watch?v=abc123XYZ00
title: Video Title
author: Channel Name
published_date: 2024-05-31
length_minutes: 26.47
views: 3606
description: "Video description..."
is_generated: True
summary: |
  AI-generated summary here...
---

[Transcript text as continuous paragraph]
```

### CSV Columns

`url`, `title`, `duration_minutes`, `view_count`, `description`, `published_date`, `transcript_downloaded`, `summary_done`

## Key Patterns

- **Rate limiting**: Default 60s delay between downloads to avoid IP blocks
- **Resume capability**: CSV tracks `transcript_downloaded` status (success/error/empty)
- **Fallback strategies**: yt-dlp primary, pytube fallback for extraction
- **Language priority**: en → en-US → en-GB → any available

## Environment Variables

```bash
ZAI_API_KEY=...                # Z.AI API key (default provider for summarization)
OPENROUTER_API_KEY=sk-or-...   # OpenRouter API key (alternative provider)
```

Default provider: **Z.AI** with model `GLM-5.1`. Switch with `ytscriber auth login` or `ytscriber config --set summarization.provider=openrouter`.

Provider architecture: `src/ytscriber/providers.py` defines `ProviderInfo` dataclass with endpoint, headers, and default model per provider. `auth.py` has `call_provider_api()` and `extract_response_text()` shared by both validation and summarizer. Wire formats: Z.AI uses Anthropic Messages API, OpenRouter uses OpenAI chat completions.

## Testing

```bash
pytest                           # Run all tests
pytest --cov=ytscriber  # With coverage
pytest tests/test_downloader.py  # Specific module
```

## Skills (.agent/skills/)

| Skill | Purpose |
|-------|---------|
| `extract-videos` | Extract video list from YouTube channel |
| `download-transcripts` | Download transcripts from CSV |
| `download-all-transcripts` | Batch download all channels overnight |
| `sync-all-channels` | Extract videos from all enabled channels |
| `summarize-transcripts` | Add AI summaries to transcripts |
| `consolidate-transcripts` | Merge transcripts for LLM context |
| `add-video-to-collection` | Add single video to collection |

## Workflow

1. **Extract**: `ytscriber extract` or `ytscriber sync-all` → `videos.csv`
2. **Download**: `ytscriber download` or `ytscriber download-all` → `transcripts/*.md`
3. **Summarize**: `ytscriber summarize` → adds `summary` to frontmatter
4. **Consolidate**: `consolidate-transcripts` → `*-consolidated.md`

Consolidate command (newest first, up to 800K tokens by default):

```bash
python scripts/consolidate_transcripts.py <channel_name> [--limit TOKENS] [--verbose]
```

## Common Tasks

### Add a new channel
```bash
ytscriber extract "https://www.youtube.com/@ChannelName/videos" \
  --count 50 \
  --folder channel-name \
  --register-channel
```

### Overnight batch run
```bash
ytscriber sync-all && ytscriber download-all
```

### Add single video to collection
```bash
ytscriber add "https://www.youtube.com/watch?v=VIDEO_ID" \
  --folder random
```

## Gotchas

- Delay < 30s triggers safety warning (YouTube rate limiting)
- Video IDs are 11 chars; channel IDs start with "UC" (filtered out)
- Descriptions truncated to 500 chars in CSV
- Token counting uses tiktoken for accurate LLM context limits

### macOS SSL certificate error (pytube)

Python installed from python.org on macOS doesn't include root CA certificates. This causes pytube (used for video metadata) to fail with `SSLCertVerificationError`. When this happens, transcript filenames lose their `YYYY-MM-DD-` date prefix and are saved as `{video_id}.md`.

**Symptom**: `INFO: ✓ Saved transcript to: .../transcripts/V-L0INGTEOg.md` (no date prefix)

**Fix**: Run the certificate installer that comes with Python:
```bash
"/Applications/Python 3.13/Install Certificates.command"
```
Adjust the path for your Python version (`3.12`, `3.14`, etc.).

**Fallback** (v1.7.0+): Even without SSL certs, the downloader uses the CSV row's `published_date` as a fallback for the filename. So the date prefix is preserved as long as the video was extracted with yt-dlp (which provides `upload_date` in channel listings).
