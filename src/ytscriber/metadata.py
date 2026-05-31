"""YouTube video metadata extraction."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

from ytscriber.logging_config import get_logger
from ytscriber.models import VideoMetadata

logger = get_logger("metadata")

# Try to import pytube for video metadata (optional)
try:
    from pytube import YouTube

    PYTUBE_AVAILABLE = True
except ImportError:
    PYTUBE_AVAILABLE = False
    logger.debug("pytube not available, metadata extraction will be limited")


def extract_metadata_from_html(yt: "YouTube") -> dict:
    """
    Extract video metadata from YouTube's initial HTML data.

    This avoids triggering API calls that might fail.

    Args:
        yt: pytube YouTube object

    Returns:
        Dictionary containing extracted metadata
    """
    metadata: dict = {}

    try:
        html = yt.watch_html

        # Look for ytInitialPlayerResponse (contains videoDetails)
        player_match = re.search(
            r"var ytInitialPlayerResponse = ({.*?});", html, re.DOTALL
        )
        if player_match:
            try:
                player = json.loads(player_match.group(1))
                if "videoDetails" in player:
                    vd = player["videoDetails"]

                    # Extract from videoDetails
                    if "title" in vd:
                        metadata["title"] = vd["title"]
                    if "author" in vd:
                        metadata["author"] = vd["author"]
                    if "lengthSeconds" in vd:
                        length_sec = int(vd["lengthSeconds"])
                        metadata["length_minutes"] = round(length_sec / 60, 2)
                    if "viewCount" in vd:
                        metadata["views"] = int(vd["viewCount"])
                    if "shortDescription" in vd:
                        desc = vd["shortDescription"].strip()
                        if len(desc) > 500:
                            desc = desc[:500] + "..."
                        metadata["description"] = desc
                    if "keywords" in vd:
                        keywords = vd["keywords"]
                        if isinstance(keywords, list):
                            metadata["keywords"] = ", ".join(keywords[:10])
            except json.JSONDecodeError:
                logger.debug("Failed to parse ytInitialPlayerResponse JSON")

        # Look for ytInitialData (for title/author if not found, and publish date)
        data_match = re.search(r"var ytInitialData = ({.*?});", html, re.DOTALL)
        if data_match:
            try:
                data = json.loads(data_match.group(1))
                _extract_from_initial_data(data, metadata)
            except json.JSONDecodeError:
                logger.debug("Failed to parse ytInitialData JSON")

    except Exception as e:
        logger.debug(f"HTML metadata extraction failed: {e}")

    return metadata


def _extract_from_initial_data(data: dict, metadata: dict) -> None:
    """
    Extract metadata from ytInitialData.

    Args:
        data: Parsed ytInitialData
        metadata: Dictionary to update with extracted data
    """
    # Extract title and author from UI if not already found
    if "title" not in metadata or "author" not in metadata:
        if "contents" in data and "twoColumnWatchNextResults" in data["contents"]:
            results = data["contents"]["twoColumnWatchNextResults"]
            if "results" in results and "results" in results["results"]:
                results2 = results["results"]["results"]

                for item in results2.get("contents", []):
                    # Extract title
                    if "title" not in metadata and "videoPrimaryInfoRenderer" in item:
                        vpi = item["videoPrimaryInfoRenderer"]
                        if "title" in vpi:
                            title_obj = vpi["title"]
                            if "runs" in title_obj:
                                metadata["title"] = "".join(
                                    [run.get("text", "") for run in title_obj["runs"]]
                                )

                    # Extract author/channel
                    if "author" not in metadata and "videoSecondaryInfoRenderer" in item:
                        vsi = item["videoSecondaryInfoRenderer"]
                        if "owner" in vsi and "videoOwnerRenderer" in vsi["owner"]:
                            owner = vsi["owner"]["videoOwnerRenderer"]
                            if "title" in owner and "runs" in owner["title"]:
                                metadata["author"] = "".join(
                                    [
                                        run.get("text", "")
                                        for run in owner["title"]["runs"]
                                    ]
                                )

    # Extract publish date from microformat
    if "published_date" not in metadata:
        if "microformat" in data and "playerMicroformatRenderer" in data["microformat"]:
            microformat = data["microformat"]["playerMicroformatRenderer"]
            if "publishDate" in microformat:
                try:
                    pd = datetime.fromisoformat(
                        microformat["publishDate"].replace("Z", "+00:00")
                    )
                    metadata["published_date"] = pd.strftime("%Y-%m-%d")
                except (ValueError, AttributeError):
                    pass


def fetch_video_metadata(video_id: str, video_url: Optional[str] = None) -> VideoMetadata:
    # One-time warning flag for metadata fetch failures
    fetch_video_metadata._warned = getattr(fetch_video_metadata, "_warned", False)
    """
    Fetch metadata for a YouTube video.

    Args:
        video_id: YouTube video ID
        video_url: Optional YouTube URL (constructed from ID if not provided)

    Returns:
        VideoMetadata object with available information
    """
    url = video_url or f"https://www.youtube.com/watch?v={video_id}"
    metadata_dict: dict = {}

    if PYTUBE_AVAILABLE:
        try:
            yt = YouTube(url)

            # Extract metadata from HTML (this avoids API calls that might fail)
            html_metadata = extract_metadata_from_html(yt)
            metadata_dict.update(html_metadata)

            # Try to get publish_date as fallback
            if "published_date" not in metadata_dict:
                try:
                    if yt.publish_date:
                        metadata_dict["published_date"] = yt.publish_date.strftime(
                            "%Y-%m-%d"
                        )
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"Failed to fetch metadata for {video_id}: {e}")
            if not fetch_video_metadata._warned:
                logger.warning(
                    "Metadata fetch failed (date prefixes may be missing). "
                    f"Cause: {type(e).__name__}: {e}"
                )
                fetch_video_metadata._warned = True

    return VideoMetadata(
        video_id=video_id,
        url=url,
        title=metadata_dict.get("title"),
        author=metadata_dict.get("author"),
        description=metadata_dict.get("description"),
        duration_minutes=metadata_dict.get("length_minutes"),
        view_count=metadata_dict.get("views"),
        published_date=metadata_dict.get("published_date"),
        keywords=metadata_dict.get("keywords"),
    )
