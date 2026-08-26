#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# image_manager.py - Poster and backdrop downloading and caching
#

"""
Image downloading and caching for movie/TV show posters and backdrops.

This module handles downloading poster and backdrop images from TMDB
and caching them locally for faster access.

Usage:
    from core.image_manager import ImageManager

    img_manager = ImageManager()

    # Download poster
    poster_path = img_manager.download_poster(metadata, size='w342')

    # Download backdrop
    backdrop_path = img_manager.download_backdrop(metadata, size='w1280')

    # Get cached images
    cached = img_manager.get_cached_images(tmdb_id=550)
"""

from pathlib import Path
from typing import Optional, Dict
import requests

from ..utils.cache import CacheManager
from ..utils.logger import get_logger
from ..utils.i18n import _


class ImageManager:
    """Manages poster and backdrop downloading and caching"""

    # TMDB image sizes
    # https://developers.themoviedb.org/3/getting-started/images
    POSTER_SIZES = {
        'small': 'w185',
        'medium': 'w342',
        'large': 'w500',
        'original': 'original'
    }

    BACKDROP_SIZES = {
        'small': 'w300',
        'medium': 'w780',
        'large': 'w1280',
        'original': 'original'
    }

    # TMDB image base URL
    IMAGE_BASE_URL = "https://image.tmdb.org/t/p"

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize image manager.

        Args:
            cache_dir: Directory for image cache (default: ~/.jellyfix/cache)
        """
        self.logger = get_logger()
        self.cache = CacheManager(cache_dir)

    def _build_image_url(self, path: str, size: str) -> str:
        """
        Build full TMDB image URL.

        Args:
            path: Image path from TMDB (e.g., '/abc123.jpg')
            size: Image size (e.g., 'w500', 'original')

        Returns:
            Full URL to image
        """
        return f"{self.IMAGE_BASE_URL}/{size}{path}"

    def _download_image(self, url: str, cache_key: str) -> Optional[Path]:
        """
        Download image from URL and cache it.

        Args:
            url: Image URL
            cache_key: Key for caching

        Returns:
            Path to cached image, or None if download failed
        """
        try:
            self.logger.debug(f"Downloading image: {url}")

            # Sessão compartilhada: baixar vários posters seguidos (biblioteca
            # grande, "Baixar Legendas para Todos") reaproveita a conexão com o
            # CDN em vez de refazer o handshake TLS a cada imagem.
            from ..utils.config import get_config
            from ..utils.http import get_session

            session = get_session('tmdb-images', timeout=get_config().image_download_timeout)
            response = session.get(url)
            response.raise_for_status()

            # Save to cache
            local_path = self.cache.save(cache_key, response.content, ext='jpg')
            self.logger.debug(_("Downloaded image: %s") % local_path)

            return local_path

        except requests.RequestException as e:
            self.logger.error(_("Failed to download image: %s") % e)
            return None

        except Exception as e:
            self.logger.error(_("Unexpected error downloading image: %s") % e)
            return None

    def download_poster(self, metadata, size: str = 'medium') -> Optional[Path]:
        """
        Download movie/TV show poster and return local path.

        Args:
            metadata: Metadata object with poster_path and tmdb_id
            size: Poster size ('small', 'medium', 'large', 'original')

        Returns:
            Path to cached poster, or None if unavailable
        """
        # Check if metadata has poster_path
        if not hasattr(metadata, 'poster_path') or not metadata.poster_path:
            self.logger.debug("No poster_path in metadata")
            return None

        if not hasattr(metadata, 'tmdb_id') or not metadata.tmdb_id:
            self.logger.debug("No tmdb_id in metadata")
            return None

        # Map size to TMDB size code
        size_code = self.POSTER_SIZES.get(size, 'w342')

        # Generate cache key
        cache_key = f"poster_{metadata.tmdb_id}_{size_code}"

        # Check cache first
        cached_path = self.cache.get(cache_key)
        if cached_path:
            self.logger.debug(f"Using cached poster: {cached_path}")
            return Path(cached_path)

        # Download image
        url = self._build_image_url(metadata.poster_path, size_code)
        return self._download_image(url, cache_key)

    def download_backdrop(self, metadata, size: str = 'large') -> Optional[Path]:
        """
        Download movie/TV show backdrop and return local path.

        Args:
            metadata: Metadata object with backdrop_path and tmdb_id
            size: Backdrop size ('small', 'medium', 'large', 'original')

        Returns:
            Path to cached backdrop, or None if unavailable
        """
        # Check if metadata has backdrop_path
        if not hasattr(metadata, 'backdrop_path') or not metadata.backdrop_path:
            self.logger.debug("No backdrop_path in metadata")
            return None

        if not hasattr(metadata, 'tmdb_id') or not metadata.tmdb_id:
            self.logger.debug("No tmdb_id in metadata")
            return None

        # Map size to TMDB size code
        size_code = self.BACKDROP_SIZES.get(size, 'w1280')

        # Generate cache key
        cache_key = f"backdrop_{metadata.tmdb_id}_{size_code}"

        # Check cache first
        cached_path = self.cache.get(cache_key)
        if cached_path:
            self.logger.debug(f"Using cached backdrop: {cached_path}")
            return Path(cached_path)

        # Download image
        url = self._build_image_url(metadata.backdrop_path, size_code)
        return self._download_image(url, cache_key)

    def get_cached_images(self, tmdb_id: int) -> Dict[str, Optional[str]]:
        """
        Get all cached images for a TMDB ID.

        Args:
            tmdb_id: TMDB ID

        Returns:
            Dictionary with 'poster' and 'backdrop' paths (or None)
        """
        result = {
            'poster': None,
            'backdrop': None
        }

        # Check for poster (try medium size)
        poster_key = f"poster_{tmdb_id}_w342"
        poster_path = self.cache.get(poster_key)
        if poster_path:
            result['poster'] = poster_path

        # Check for backdrop (try large size)
        backdrop_key = f"backdrop_{tmdb_id}_w1280"
        backdrop_path = self.cache.get(backdrop_key)
        if backdrop_path:
            result['backdrop'] = backdrop_path

        return result

    def clear_cache(self):
        """Clear all cached images"""
        self.logger.info(_("Clearing image cache..."))
        self.cache.clear_all()
        self.logger.info(_("Image cache cleared"))

    def get_cache_stats(self) -> Dict:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        stats = self.cache.get_cache_stats()

        # Convert size to MB
        size_mb = stats['total_size'] / (1024 * 1024)

        return {
            'total_files': stats['total_files'],
            'total_size_mb': round(size_mb, 2),
            'oldest_entry': stats['oldest_entry']
        }
