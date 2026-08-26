#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# utils/http.py - Shared HTTP sessions with keep-alive and default timeout
#

"""
Shared requests.Session objects.

Two reasons this exists instead of calling ``requests.get`` directly:

1. **Keep-alive.** A bare ``requests.get`` opens a new TCP + TLS connection on
   every call. Against api.themoviedb.org the handshake costs ~0.35s, so a
   request that takes 0.17s on a warm connection takes ~0.53s on a cold one —
   about 3x slower for every metadata lookup and every poster download.

2. **Default timeout.** ``requests`` has no timeout by default, so a stalled
   server hangs the calling thread forever. In the GUI that meant a poster
   that never appeared, with no error to explain it.
"""

import threading
from typing import Dict, Optional

import requests

# Sessions are created lazily and shared per (host-group, timeout) pair.
_sessions: Dict[tuple, "TimeoutSession"] = {}
_lock = threading.Lock()

DEFAULT_TIMEOUT = 15


class TimeoutSession(requests.Session):
    """Session that applies a default timeout to every request."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        super().__init__()
        self.timeout = timeout

    def request(self, *args, **kwargs):  # type: ignore[override]
        kwargs.setdefault("timeout", self.timeout)
        return super().request(*args, **kwargs)


def get_session(name: str, timeout: Optional[int] = None) -> TimeoutSession:
    """
    Return a shared session for a logical group of requests.

    Args:
        name: Group name ('tmdb-api', 'tmdb-images', ...). Requests to the same
            host should share a name so the connection pool is reused.
        timeout: Default timeout in seconds for requests on this session.

    Returns:
        A shared TimeoutSession. Safe to use from multiple threads: requests
        sessions are thread-safe for plain request calls, and the pool is what
        we actually want to share.
    """
    key = (name, timeout or DEFAULT_TIMEOUT)
    with _lock:
        session = _sessions.get(key)
        if session is None:
            session = TimeoutSession(timeout or DEFAULT_TIMEOUT)
            _sessions[key] = session
        return session
