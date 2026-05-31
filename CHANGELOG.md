# Changelog

All notable changes to YTScriber will be documented in this file.

## [1.5.6] - 2026-05-31

### Fixed
- **Summary log messages no longer merge with the countdown line**: log handler now clears any active countdown/spinner before writing, so `✓ Summarized:` messages appear on their own line.

## [1.5.5] - 2026-05-31

### Changed
- **Rate-limit delay now runs after download + summary kickoff**, not before. This means transcripts download immediately, the LLM summary starts right away, and the 60s countdown overlaps the summarization — eliminating the perception of "waiting 60 seconds for nothing."
- Countdown message now says `⏳ Summarizing + rate-limit wait` when summarizing is active, making it clear two things are happening during the wait.

## [1.5.4] - 2026-05-31

### Added
- **Live progress during waits**: the rate-limit delay between downloads now shows a live countdown, transcript fetches show a spinner, and the end-of-run summary drain shows a "Generating summaries..." spinner. These render only on an interactive terminal and stay silent when output is piped to a log file.

## [1.5.3] - 2026-05-31

### Changed
- Default summarization model is now `nvidia/nemotron-3-super-120b-a12b:free` (free and high-quality), replacing `xiaomi/mimo-v2-flash:free`.

## [1.5.2] - 2026-05-31

### Changed
- `ytscriber auth login` now also prompts for the summarization model and validates it with a real (1-token) test request, so an unavailable model is caught at login instead of failing mid-download. The chosen model is saved to config.

## [1.5.1] - 2026-05-31

### Added
- **Login-time key validation**: `ytscriber auth login` now verifies the key against OpenRouter before saving it, so an invalid key is rejected immediately instead of failing deep in a download run.

### Changed
- Background summary worker now logs when a summary starts, giving visibility during the rate-limit window.
- Clearer summary error messages: a `404` now reports the unresolved model name, and `401/403` reports an unauthorized key, instead of a bare HTTP status.

## [1.5.0] - 2026-05-31

### Added
- **Summarize while downloading**: Pass `--summarize` to `download` or `download-all` to generate AI summaries during the rate-limit delay between downloads. The LLM call runs in a background worker so it overlaps the existing wait window, adding no extra time. Downloads are never blocked or slowed; any summaries still in flight are drained after the last download.
- **Secure key management with `auth` subcommands**: `ytscriber auth login` stores your OpenRouter key in the OS keychain (macOS Keychain, Windows Credential Manager, libsecret/KWallet). `auth status` shows where the key resolves from (masked), and `auth logout` removes it.
- **Layered credential resolution**: API key is resolved from `--api-key` flag → `OPENROUTER_API_KEY` env var → `.env` in the current directory → OS keychain. All layers are optional; summarization stays off if no key is found.
- New `--api-key` flag on `download` and `download-all`.

### Changed
- `summarize` now resolves the API key through the same layered resolver (keychain support), not just the environment variable.

### Notes
- Adds `keyring` and `python-dotenv` as dependencies.
- Summaries reuse the `summarization.max_words` config (default 500), shared with the standalone `summarize` command.

## [1.4.0] - 2026-05-10

### Added
- **Playlist support in `extract`**: Pass any playlist URL (`/playlist?list=...` or `watch?v=...&list=...`) to extract every video in the playlist. Channel URLs continue to work as before.
- New helpers `is_playlist_url` and `normalize_playlist_url` in `utils`.

### Changed
- `extract --count` default raised from 10 to 100 so playlists and small/medium channels pull everything by default.

### Notes
- `--register-channel` is skipped for playlist URLs (they are not tracked in `channels.yaml`); re-run `extract` to refresh a playlist folder.

## [1.2.2] - 2025-01-11

### Fixed
- Support for mobile YouTube URLs (`m.youtube.com`)

## [1.2.1] - 2025-01-11

### Fixed
- Version mismatch between pyproject.toml and __init__.py

## [1.2.0] - 2025-01-11

### Added
- **PyPI package**: Published as `ytscriber` on PyPI (`pip install ytscriber`).
- **Unified CLI**: Single `ytscriber <subcommand>` pattern replaces `transcript-*` commands.
- **Cross-platform paths**: Data/config directories via `platformdirs` (`~/Documents/YTScriber` on macOS/Windows, `~/ytscriber` on Linux).
- **New commands**: `sync-all`, `download-all`, `config`, and `status` subcommands.
- **Auto-initialization**: Creates config/data folders automatically on first run.
- **Improved --help**: All arguments now have help text, examples, and defaults shown.
- **Edge case handling**: Helpful errors for video URL to extract, missing folders, missing API key.
- **Rate limiting guidance**: VPN recommendations and overnight batch suggestions in warnings.

### Changed
- **CLI commands**: `transcript-extract` → `ytscriber extract`, `transcript-download` → `ytscriber download`, etc.
- **--folder shorthand**: Use `--folder name` instead of explicit CSV paths.
- **Configuration**: User settings stored in `~/.config/ytscriber/config.yaml`.
- **Documentation**: Comprehensive README and CLAUDE.md for new workflows.

## [1.1.0] - 2025-12-26

### Added
- **AI Summarization**: New `transcript-summarize` command to generate AI summaries for transcripts using OpenRouter.
- **Agent Skill**: `summarize-transcripts` skill to automate the summarization workflow securely.
- **Template**: Added `.env.example` for environment configuration.
- **Security**: Enhanced API key checks in documentation to prevent secret leakage in logs.
- New dependencies: `requests`, `python-dotenv`.

### Changed
- **Documentation**: Updated `README.md` and `AGENTS.md` to reflect new summarization capabilities.
- **Skills**: Updated all existing agent skills (`download`, `extract`, `consolidate`, `add-video`) for consistency and prompts.
- **Project Structure**: Refactored `.gitignore` to better handle data and environment files.

### Removed
- **Skill**: Removed `sync-agent-configs` skill as it is no longer required.
- **Prompts**: Removed standalone `prompts/` directory; moved prompt logic into `summarizer.py` and skills.

## [1.0.0] - 2025-12-25

### Added
- `transcript-extract` command to extract video metadata from YouTube channels
- `transcript-download` command to download transcripts with YAML frontmatter
- `transcript-add` command to manually add videos to collections
- Batch processing with resume capability via CSV tracking
- Rate limiting with automatic IP block detection
- Support for multiple extraction backends (yt-dlp, pytube)
- Consolidation script to merge transcripts for LLM analysis
- Comprehensive test suite
