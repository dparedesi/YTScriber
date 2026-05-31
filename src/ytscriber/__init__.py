"""
YTScriber.

Download YouTube transcripts and organize them for analysis, summarization,
and archival.
"""

__version__ = "1.7.0"
__author__ = "Daniel Paredes"

from ytscriber.downloader import TranscriptDownloader
from ytscriber.extractor import ChannelExtractor
from ytscriber.models import VideoMetadata, TranscriptResult

__all__ = [
    "TranscriptDownloader",
    "ChannelExtractor",
    "VideoMetadata",
    "TranscriptResult",
    "__version__",
]
