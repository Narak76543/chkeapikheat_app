"""
Download Task Model
Defines status enum and dataclass for download tasks.
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(Enum):
    QUEUED      = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    PAUSED      = "PAUSED"
    DONE        = "DONE"
    ERROR       = "ERROR"
    CANCELLED   = "CANCELLED"


@dataclass
class DownloadTask:
    url                : str
    destination_path   : str = ""
    id                 : str = field(default_factory=lambda: str(uuid.uuid4()))
    filename           : str = ""
    status             : TaskStatus = TaskStatus.QUEUED
    progress_percent   : float = 0.0
    speed_bytes_per_sec: float = 0.0
    downloaded_bytes   : int = 0
    total_bytes        : int = 0
    error_message      : str | None = None
    poster_url         : str = ""
    duration           : str = ""
    is_episodes        : bool = False
    single_ep_index    : int | None = None
    quality            : str = "1080p"
