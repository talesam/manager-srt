"""Detector de tipo de mídia (filme vs série)"""

import re
from pathlib import Path
from enum import Enum
from typing import Optional
from ..utils.helpers import extract_season_episode, extract_year, is_video_file, normalize_spaces

# Pre-compiled patterns for title extraction
_RE_TITLE_SXXEXX = re.compile(r"^(.+?)\s*[Ss]\d{1,2}[Ee]\d{1,2}")
_RE_TITLE_NxNN = re.compile(r"^(.+?)\s*\d{1,2}x\d{1,2}")
_RE_TITLE_BOOK_VOL = re.compile(
    r"^(.+?)\s*(?:Book|Volume|Vol|Part|Season|Temporada|Cap\.?|Ep\.?)\s*\d{1,2}",
    re.IGNORECASE,
)
_RE_TITLE_DASH_NUM = re.compile(
    r"^(.+?)\s-\s(?!(?:19|20)\d{2}(?!\d))\d{2,4}(?:v\d)?(?![\dpPkKiI])"
)
_RE_DIGITS = re.compile(r"(\d+)")


class MediaType(Enum):
    """Tipo de mídia"""
    MOVIE = "movie"
    TVSHOW = "tvshow"
    UNKNOWN = "unknown"


class MediaInfo:
    """Informações sobre um arquivo de mídia"""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.media_type = MediaType.UNKNOWN
        self.season: Optional[int] = None
        self.episode_start: Optional[int] = None
        self.episode_end: Optional[int] = None
        self.year: Optional[int] = None
        self.title: Optional[str] = None

        self._detect()

    def _detect(self):
        """Detecta o tipo de mídia e extrai informações"""
        if not is_video_file(self.file_path):
            return

        filename = self.file_path.stem

        # Try to extract TV show info
        se_info = extract_season_episode(filename)

        if se_info:
            # It's a TV show
            self.media_type = MediaType.TVSHOW
            self.season, self.episode_start, self.episode_end = se_info

            # Extract title (everything before the season/episode pattern)
            # Try S01E01 pattern
            match = _RE_TITLE_SXXEXX.search(filename)
            if match:
                self.title = match.group(1).strip()
            else:
                # Try 1x01 pattern
                match = _RE_TITLE_NxNN.search(filename)
                if match:
                    self.title = match.group(1).strip()
                else:
                    # Try Book/Volume/Part/Season pattern
                    match = _RE_TITLE_BOOK_VOL.search(filename)
                    if match:
                        self.title = match.group(1).strip()
                    else:
                        # Numeração absoluta de anime ("Título - 01 [tags]"):
                        # sem isso o título ficava sendo o nome inteiro do
                        # arquivo e a busca no TMDB casava com qualquer coisa.
                        match = _RE_TITLE_DASH_NUM.search(filename)
                        if match:
                            self.title = match.group(1).strip()
                        else:
                            # Fallback: use filename without extension
                            self.title = filename
        else:
            # Check if folder structure indicates a TV show
            parent_folder = self.file_path.parent.name.lower()

            if parent_folder.startswith('season') or parent_folder.startswith('temporada'):
                self.media_type = MediaType.TVSHOW
                # Try to extract season number from folder name
                match = _RE_DIGITS.search(parent_folder)
                if match:
                    self.season = int(match.group(1))
            else:
                # Probably a movie
                self.media_type = MediaType.MOVIE
                self.year = extract_year(filename)
                self.title = normalize_spaces(filename)
                if self.year:
                    self.title = re.sub(rf"\s*[\(\[]{self.year}[\)\]]\s*", " ", self.title).strip()

    def is_movie(self) -> bool:
        """Check if it's a movie"""
        return self.media_type == MediaType.MOVIE

    def is_tvshow(self) -> bool:
        """Check if it's a TV show"""
        return self.media_type == MediaType.TVSHOW

    def __repr__(self):
        if self.is_tvshow():
            season = f"S{self.season:02d}" if self.season is not None else "S??"
            episode = f"E{self.episode_start:02d}" if self.episode_start is not None else "E??"
            return f"MediaInfo({self.title} {season}{episode}, type={self.media_type.value})"
        else:
            return f"MediaInfo({self.title}, type={self.media_type.value})"


def detect_media_type(file_path: Path) -> MediaInfo:
    """
    Detect the media type of a file.

    Args:
        file_path: Path to the file

    Returns:
        MediaInfo with detected information
    """
    return MediaInfo(file_path)


def is_movie_folder(folder_path: Path) -> bool:
    """
    Check if a folder contains movies.

    Args:
        folder_path: Path to the folder

    Returns:
        True if it's a movie folder
    """
    # Check for "Season" subfolders or files with S01E01
    has_season_folders = any(
        d.name.lower().startswith(('season', 'temporada'))
        for d in folder_path.iterdir()
        if d.is_dir()
    )

    if has_season_folders:
        return False

    # Check video files
    video_files = [f for f in folder_path.glob('*') if is_video_file(f)]

    if not video_files:
        return True  # Empty folder, assume movie

    # Check if any file has a TV show pattern
    for video in video_files[:5]:  # Only check first 5 files
        if extract_season_episode(video.stem):
            return False

    return True


def is_tvshow_folder(folder_path: Path) -> bool:
    """
    Check if a folder contains TV shows.

    Args:
        folder_path: Path to the folder

    Returns:
        True if it's a TV show folder
    """
    return not is_movie_folder(folder_path)
