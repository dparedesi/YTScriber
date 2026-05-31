"""Tests for CLI UX improvements."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import yaml

from ytscriber import cli, paths


class DummyResult:
    def __init__(self, success: bool = True) -> None:
        self.success = success


def test_handle_download_single_video_defaults_collection(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"

    monkeypatch.setattr(cli, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: {"defaults": {"delay": 60, "languages": ["en"]}},
    )

    created: dict[str, cli.TranscriptDownloader] = {}

    class DummyDownloader:
        def __init__(self, languages=None, delay=0.0, output_dir=None):
            self.languages = languages
            self.delay = delay
            self.output_dir = output_dir
            self.calls: list[dict[str, str | None]] = []
            created["instance"] = self

        def download(self, video_id, video_url=None, output_file=None):
            self.calls.append(
                {
                    "video_id": video_id,
                    "video_url": video_url,
                    "output_file": output_file,
                }
            )
            return DummyResult()

    monkeypatch.setattr(cli, "TranscriptDownloader", DummyDownloader)

    args = Namespace(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        folder=None,
        csv=None,
        output=None,
        output_dir="outputs",
        languages=["en"],
        delay=60,
        verbose=False,
    )

    exit_code = cli.handle_download(args)

    expected_folder = data_dir / paths.DEFAULT_COLLECTION
    expected_csv = expected_folder / "videos.csv"
    expected_transcripts = expected_folder / "transcripts"

    assert exit_code == 0
    assert expected_csv.exists()
    assert expected_transcripts.exists()
    assert created["instance"].output_dir == str(expected_transcripts)
    assert created["instance"].calls[0]["video_id"] == "dQw4w9WgXcQ"

    csv_contents = expected_csv.read_text(encoding="utf-8")
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in csv_contents


def test_handle_add_defaults_collection(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    default_dir = data_dir / paths.DEFAULT_COLLECTION

    monkeypatch.setattr(cli, "get_default_collection_dir", lambda: default_dir)
    monkeypatch.setattr(cli, "get_data_dir", lambda: data_dir)

    args = Namespace(
        url="https://www.youtube.com/watch?v=abc123xyz45",
        folder=None,
        csv=None,
        verbose=False,
    )

    exit_code = cli.handle_add(args)

    csv_path = default_dir / "videos.csv"
    assert exit_code == 0
    assert csv_path.exists()
    assert "https://www.youtube.com/watch?v=abc123xyz45" in csv_path.read_text(
        encoding="utf-8"
    )


def test_handle_status_lists_folders(monkeypatch, tmp_path, capsys):
    data_dir = tmp_path / "data"
    config_dir = tmp_path / "config"
    data_dir.mkdir()
    config_dir.mkdir()

    folder_one = data_dir / "a16z"
    folder_two = data_dir / paths.DEFAULT_COLLECTION

    for folder, count in [(folder_one, 2), (folder_two, 1)]:
        transcripts_dir = folder / "transcripts"
        transcripts_dir.mkdir(parents=True)
        (folder / "videos.csv").write_text("url\n", encoding="utf-8")
        for idx in range(count):
            (transcripts_dir / f"2025-01-0{idx + 1}-video.md").write_text(
                "---\nvideo_id: test\n---\n",
                encoding="utf-8",
            )

    channels_file = data_dir / "channels.yaml"
    channels_file.write_text(
        yaml.safe_dump({"channels": [], "collections": []}, sort_keys=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(cli, "get_config_path", lambda: config_dir / "config.yaml")
    monkeypatch.setattr(cli, "get_channels_file", lambda: channels_file)

    exit_code = cli.handle_status(Namespace(verbose=False))
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Available folders:" in output
    assert "- a16z (2 transcripts)" in output
    assert f"- {paths.DEFAULT_COLLECTION} (1 transcripts)" in output
