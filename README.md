# YTScriber

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Download YouTube transcripts and manage channel archives with a unified CLI.

## Features

- 📹 **Extract videos** from any YouTube channel
- 📝 **Download transcripts** with metadata (title, author, duration, etc.)
- 🧠 **Summarize while downloading** — AI summaries run during the delay between downloads, adding no extra time
- 🔐 **Secure key storage** in the OS keychain via `ytscriber auth login`
- 📄 **Save as markdown** files with YAML frontmatter for easy processing
- 🔄 **Track progress** in CSV files to resume interrupted downloads
- **Cross-platform data directories** via `platformdirs`
- **Unified CLI** with subcommands (`ytscriber download`, `extract`, `sync-all`)

## Installation

### From PyPI

```bash
pip install ytscriber
```

### From source (recommended for development)

```bash
git clone https://github.com/dparedesi/YTScribe.git
cd YTScribe
pip install -e .
```

### Development installation

```bash
pip install -e ".[dev]"
```



## Quick Start

```bash
# Extract videos from a conference channel
ytscriber extract https://www.youtube.com/@AWSEventsChannel/videos \
  --count 100 \
  --folder aws-reinvent-2025 \
  --register-channel

# Download transcripts
ytscriber download --folder aws-reinvent-2025
```

## Usage

### Extract videos from a channel

```bash
ytscriber extract <channel_url> --count <number> --folder <folder>
```

**Examples:**

```bash
# AWS re:Invent 2025
ytscriber extract https://www.youtube.com/@AWSEventsChannel/videos \
  --count 100 \
  --folder aws-reinvent-2025 \
  --register-channel

# PyCon US
ytscriber extract https://www.youtube.com/@PyConUS \
  --count 50 \
  --folder pycon-2024 \
  --register-channel

# KubeCon
ytscriber extract https://www.youtube.com/@cncf/videos \
  --count 75 \
  --folder kubecon-2024 \
  --register-channel
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--count, -n` | Number of latest videos to extract | 10 |
| `--folder` | Folder under data dir (shorthand for CSV) | - |
| `--append-csv` | Create or append to CSV file | - |
| `--output, -o` | Save video IDs to text file | - |
| `--register-channel` | Add channel to channels.yaml | False |
| `--verbose, -v` | Enable verbose output | False |

### Download transcripts

```bash
ytscriber download --folder <folder>
```

**Examples:**

```bash
# Download transcripts for AWS re:Invent
ytscriber download --folder aws-reinvent-2025

# With faster processing (shorter delay)
ytscriber download --folder pycon-2024 --delay 30

# Download AND summarize each transcript during the delay window (no extra time)
ytscriber download --folder aws-reinvent-2025 --summarize
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--folder` | Folder under data dir (shorthand for CSV/output) | - |
| `--csv` | Input CSV file with video URLs | - |
| `--output-dir` | Directory for transcript files | outputs |
| `--delay` | Seconds between requests | 60 |
| `--languages, -l` | Language codes to try | en en-US en-GB |
| `--summarize` | Summarize each transcript during the delay window (needs API key) | False |
| `--api-key` | OpenRouter API key (overrides env var and keychain) | - |
| `--verbose, -v` | Enable verbose output | False |

> **Tip:** `--summarize` reuses the 60s rate-limit delay to run the AI summary in the background, so summaries come for free without slowing downloads. It also works on `download-all`. Requires an OpenRouter key (see [AI Summarization Setup](#ai-summarization-setup)).

**Single video mode:**

```bash
ytscriber download https://www.youtube.com/watch?v=VIDEO_ID --output transcript.md
```

### Add a video to a collection

```bash
ytscriber add <youtube_url> --folder <collection>
```

### Sync all channels

```bash
ytscriber sync-all
```

### Download all transcripts

```bash
ytscriber download-all

# Also generate summaries during the delay window
ytscriber download-all --summarize
```

### View or edit config

```bash
ytscriber config
ytscriber config --set defaults.delay=45
```

### Status

```bash
ytscriber status
```

## Output Format

### Transcript files (Markdown with YAML frontmatter)

Each transcript is saved as a Markdown file with rich metadata in the YAML frontmatter:

```markdown
---
video_id: i_cskqmWA3U
video_url: https://www.youtube.com/watch?v=i_cskqmWA3U
title: Personalize ChatGPT with custom instructions
author: OpenAI
published_date: 2025-05-12
length_minutes: 2.17
views: 60882
description: "With custom instructions, ChatGPT becomes more relevant..."
is_generated: True
is_translatable: True
---

You can find memory and custom instructions by clicking on your profile
in the top right, clicking on settings, and then personalization...
```

Files are named with the publish date for easy sorting: `2025-05-12-i_cskqmWA3U.md`

### AI Summarization Setup

To use the AI summarization features, you need an API key from [OpenRouter](https://openrouter.ai/).

**1. Get an API Key** — Sign up at OpenRouter and create a key.

**2. Provide the key** — YTScriber resolves it from the first available source:

1. `--api-key` flag (one-off / CI)
2. `OPENROUTER_API_KEY` environment variable
3. A `.env` file in the current directory
4. The OS keychain (recommended for everyday use)

The recommended, most secure option is to store it in your OS keychain:

```bash
ytscriber auth login     # prompts for key + model, validates both, stores securely
ytscriber auth status    # shows where the key is resolved from (masked)
ytscriber auth logout    # removes the stored key
```

`auth login` validates your key against OpenRouter and runs a tiny test request
against your chosen model, so a wrong key or an unavailable model is caught
immediately rather than failing mid-download.

Alternatively, use an environment variable or a `.env` file:

```bash
export OPENROUTER_API_KEY=sk-or-your-key-here
# or create a .env file containing:
# OPENROUTER_API_KEY=sk-or-your-key-here
```

**3. Recommended Model** — By default, the tool uses `nvidia/nemotron-3-super-120b-a12b:free`, which is free and high-quality. Change it with the `--model` flag or set a default with `ytscriber config --set summarization.model=...`.

### Summarize transcripts

You can summarize during download (`--summarize`, see above) or run summarization separately on already-downloaded transcripts:

```bash
ytscriber summarize <folder_name> [options]
```

**Examples:**

```bash
# Summarize random folder
ytscriber summarize random

# Summarize all folders
ytscriber summarize --all

# Dry run to preview changes
ytscriber summarize random --dry-run
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--all` | Process all folders | False |
| `--dry-run` | Preview changes without writing | False |
| `--force` | overwrite existing summaries | False |
| `--model` | OpenRouter model to use | `nvidia/nemotron-3-super-120b-a12b:free` |

### CSV tracking format

```csv
url,title,duration_minutes,view_count,description,transcript_downloaded,summary_done
https://youtube.com/watch?v=...,Talk Title,45.5,1234,Description...,success,
```

| Column | Description |
|--------|-------------|
| `transcript_downloaded` | Status: `success`, `error: <reason>`, or empty |
| `summary_done` | Track if you've processed the transcript |

## Project Structure

```
YTScribe/
├── src/
│   └── ytscriber/
│       ├── __init__.py          # Package exports
│       ├── cli.py               # Command-line interface
│       ├── downloader.py        # Transcript downloading
│       ├── extractor.py         # Channel video extraction
│       ├── csv_handler.py       # CSV operations
│       ├── metadata.py          # Video metadata extraction
│       ├── models.py            # Data models
│       ├── exceptions.py        # Custom exceptions
│       ├── logging_config.py    # Logging setup
│       └── utils.py             # Utility functions
├── scripts/                     # Automation scripts
├── tests/                       # Unit tests
├── prompts/                     # AI prompts for analysis
├── examples/                    # Example shell scripts
├── pyproject.toml               # Project configuration
└── README.md
```

## Data Organization

By default, data is stored in:

- macOS/Windows: `~/Documents/YTScriber`
- Linux: `~/ytscriber`

Example structure:

```
YTScriber/
├── aws-reinvent-2025/
│   ├── videos.csv
│   └── transcripts/
│       ├── 2025-12-03-abc123xyz.md
│       └── 2025-12-03-def456uvw.md
├── pycon-2024/
│   ├── videos.csv
│   └── transcripts/
└── kubecon-eu-2024/
    ├── videos.csv
    └── transcripts/
```

## Migration (1.x to 2.0)

If you used the old `transcript-*` commands and a repo-local `data/` folder:

1. Move your existing `data/` folder into the new data directory above.
2. Copy `channels.yaml` into the same data directory if you rely on sync-all.
3. Update commands:
   - `transcript-extract` -> `ytscriber extract`
   - `transcript-download` -> `ytscriber download`
   - `transcript-add` -> `ytscriber add`
   - `transcript-summarize` -> `ytscriber summarize`
4. Optionally set defaults with `ytscriber config --set defaults.delay=...`.

## Rate Limiting & Best Practices

YouTube may rate limit or block your IP if you make too many requests:

1. **Use reasonable delays**: Default 60 seconds between requests is safe
2. **Resume capability**: Script tracks progress in CSV, can resume after interruption
3. **Start small**: Test with 10-20 videos before large batches
4. **Respect limits**: If you get blocked, wait 30-60 minutes before retrying

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/dparedesi/YTScribe.git
cd YTScribe

# Install with development dependencies
pip install -e ".[dev]"

# Install pre-commit hooks (optional)
pre-commit install
```

### Running tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=ytscriber

# Run specific test file
pytest tests/test_utils.py
```

### Code quality

```bash
# Format code
black src tests

# Lint code
ruff check src tests

# Type checking
mypy src
```

## Programmatic Usage

```python
from ytscriber import TranscriptDownloader, ChannelExtractor

# Extract videos from a channel
extractor = ChannelExtractor()
videos = extractor.extract_videos(
    "https://www.youtube.com/@AWSEventsChannel/videos",
    max_videos=10
)

# Download transcripts
downloader = TranscriptDownloader(
    languages=["en", "en-US"],
    delay=30,
    output_dir="transcripts"
)

for video in videos:
    result = downloader.download(video.video_id, video.url)
    if result.success:
        print(f"Downloaded: {video.title}")
    else:
        print(f"Failed: {result.error_message}")
```

## Troubleshooting

### "No transcript found"

- Video may not have captions/transcripts available
- Try with different language codes: `--languages en en-US auto`

### "IP blocked" or rate limiting

- Wait 30-60 minutes before retrying
- Increase delay: `--delay 120`
- Use different network/IP if persistent

### "Could not extract metadata"

- Transcript will still download, just without extra metadata
- Check if video is accessible and not private

### Script interrupted

- Just run the same command again - it will skip already downloaded videos
- Progress is saved to CSV after each video

## Requirements

- Python 3.9+
- youtube-transcript-api
- yt-dlp
- pytube

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests and linting (`pytest && ruff check .`)
4. Commit your changes (`git commit -m 'Add amazing feature'`)
5. Push to the branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request
