"""Command-line interface for ytscriber."""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

from ytscriber import __version__
from ytscriber.auth import (
    delete_stored_key,
    mask_key,
    resolve_api_key,
    resolve_key_source,
    set_stored_key,
    validate_api_key,
    validate_model,
)
from ytscriber.batch import download_all_transcripts, download_from_csv, find_video_csv_files
from ytscriber.config import (
    default_config,
    get_config_path,
    load_config,
    parse_config_value,
    save_config,
    set_config_value,
)
from ytscriber.csv_handler import append_videos_to_csv, ensure_csv_columns
from ytscriber.downloader import TranscriptDownloader
from ytscriber.exceptions import (
    CSVError,
    ChannelExtractionError,
    IPBlockedError,
    InvalidURLError,
)
from ytscriber.extractor import ChannelExtractor
from ytscriber.init import ensure_initialized
from ytscriber.logging_config import get_logger, setup_logging
from ytscriber.models import BatchProgress
from ytscriber.paths import (
    DEFAULT_COLLECTION,
    get_channels_file,
    get_data_dir,
    get_default_collection_dir,
)
from ytscriber.summarizer import (
    DEFAULT_DELAY as SUMMARIZE_DEFAULT_DELAY,
    DEFAULT_MAX_WORDS as SUMMARIZE_DEFAULT_MAX_WORDS,
    DEFAULT_MODEL as SUMMARIZE_DEFAULT_MODEL,
    BatchSummarizeProgress,
    get_data_folders,
    process_folder,
)
from ytscriber.providers import (
    DEFAULT_PROVIDER,
    PROVIDERS,
    VALID_PROVIDERS,
)
from ytscriber.sync import sync_all_channels
from ytscriber.utils import ensure_videos_endpoint, extract_video_id, is_playlist_url

logger = get_logger("cli")


class _DefaultFromConfig:
    def __init__(self, display: Any) -> None:
        self.display = display

    def __str__(self) -> str:
        return str(self.display)

    def __repr__(self) -> str:
        return str(self.display)


def _default_from_config(display: Any) -> _DefaultFromConfig:
    return _DefaultFromConfig(display)


def _resolve_config_default(value: Any, fallback: Any) -> Any:
    return fallback if isinstance(value, _DefaultFromConfig) else value


def _apply_verbose_logging(verbose: bool) -> None:
    setup_logging(level=logging.DEBUG if verbose else logging.INFO)


def _confirm_low_delay(delay: float) -> None:
    if delay >= 30:
        return
    print("=" * 60)
    print("WARNING: Delay is set below 30 seconds.")
    print(f"You specified --delay {delay}, which is very aggressive.")
    print("YouTube may block your IP if you make requests too quickly.")
    print("")
    print("Recommendations:")
    print("- Use --delay 60 or higher (default)")
    print("- Consider using a VPN if downloading many transcripts")
    print("- Run overnight with: ytscriber download-all")
    print("=" * 60)
    response = input("Proceed at your own risk? (yes/no): ").strip().lower()
    if response != "yes":
        print("Aborted. Consider using --delay 60 (default) or higher.")
        sys.exit(0)


def _resolve_folder_paths(folder: str) -> tuple[Path, Path]:
    data_dir = get_data_dir()
    folder_dir = data_dir / folder
    return folder_dir / "videos.csv", folder_dir / "transcripts"


def _resolve_summarize_options(
    args: argparse.Namespace, config: dict[str, Any]
) -> dict[str, Any]:
    """Resolve summarize-during-download options.

    Summarization is opt-in via ``--summarize`` and never mandatory: if no
    API key can be resolved we warn and continue downloading without summaries.
    """
    if not getattr(args, "summarize", False):
        return {"summarize": False}

    summarization = config.get("summarization", {})
    provider = summarization.get("provider", DEFAULT_PROVIDER)
    pconf = PROVIDERS[provider]

    api_key = resolve_api_key(getattr(args, "api_key", None), provider=provider)
    if not api_key:
        logger.warning(
            f"--summarize requested but no {pconf.display_name} API key found; "
            "continuing with downloads only."
        )
        logger.warning("Set one up with: ytscriber auth login")
        return {"summarize": False}

    return {
        "summarize": True,
        "api_key": api_key,
        "summarize_model": summarization.get("model", pconf.default_model),
        "summarize_max_words": summarization.get("max_words", SUMMARIZE_DEFAULT_MAX_WORDS),
        "summarize_provider": provider,
    }



def _ensure_csv_file(csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists():
        return

    fieldnames = ensure_csv_columns([])
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()


def _print_batch_summary(progress: BatchProgress, label: str = "Batch") -> None:
    print("=" * 60)
    print(f"{label} Complete")
    print(f"  Success: {progress.success}")
    print(f"  Skipped: {progress.skipped}")
    print(f"  Errors: {progress.errors}")
    print(f"  Total: {progress.total}")
    print("=" * 60)


def _register_channel(csv_path: Path, channel_url: str, count: int) -> None:
    folder_name = csv_path.parent.name
    if not folder_name:
        logger.warning("Could not determine folder name from CSV path.")
        return

    channel_url = ensure_videos_endpoint(channel_url)
    channels_file = get_channels_file()
    channels_data: dict[str, Any] = {"channels": [], "collections": []}

    if channels_file.exists():
        try:
            existing = yaml.safe_load(channels_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Could not read channels.yaml: {e}")
            existing = None

        if isinstance(existing, dict):
            channels_data["channels"] = existing.get("channels", []) or []
            channels_data["collections"] = existing.get("collections", []) or []
        elif isinstance(existing, list):
            channels_data["channels"] = existing

    for channel in channels_data["channels"]:
        if channel.get("folder") == folder_name:
            logger.info(f"Channel '{folder_name}' already registered.")
            return
        if channel.get("url") == channel_url:
            logger.info("Channel URL already registered.")
            return

    channels_data["channels"].append(
        {
            "folder": folder_name,
            "url": channel_url,
            "count": count,
            "enabled": True,
        }
    )

    try:
        channels_file.write_text(
            yaml.safe_dump(channels_data, sort_keys=False),
            encoding="utf-8",
        )
        logger.info(f"Registered channel '{folder_name}' in {channels_file}")
    except Exception as e:
        logger.error(f"Could not write channels.yaml: {e}")


def handle_download(args: argparse.Namespace) -> int:
    _apply_verbose_logging(args.verbose)

    config = load_config()
    defaults = config.get("defaults", {})
    delay = _resolve_config_default(args.delay, defaults.get("delay", 60))
    languages = _resolve_config_default(
        args.languages,
        defaults.get("languages", ["en", "en-US", "en-GB"]),
    )

    if args.url:
        if args.csv:
            logger.error("Use --csv without a URL for batch downloads.")
            return 1
        if args.output_dir and args.output_dir != "outputs":
            logger.error("Use --output-dir without a URL for batch downloads.")
            return 1

        folder = args.folder or DEFAULT_COLLECTION
        if not args.folder:
            logger.info(f"Using default collection: {DEFAULT_COLLECTION}")

        csv_path, output_dir = _resolve_folder_paths(folder)
        output_dir.mkdir(parents=True, exist_ok=True)
        _ensure_csv_file(csv_path)

        try:
            video_id = extract_video_id(args.url)
        except InvalidURLError:
            logger.error(f"Invalid YouTube URL: {args.url}")
            return 1

        from ytscriber.models import VideoMetadata

        video = VideoMetadata(
            video_id=video_id,
            url=f"https://www.youtube.com/watch?v={video_id}",
        )

        try:
            added = append_videos_to_csv(str(csv_path), [video])
            if added > 0:
                logger.info(f"Added video {video_id} to {csv_path}")
            else:
                logger.info(f"Video {video_id} already exists in {csv_path}")
        except CSVError as e:
            logger.error(str(e))
            return 1

        downloader = TranscriptDownloader(
            languages=languages,
            delay=0,
            output_dir=str(output_dir),
        )

        try:
            result = downloader.download(
                video_id=video_id,
                video_url=args.url,
                output_file=args.output,
            )
            return 0 if result.success else 1
        except IPBlockedError as e:
            logger.error(f"IP blocked by YouTube: {e}")
            return 2

    if args.folder:
        if args.csv or (args.output_dir and args.output_dir != "outputs"):
            logger.error("Use --folder without --csv/--output-dir for shorthand paths.")
            return 1
        csv_path, output_dir = _resolve_folder_paths(args.folder)
        if not csv_path.exists():
            logger.error(f"No videos.csv found in {csv_path.parent}")
            logger.error(
                f"First run: ytscriber extract <channel-url> --folder {args.folder}"
            )
            return 1
        args.csv = str(csv_path)
        args.output_dir = str(output_dir)

    output_dir = Path(args.output_dir) if args.output_dir else Path("outputs")

    if args.csv:
        _confirm_low_delay(delay)
        summarize_opts = _resolve_summarize_options(args, config)
        try:
            progress = download_from_csv(
                csv_path=Path(args.csv),
                output_dir=output_dir,
                languages=languages,
                delay=delay,
                **summarize_opts,
            )
        except IPBlockedError:
            logger.error("IP blocked by YouTube. Stopping.")
            return 2

        _print_batch_summary(progress)
        return 0

    logger.error("Provide a video URL, or use --csv/--folder for batch downloads.")
    return 1


def handle_extract(args: argparse.Namespace) -> int:
    _apply_verbose_logging(args.verbose)

    if not is_playlist_url(args.channel_url):
        try:
            extract_video_id(args.channel_url)
        except InvalidURLError:
            pass
        else:
            logger.error("Error: This looks like a video URL, not a channel URL.")
            logger.error(
                "To add a single video, use: ytscriber add <url> --folder <name>"
            )
            return 1

    if args.folder:
        if args.append_csv:
            logger.error("Use --folder without --append-csv for shorthand paths.")
            return 1
        args.append_csv = str(get_data_dir() / args.folder / "videos.csv")

    extractor = ChannelExtractor()

    try:
        videos = extractor.extract_videos(args.channel_url, max_videos=args.count)
    except ChannelExtractionError as e:
        logger.error(str(e))
        return 1

    if not videos:
        logger.error("No videos found.")
        return 1

    if args.append_csv:
        Path(args.append_csv).parent.mkdir(parents=True, exist_ok=True)
        try:
            append_videos_to_csv(args.append_csv, videos)
        except CSVError as e:
            logger.error(str(e))
            return 1

        if args.register_channel:
            if is_playlist_url(args.channel_url):
                logger.info(
                    "Skipping channel registration: playlist URLs are not "
                    "tracked in channels.yaml (re-run extract to refresh)."
                )
            else:
                _register_channel(Path(args.append_csv), args.channel_url, args.count)
    elif args.output:
        try:
            output_path = Path(args.output)
            output_path.write_text(
                "\n".join([video.video_id for video in videos]) + "\n",
                encoding="utf-8",
            )
            logger.info(f"Video IDs saved to: {args.output}")
        except Exception as e:
            logger.error(f"Error writing to file: {e}")
            return 1
    else:
        for video in videos:
            print(video.video_id)

    return 0


def handle_add(args: argparse.Namespace) -> int:
    _apply_verbose_logging(args.verbose)

    if not args.folder and not args.csv:
        args.csv = str(get_default_collection_dir() / "videos.csv")
        logger.info(f"Using default collection: {DEFAULT_COLLECTION}")

    if args.folder:
        if args.csv:
            logger.error("Use --folder without --csv for shorthand paths.")
            return 1
        args.csv = str(get_data_dir() / args.folder / "videos.csv")

    if not args.csv:
        logger.error("--csv or --folder is required.")
        logger.error("Example: ytscriber add <url> --folder my-collection")
        return 1

    try:
        video_id = extract_video_id(args.url)
    except InvalidURLError:
        logger.error(f"Invalid YouTube URL: {args.url}")
        return 1

    from ytscriber.models import VideoMetadata

    video = VideoMetadata(
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
    )

    csv_path = Path(args.csv)
    _ensure_csv_file(csv_path)

    try:
        added = append_videos_to_csv(args.csv, [video])
        if added > 0:
            logger.info(f"Added video {video_id} to {args.csv}")
        else:
            logger.info(f"Video {video_id} already exists in {args.csv}")
    except CSVError as e:
        logger.error(str(e))
        return 1

    return 0


def handle_summarize(args: argparse.Namespace) -> int:
    _apply_verbose_logging(args.verbose)

    if not args.folder and not args.all:
        logger.error("Provide a folder or use --all.")
        return 1

    config = load_config()
    summarization = config.get("summarization", {})
    provider = summarization.get("provider", DEFAULT_PROVIDER)

    api_key = resolve_api_key(provider=provider)
    if not api_key:
        pconf = PROVIDERS[provider]
        logger.error(f"Error: no {pconf.display_name} API key found.")
        logger.error("Set one up with: ytscriber auth login")
        return 1

    model = _resolve_config_default(
        args.model,
        summarization.get("model", SUMMARIZE_DEFAULT_MODEL),
    )
    max_words = _resolve_config_default(
        args.max_words,
        summarization.get("max_words", SUMMARIZE_DEFAULT_MAX_WORDS),
    )
    delay = _resolve_config_default(args.delay, SUMMARIZE_DEFAULT_DELAY)

    data_dir = get_data_dir()
    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        return 1

    if args.all:
        folders = get_data_folders(data_dir)
        if not folders:
            logger.error("No folders with transcripts found")
            return 1
    else:
        folder_path = data_dir / args.folder
        if not folder_path.exists():
            logger.error(f"Folder not found: {folder_path}")
            return 1
        folders = [folder_path]

    total_progress = BatchSummarizeProgress(total=0)

    for folder in folders:
        progress = process_folder(
            folder_path=folder,
            api_key=api_key,
            model=model,
            max_words=max_words,
            delay=delay,
            force=args.force,
            dry_run=args.dry_run,
            verbose=args.verbose,
            provider=provider,
        )

        total_progress.total += progress.total
        total_progress.processed += progress.processed
        total_progress.success += progress.success
        total_progress.skipped += progress.skipped
        total_progress.errors += progress.errors

    print("=" * 60)
    print("Summarization Complete")
    print(f"  Success: {total_progress.success}")
    print(f"  Skipped: {total_progress.skipped}")
    print(f"  Errors: {total_progress.errors}")
    print(f"  Total: {total_progress.total}")
    print("=" * 60)

    return 0


def handle_sync_all(args: argparse.Namespace) -> int:
    _apply_verbose_logging(args.verbose)

    channels_file = get_channels_file()
    data_dir = get_data_dir()

    try:
        progress = sync_all_channels(
            channels_file=channels_file,
            data_dir=data_dir,
            delay=args.delay,
            quiet=args.quiet,
        )
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1

    print("=" * 60)
    print("Sync Complete")
    print(f"  Success: {progress.success}")
    print(f"  Skipped: {progress.skipped}")
    print(f"  Errors: {progress.errors}")
    print(f"  Total: {progress.total}")
    print("=" * 60)

    return 0


def handle_download_all(args: argparse.Namespace) -> int:
    _apply_verbose_logging(args.verbose)

    config = load_config()
    defaults = config.get("defaults", {})
    delay = _resolve_config_default(args.delay, defaults.get("delay", 60))
    languages = _resolve_config_default(
        args.languages,
        defaults.get("languages", ["en", "en-US", "en-GB"]),
    )

    _confirm_low_delay(delay)

    summarize_opts = _resolve_summarize_options(args, config)
    try:
        progress = download_all_transcripts(
            data_dir=get_data_dir(),
            delay=delay,
            languages=languages,
            **summarize_opts,
        )
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1
    except IPBlockedError:
        logger.error("IP blocked by YouTube. Stopping.")
        return 2

    _print_batch_summary(progress, label="Download All")
    return 0


def handle_config(args: argparse.Namespace) -> int:
    _apply_verbose_logging(args.verbose)

    config = load_config()

    if args.reset:
        config = default_config()
        save_config(config)

    if args.set:
        for item in args.set:
            if "=" not in item:
                logger.error(f"Invalid --set value: {item}. Use key=value.")
                return 1
            key, value = item.split("=", 1)
            set_config_value(config, key.strip(), parse_config_value(value.strip()))
        save_config(config)

    if args.path_only:
        print(str(get_config_path()))
        return 0

    print(str(get_config_path()))
    print(yaml.safe_dump(config, sort_keys=False).rstrip())
    return 0


def handle_status(args: argparse.Namespace) -> int:
    _apply_verbose_logging(args.verbose)

    data_dir = get_data_dir()
    config_path = get_config_path()
    channels_file = get_channels_file()

    channels_count = 0
    collections_count = 0
    if channels_file.exists():
        try:
            data = yaml.safe_load(channels_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                channels_count = len(data.get("channels", []) or [])
                collections_count = len(data.get("collections", []) or [])
            elif isinstance(data, list):
                channels_count = len(data)
        except Exception as e:
            logger.warning(f"Could not read channels file: {e}")

    csv_files = find_video_csv_files(data_dir)
    transcript_count = 0
    folder_counts: list[tuple[str, int]] = []
    for csv_file in csv_files:
        transcripts_dir = csv_file.parent / "transcripts"
        count = len(list(transcripts_dir.glob("*.md"))) if transcripts_dir.exists() else 0
        transcript_count += count
        folder_counts.append((csv_file.parent.name, count))

    print("=" * 60)
    print("YTScriber Status")
    print(f"Data dir: {data_dir}")
    print(f"Config: {config_path}")
    print(f"Channels configured: {channels_count}")
    print(f"Collections configured: {collections_count}")
    print(f"Folders with videos.csv: {len(csv_files)}")
    print(f"Transcripts found: {transcript_count}")
    if folder_counts:
        print("Available folders:")
        for folder_name, count in folder_counts:
            print(f"  - {folder_name} ({count} transcripts)")
    else:
        print("Available folders: none")
    print("=" * 60)
    return 0


def handle_auth(args: argparse.Namespace) -> int:
    _apply_verbose_logging(getattr(args, "verbose", False))

    action = getattr(args, "auth_command", None)

    if action == "login":
        import getpass

        config = load_config()
        summarization = config.get("summarization", {})
        current_provider = summarization.get("provider", DEFAULT_PROVIDER)
        current_model = summarization.get("model", "")

        # Show current config
        pconf = PROVIDERS.get(current_provider)
        if pconf:
            print(f"Current provider: {pconf.display_name} (model: {current_model})")

        # Prompt for provider
        try:
            provider_input = input(
                f"Provider [{'/'.join(VALID_PROVIDERS)}] (default: {current_provider}): "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            logger.error("Aborted.")
            return 1
        provider = provider_input if provider_input in VALID_PROVIDERS else current_provider
        pconf = PROVIDERS[provider]

        # Check for existing key
        existing, source = resolve_key_source(provider=provider)
        if existing and source != "none":
            logger.info(f"An API key is already configured for {pconf.display_name} (from {source}).")

        # Prompt for API key
        try:
            api_key = getpass.getpass(f"Enter your {pconf.display_name} API key: ").strip()
            default_model = current_model or pconf.default_model
            model_prompt = (
                f"Summarization model [{default_model}]: "
                if default_model
                else "Summarization model: "
            )
            model = input(model_prompt).strip() or default_model
        except (EOFError, KeyboardInterrupt):
            print()
            logger.error("Aborted.")
            return 1
        if not api_key:
            logger.error("No key entered.")
            return 1
        if not model:
            logger.error("No model entered.")
            return 1

        # Validate key
        print(f"Validating key with {pconf.display_name}...")
        is_valid, message = validate_api_key(api_key, provider=provider)
        if not is_valid:
            logger.error(f"Key not saved: {message}.")
            if provider == "openrouter":
                logger.error("Double-check your key at https://openrouter.ai/keys")
            else:
                logger.error("Double-check your key at https://z.ai")
            return 1

        # Validate model
        print(f"Testing model '{model}'...")
        model_ok, model_msg = validate_model(api_key, model, provider=provider)
        if not model_ok:
            logger.error(f"Nothing saved: {model_msg}.")
            if provider == "openrouter":
                logger.error("Browse available models at https://openrouter.ai/models")
            else:
                logger.error("Check available models in your Z.AI dashboard")
            return 1

        # Save
        if not set_stored_key(api_key, provider=provider):
            logger.error("Could not save key to the OS keychain.")
            return 1
        set_config_value(config, "summarization.provider", provider)
        set_config_value(config, "summarization.model", model)
        save_config(config)
        print(
            f"Validated and saved {pconf.display_name} API key ({mask_key(api_key)}) "
            f"and model '{model}'."
        )
        return 0

    if action == "status":
        config = load_config()
        provider = config.get("summarization", {}).get("provider", DEFAULT_PROVIDER)
        pconf = PROVIDERS.get(provider, PROVIDERS[DEFAULT_PROVIDER])
        print(f"Provider: {pconf.display_name}")

        key, source = resolve_key_source(provider=provider)
        if key:
            labels = {
                "flag": "command-line flag",
                "env": f"{pconf.env_var} environment variable / .env",
                "keychain": "OS keychain",
            }
            print(f"API key found ({mask_key(key)}) via {labels.get(source, source)}.")
            return 0
        print("No API key configured.")
        print("Set one up with: ytscriber auth login")
        return 1

    if action == "logout":
        config = load_config()
        provider = config.get("summarization", {}).get("provider", DEFAULT_PROVIDER)
        pconf = PROVIDERS.get(provider, PROVIDERS[DEFAULT_PROVIDER])
        if delete_stored_key(provider=provider):
            print(f"Removed {pconf.display_name} API key from keychain.")
        else:
            print("No API key was stored in the keychain.")
        return 0

    logger.error("Unknown auth command. Use: login, status, or logout.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytscriber",
        description="Download and manage YouTube transcripts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Quick start:\n"
            "  ytscriber download <url>     Download a single video transcript\n"
            "  ytscriber status             Show available folders\n"
            "\n"
            "Environment variables:\n"
            "  ZAI_API_KEY          Z.AI API key for summaries (default provider)\n"
            "  OPENROUTER_API_KEY   OpenRouter API key (alternative provider)\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser(
        "download",
        help="Download transcripts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Single video (saves to ~/Documents/YTScriber/ad-hoc-downloads/)\n"
            "  ytscriber download https://youtube.com/watch?v=VIDEO_ID\n"
            "\n"
            "  # Single video to specific folder\n"
            "  ytscriber download https://youtube.com/watch?v=VIDEO_ID --folder my-collection\n"
            "\n"
            "  # Batch download from folder\n"
            "  ytscriber download --folder my-channel\n"
            "\n"
            "Rate limiting:\n"
            "  YouTube may block IPs making too many requests.\n"
            "  Default delay of 60s is safe for most use cases.\n"
            "  For large batches, consider running overnight.\n"
        ),
    )
    download_parser.add_argument("url", nargs="?", help="YouTube video URL")
    download_parser.add_argument(
        "--csv",
        metavar="FILE",
        help="CSV file with video URLs",
    )
    download_parser.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        help="Output file for single video",
    )
    download_parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default="outputs",
        help="Output directory for batch mode (default: %(default)s)",
    )
    download_parser.add_argument(
        "--folder",
        help="Folder under data dir (shorthand for CSV/output)",
    )
    download_parser.add_argument(
        "--languages",
        "-l",
        nargs="+",
        metavar="LANG",
        default=_default_from_config("en en-US en-GB"),
        help="Transcript languages to try (default: %(default)s)",
    )
    download_parser.add_argument(
        "--delay",
        type=float,
        metavar="SECONDS",
        default=_default_from_config(60),
        help="Seconds between requests (default: %(default)s)",
    )
    download_parser.add_argument(
        "--summarize",
        action="store_true",
        help="Summarize each transcript during the delay window (needs API key)",
    )
    download_parser.add_argument(
        "--api-key",
        metavar="KEY",
        help="API key (overrides env var and keychain)",
    )
    download_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )
    download_parser.set_defaults(func=handle_download)

    extract_parser = subparsers.add_parser(
        "extract",
        help="Extract videos from a channel or playlist",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ytscriber extract https://www.youtube.com/@OpenAI/videos --count 20 --folder OpenAI\n"
            "  ytscriber extract https://www.youtube.com/playlist?list=PLxxx --folder my-playlist\n"
            "  ytscriber extract https://www.youtube.com/@OpenAI/videos --count 20 --append-csv ~/videos.csv\n"
        ),
    )
    extract_parser.add_argument(
        "channel_url",
        help="YouTube channel URL or playlist URL (watch?v=...&list=... also accepted)",
    )
    extract_parser.add_argument(
        "--count",
        "-n",
        type=int,
        default=100,
        metavar="N",
        help="Number of videos to extract (default: %(default)s)",
    )
    extract_parser.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        help="Save video IDs to file",
    )
    extract_parser.add_argument(
        "--append-csv",
        metavar="FILE",
        help="Append videos to CSV",
    )
    extract_parser.add_argument(
        "--folder",
        help="Folder under data dir (shorthand for CSV)",
    )
    extract_parser.add_argument(
        "--register-channel",
        action="store_true",
        help="Add channel to channels.yaml for sync-all",
    )
    extract_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )
    extract_parser.set_defaults(func=handle_extract)

    add_parser = subparsers.add_parser(
        "add",
        help="Add a video to a collection CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ytscriber add https://youtube.com/watch?v=VIDEO_ID --folder random\n"
            "  ytscriber add https://youtube.com/watch?v=VIDEO_ID --csv ~/videos.csv\n"
        ),
    )
    add_parser.add_argument("url", help="YouTube video URL")
    add_parser.add_argument(
        "--csv",
        metavar="FILE",
        help="CSV file to add the video to",
    )
    add_parser.add_argument(
        "--folder",
        help="Folder under data dir (shorthand for CSV)",
    )
    add_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )
    add_parser.set_defaults(func=handle_add)

    summarize_parser = subparsers.add_parser(
        "summarize",
        help="Summarize transcripts with AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ytscriber summarize OpenAI\n"
            "  ytscriber summarize --all --dry-run\n"
        ),
    )
    summarize_parser.add_argument(
        "folder",
        nargs="?",
        help="Folder under data dir to process",
    )
    summarize_parser.add_argument(
        "--all",
        action="store_true",
        help="Process all folders (default: %(default)s)",
    )
    summarize_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without making changes",
    )
    summarize_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-process already completed items",
    )
    summarize_parser.add_argument(
        "--delay",
        type=float,
        metavar="SECONDS",
        default=_default_from_config(SUMMARIZE_DEFAULT_DELAY),
        help="Seconds between requests (default: %(default)s)",
    )
    summarize_parser.add_argument(
        "--model",
        default=_default_from_config(SUMMARIZE_DEFAULT_MODEL),
        help="Summarization model (default: %(default)s)",
    )
    summarize_parser.add_argument(
        "--max-words",
        type=int,
        metavar="N",
        default=_default_from_config(SUMMARIZE_DEFAULT_MAX_WORDS),
        help="Target summary length (default: %(default)s)",
    )
    summarize_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )
    summarize_parser.set_defaults(func=handle_summarize)

    sync_parser = subparsers.add_parser(
        "sync-all",
        help="Sync all channels from config",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ytscriber sync-all\n"
        ),
    )
    sync_parser.add_argument(
        "--delay",
        type=float,
        metavar="SECONDS",
        default=10.0,
        help="Seconds between channels (default: %(default)s)",
    )
    sync_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress non-error output",
    )
    sync_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )
    sync_parser.set_defaults(func=handle_sync_all)

    download_all_parser = subparsers.add_parser(
        "download-all",
        help="Download transcripts for all videos.csv files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ytscriber download-all\n"
            "\n"
            "Rate limiting:\n"
            "  YouTube may block IPs making too many requests.\n"
            "  Default delay of 60s is safe for most use cases.\n"
            "  For large batches, consider running overnight.\n"
        ),
    )
    download_all_parser.add_argument(
        "--delay",
        type=float,
        metavar="SECONDS",
        default=_default_from_config(60),
        help="Seconds between requests (default: %(default)s)",
    )
    download_all_parser.add_argument(
        "--languages",
        "-l",
        nargs="+",
        metavar="LANG",
        default=_default_from_config("en en-US en-GB"),
        help="Transcript languages to try (default: %(default)s)",
    )
    download_all_parser.add_argument(
        "--summarize",
        action="store_true",
        help="Summarize each transcript during the delay window (needs API key)",
    )
    download_all_parser.add_argument(
        "--api-key",
        metavar="KEY",
        help="API key (overrides env var and keychain)",
    )
    download_all_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )
    download_all_parser.set_defaults(func=handle_download_all)

    config_parser = subparsers.add_parser(
        "config",
        help="View or edit config",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ytscriber config\n"
            "  ytscriber config --set defaults.delay=90\n"
            "  ytscriber config --set summarization.model=provider/model\n"
        ),
    )
    config_parser.add_argument(
        "--set",
        action="append",
        metavar="KEY=VALUE",
        help="Set config value (e.g., defaults.delay=90)",
    )
    config_parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset config to defaults",
    )
    config_parser.add_argument(
        "--path-only",
        action="store_true",
        help="Print config path only",
    )
    config_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )
    config_parser.set_defaults(func=handle_config)

    status_parser = subparsers.add_parser(
        "status",
        help="Show status summary",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ytscriber status\n"
        ),
    )
    status_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )
    status_parser.set_defaults(func=handle_status)

    auth_parser = subparsers.add_parser(
        "auth",
        help="Manage API keys for summarization providers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ytscriber auth login     Store your key securely in the OS keychain\n"
            "  ytscriber auth status    Show where your key is resolved from\n"
            "  ytscriber auth logout    Remove the stored key\n"
        ),
    )
    auth_sub = auth_parser.add_subparsers(dest="auth_command", required=True)
    auth_login = auth_sub.add_parser("login", help="Store API key in the OS keychain")
    auth_login.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    auth_status = auth_sub.add_parser("status", help="Show resolved API key source")
    auth_status.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    auth_logout = auth_sub.add_parser("logout", help="Remove API key from the keychain")
    auth_logout.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    auth_parser.set_defaults(func=handle_auth)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    ensure_initialized()

    exit_code = args.func(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
