#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# core/subtitle_manager.py - Automatic subtitle downloading
#

"""
Subtitle downloading manager using Subliminal.

Handles searching and downloading subtitles from various providers
(OpenSubtitles, Podnapisi, etc.) using the Subliminal library.

Implements a 3-level search strategy:
  1. Search by video hash (exact match)
  2. Search by TMDB title/metadata (fallback)
  3. Manual search with user query (last resort)
"""

import os
import time
from pathlib import Path
from typing import List, Dict, Optional, Set, Any, Tuple
from dataclasses import dataclass
import re

from ..utils.logger import get_logger
from ..utils.i18n import _
from ..utils.config import get_config

try:
    from subliminal import download_best_subtitles, scan_video  # noqa: F401
    from subliminal import list_subtitles, AsyncProviderPool  # noqa: F401
    from subliminal.video import Video, Movie  # noqa: F401
    from babelfish import Language
    HAS_SUBLIMINAL = True
except ImportError:
    HAS_SUBLIMINAL = False

_CACHE_CONFIGURED = False
_OSCOM_LANGUAGES_PATCHED = False


def _cache_dir() -> Path:
    return Path.home() / ".jellyfix" / "cache"


def invalidate_subliminal_token_cache(reason: str = "") -> bool:
    """Apaga o cache de tokens do subliminal.

    O token de sessão do opensubtitles.com fica guardado em disco para
    sobreviver entre execuções. Quando ele deixa de valer — troca de conta,
    expiração, sessão revogada — o subliminal **reusa o token velho** e o
    download volta vazio, sem erro nenhum: a legenda é encontrada e nunca é
    gravada. Apagar o cache força um login novo.

    Returns:
        True se algum arquivo foi removido.
    """
    removidos = False
    base = _cache_dir()
    for nome in ("subliminal.dbm", "subliminal.dbm.db",
                 "subliminal.dbm.dogpile.lock", "subliminal.dbm.rw.lock"):
        alvo = base / nome
        try:
            if alvo.exists():
                alvo.unlink()
                removidos = True
        except OSError:
            pass

    if removidos and reason:
        try:
            get_logger().info(_("Subtitle session cache cleared (%s)") % reason)
        except Exception:
            pass
    return removidos


def _configure_subliminal_cache(username: str = "") -> None:
    """Configure subliminal's dogpile cache region — required for downloads.

    Subliminal caches provider auth tokens (notably opensubtitles.com's session
    token) in a dogpile cache region that the *host application* must configure.
    If it is never configured, every download raises ``RegionNotConfigured`` and
    silently fails — subtitles are found but never written. We set it up once,
    persisting to ~/.jellyfix/cache so the token survives between runs, and fall
    back to an in-memory region if the on-disk backend can't be created.

    O cache é descartado quando o USUÁRIO configurado muda: o token guardado
    pertence a uma conta específica e, reusado com outra, faz todo download
    voltar vazio (a busca funciona, o arquivo nunca chega).
    """
    global _CACHE_CONFIGURED
    if not HAS_SUBLIMINAL or _CACHE_CONFIGURED:
        return
    try:
        from subliminal.cache import region
        if getattr(region, 'is_configured', False):
            _CACHE_CONFIGURED = True
            return

        cache_dir = _cache_dir()
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)

            # Conta mudou desde a última execução? Token antigo não vale mais.
            marcador = cache_dir / "oscom_user"
            anterior = ""
            try:
                anterior = marcador.read_text(encoding="utf-8").strip()
            except OSError:
                pass
            if username and anterior and anterior != username:
                invalidate_subliminal_token_cache(
                    reason=f"{anterior} → {username}"
                )
            if username and anterior != username:
                try:
                    marcador.write_text(username, encoding="utf-8")
                except OSError:
                    pass

            region.configure(
                'dogpile.cache.dbm',
                arguments={'filename': str(cache_dir / "subliminal.dbm")},
            )
        except Exception:
            # On-disk backend failed — use an in-memory region for this run
            region.configure('dogpile.cache.memory')
        _CACHE_CONFIGURED = True
    except Exception:
        pass


def _patch_opensubtitlescom_languages() -> None:
    """Ensure OpenSubtitles.com can search European Portuguese.

    Subliminal 2.5.0 can convert pt-PT to the API code ``pt-pt``, but its
    provider language whitelist omits pt-PT. AsyncProviderPool filters by that
    whitelist before querying, so pt-PT searches otherwise return zero results.
    """
    global _OSCOM_LANGUAGES_PATCHED
    if not HAS_SUBLIMINAL or _OSCOM_LANGUAGES_PATCHED:
        return
    try:
        from subliminal.providers.opensubtitlescom import OpenSubtitlesComProvider

        OpenSubtitlesComProvider.languages.add(Language('por', 'PT'))
        _OSCOM_LANGUAGES_PATCHED = True
    except Exception:
        pass

# Curated provider list: fast and reliable for multilingual subtitle search.
# NOTE: the legacy "opensubtitles" XML-RPC provider was intentionally dropped —
# OpenSubtitles.org disabled that API and it now only raises Unauthorized,
# wasting a round-trip on every search. Use "opensubtitlescom" (the REST API).
# Excludes slow/niche providers (napiprojekt=Polish-only, subtitulamos=Spanish-only).
DEFAULT_PROVIDERS = ["opensubtitlescom", "podnapisi", "gestdown"]

# Fallback providers, only queried when the primary list returns nothing.
# Login-free on purpose (bsplayer = movies+TV, tvsubtitles = TV) so the fallback
# works without any account, unlike addic7ed which requires login.
DEFAULT_EXTRA_PROVIDERS = ["bsplayer", "tvsubtitles"]

# Language display names mapping (ISO 639-2 to human readable)
LANGUAGE_NAMES = {
    'por': 'Português',
    'por-pt': 'Português (Portugal)',
    'eng': 'English',
    'spa': 'Español',
    'fre': 'Français',
    'ger': 'Deutsch',
    'ita': 'Italiano',
    'jpn': '日本語',
    'kor': '한국어',
    'chi': '中文',
    'rus': 'Русский',
    'ara': 'العربية',
    'hin': 'हिन्दी',
    'tur': 'Türkçe',
    'pol': 'Polski',
    'dut': 'Nederlands',
    'swe': 'Svenska',
    'nor': 'Norsk',
    'dan': 'Dansk',
    'fin': 'Suomi',
    'gre': 'Ελληνικά',
    'heb': 'עברית',
    'tha': 'ไทย',
    'vie': 'Tiếng Việt',
    'ind': 'Bahasa Indonesia',
    'may': 'Bahasa Melayu',
    'rum': 'Română',
    'hun': 'Magyar',
    'cze': 'Čeština',
    'ukr': 'Українська',
}


@dataclass
class SubtitleResult:
    """Represents a subtitle search result for manual selection"""
    id: str
    language: str  # ISO 639-2 code (e.g., 'por', 'eng')
    provider: str
    release_name: str
    score: int
    subtitle_obj: Any  # The actual Subtitle object
    
    # Enhanced fields for better UX
    language_name: str = ""  # Human readable (e.g., "Português (Brasil)")
    language_country: str = ""  # Country variant (e.g., "BR", "PT")
    is_forced: bool = False  # Forced subtitles for foreign parts
    is_hearing_impaired: bool = False  # SDH/HI subtitles
    file_size: int = 0  # Size in bytes (0 = unknown)
    download_count: int = 0  # Popularity indicator


class SubtitleManager:
    """Manages subtitle searching and downloading"""

    def __init__(self):
        """Initialize subtitle manager"""
        self.logger = get_logger()
        self.config = get_config()

        self._opensubtitles_accounts = self._configured_opensubtitles_accounts()
        self._opensubtitles_account_index = 0
        self._exhausted_opensubtitles_accounts: Set[int] = set()
        # Quota queried at most once per account and execution.
        self._quota_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        # A sessão só é descartada uma vez por execução
        self._token_reset_done = False

        if not HAS_SUBLIMINAL:
            self.logger.warning("Subliminal library not found. Subtitle downloading disabled.")
        else:
            _patch_opensubtitlescom_languages()
            _configure_subliminal_cache(
                self._active_opensubtitles_account().get('username', '')
            )

    def is_available(self) -> bool:
        """Check if subtitle downloading is available (libraries installed)"""
        return HAS_SUBLIMINAL

    # ------------------------------------------------------------------
    # Shared helpers (single source of truth for languages / providers)
    # ------------------------------------------------------------------

    def _build_languages(self, languages: Optional[List[str]]) -> Set:
        """Convert ISO 639-2 codes into a set of babelfish Language objects.

        Portuguese variants are special-cased: OpenSubtitles.com returns the
        country-qualified variants (pt-BR / pt-PT), so the new 'por-pt'
        preference must be requested as Portuguese from Portugal.
        """
        if not languages:
            languages = self.config.kept_languages or ['por', 'eng']

        langs: Set = set()
        for lang in languages:
            lang = str(lang).lower()
            if lang in ("por-pt", "pt-pt"):
                try:
                    langs.add(Language('por', 'PT'))
                except Exception:
                    langs.add(Language('por'))
            elif lang in ("por", "pt", "por-br", "pt-br"):
                langs.add(Language('por'))
                try:
                    langs.add(Language('por', 'BR'))
                except Exception:
                    pass  # Some babelfish versions may not support country codes
            else:
                langs.add(Language(lang))
        return langs

    @staticmethod
    def _words(text: str) -> set:
        """Palavras de um título, com pontuação virando SEPARADOR.

        Removê-la (em vez de trocar por espaço) grudava as palavras:
        "Dr.STONE" virava "drstone", que não tem NENHUMA palavra em comum com
        "dr stone" — e a legenda certa era descartada como "filme diferente".
        """
        if not text:
            return set()
        limpo = ''.join(c if (c.isalnum() or c.isspace()) else ' ' for c in text.lower())
        return {p for p in limpo.split() if p}

    @staticmethod
    def _subtitle_release_name(sub: Any) -> str:
        """Nome do lançamento da legenda, tolerante à versão do subliminal.

        O subliminal 2.5.0 expõe ``release``/``file_name``/``info`` nos objetos
        do opensubtitles.com; os nomes antigos (``release_info``, ``releases``,
        ``movie_name``) não existem mais. Procurando só pelos antigos, TODAS as
        legendas apareciam como "Unknown release" na busca manual — o usuário
        escolhia às cegas, sem saber qual batia com o vídeo dele.
        """
        for attr in ('release', 'file_name', 'info', 'release_info', 'movie_full_name'):
            value = getattr(sub, attr, None)
            if value:
                return str(value)

        releases = getattr(sub, 'releases', None) or []
        if releases and releases[0]:
            return str(releases[0])

        for attr in ('movie_name', 'series_title', 'series', 'movie_title'):
            value = getattr(sub, attr, None)
            if value:
                return str(value)

        return ""

    @staticmethod
    def _subtitle_flag(sub: Any, attr: str, keywords: tuple) -> bool:
        """Lê um marcador da legenda, preferindo o booleano do provedor.

        Adivinhar pelo texto do lançamento só entra em cena quando o provedor
        não informa o campo — o opensubtitles.com informa.
        """
        value = getattr(sub, attr, None)
        if isinstance(value, bool):
            return value

        release = SubtitleManager._subtitle_release_name(sub).lower()
        return any(k in release for k in keywords)

    def _language_country_code(self, language: Any) -> str:
        """Return a language object's country code (BR/PT/etc.), if present."""
        country = getattr(language, 'country', None)
        if not country:
            return ""
        alpha2 = getattr(country, 'alpha2', None)
        return str(alpha2 or country).upper()

    def _subtitle_language_code(self, sub: Any) -> str:
        """Return Jellyfix's internal language code, preserving pt-PT."""
        lang_code = str(sub.language.alpha3)
        if lang_code == 'por' and self._get_portuguese_variant(sub) == 'por-pt':
            return 'por-pt'
        return lang_code

    def _get_providers(self) -> List[str]:
        """Primary providers, from config with a safe default."""
        return list(getattr(self.config, 'subtitle_providers', None) or DEFAULT_PROVIDERS)

    def _get_extra_providers(self) -> List[str]:
        """Fallback providers, queried only when the primaries find nothing."""
        return list(getattr(self.config, 'subtitle_extra_providers', None) or DEFAULT_EXTRA_PROVIDERS)

    def _configured_opensubtitles_accounts(self) -> List[Dict[str, str]]:
        """Normalize multi-account config and retain legacy compatibility."""
        accounts: List[Dict[str, str]] = []
        seen = set()
        for raw in getattr(self.config, 'opensubtitles_accounts', None) or []:
            if not isinstance(raw, dict):
                continue
            username = str(raw.get('username') or '').strip()
            password = str(raw.get('password') or '')
            if not (username and password) or username.casefold() in seen:
                continue
            account = {'username': username, 'password': password}
            apikey = str(raw.get('apikey') or '').strip()
            if apikey:
                account['apikey'] = apikey
            accounts.append(account)
            seen.add(username.casefold())

        username = str(getattr(self.config, 'opensubtitles_username', '') or '').strip()
        password = str(getattr(self.config, 'opensubtitles_password', '') or '')
        if username and password and username.casefold() not in seen:
            account = {'username': username, 'password': password}
            apikey = str(getattr(self.config, 'opensubtitles_apikey', '') or '').strip()
            if apikey:
                account['apikey'] = apikey
            accounts.insert(0, account)
        return accounts

    def _active_opensubtitles_account(self) -> Dict[str, str]:
        """Return the account currently used by the provider."""
        if not self._opensubtitles_accounts:
            return {}
        return self._opensubtitles_accounts[self._opensubtitles_account_index]

    def _activate_opensubtitles_account(self, index: int) -> None:
        """Switch account and invalidate the provider token cache."""
        if index == self._opensubtitles_account_index:
            return
        self._opensubtitles_account_index = index
        try:
            from subliminal.cache import region
            region.invalidate(hard=True)
        except Exception as e:
            self.logger.debug(f"Could not invalidate OpenSubtitles session: {e}")
        username = self._active_opensubtitles_account().get('username', '')
        self.logger.info(_("OpenSubtitles limit reached; switching to account: %s") % username)
        # The API permits one login per second per IP. Account switches require
        # a fresh login, so leave a small margin before the provider retry.
        time.sleep(1.1)

    def _get_provider_configs(self) -> Dict[str, Dict[str, Any]]:
        """Build per-provider tuning passed to subliminal.

        Crucially bounds opensubtitles.com pagination: the default (unbounded)
        recurses through every result page and the API answers HTTP 400 on deep
        pages for anonymous clients, which both slows searches to ~20s and makes
        them return zero subtitles. Logging in (if configured) lifts the strict
        anonymous rate/download limits.
        """
        max_pages = int(getattr(self.config, 'subtitle_max_pages', 1) or 1)
        timeout = int(getattr(self.config, 'subtitle_timeout', 15) or 15)

        oscom: Dict[str, Any] = {
            'max_result_pages': max_pages,
            'timeout': timeout,
        }
        account = self._active_opensubtitles_account()
        username = account.get('username', '')
        password = account.get('password', '')
        apikey = (
            account.get('apikey', '')
            or getattr(self.config, 'opensubtitles_apikey', '')
            or ''
        )
        if username and password:
            oscom['username'] = username
            oscom['password'] = password
        if apikey:
            oscom['apikey'] = apikey

        return {'opensubtitlescom': oscom}

    def _has_opensubtitles_login(self) -> bool:
        """Whether opensubtitles.com credentials are configured."""
        return bool(self._opensubtitles_accounts)

    def test_opensubtitles_login(self, username: str, password: str) -> Tuple[bool, str]:
        """Verify opensubtitles.com credentials, returning (ok, message).

        Calls the login endpoint directly so we can surface the API's real error
        message (subliminal collapses everything to "Bad Request"). The most
        common failure is using the account e-mail instead of the username.
        """
        if not username or not password:
            return False, _("Username and password are both required")

        try:
            import requests
            try:
                from subliminal.providers.opensubtitlescom import (
                    OPENSUBTITLESCOM_API_KEY, OpenSubtitlesComProvider,
                )
                default_key = OPENSUBTITLESCOM_API_KEY
                user_agent = OpenSubtitlesComProvider.user_agent
            except Exception:
                default_key = 'mij33pjc3kOlup1qOKxnWWxvle2kFbMH'
                user_agent = 'Subliminal'

            apikey = (getattr(self.config, 'opensubtitles_apikey', '') or '') or default_key
            timeout = int(getattr(self.config, 'subtitle_timeout', 15) or 15)

            headers = {
                'Api-Key': apikey,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': user_agent,
            }

            # A API aceita 1 login por segundo por IP e responde 429 acima
            # disso. Sem tratar, testar duas vezes seguidas devolvia um erro
            # de "limite" que parecia (erradamente) senha errada.
            for tentativa in range(3):
                r = requests.post(
                    "https://api.opensubtitles.com/api/v1/login",
                    json={'username': username, 'password': password},
                    headers=headers, timeout=timeout,
                )
                if r.status_code != 429:
                    break
                if tentativa < 2:
                    time.sleep(2)

            if r.status_code == 200:
                return True, _("Login OK — subtitles can be downloaded")

            # Surface the real API message (e.g. "use your username, not e-mail")
            try:
                api_msg = r.json().get('message', '') or r.reason
            except Exception:
                api_msg = r.reason

            if r.status_code == 429:
                return False, _(
                    "opensubtitles.com is rate limiting logins (1 per second per IP). "
                    "Wait a few seconds and test again."
                )

            if r.status_code == 401:
                return False, _(
                    "Username or password rejected by opensubtitles.com. "
                    "Use the USERNAME (not the e-mail), check for a trailing space, "
                    "and confirm the account e-mail was verified — a brand new "
                    "account only works in the API after confirming the e-mail."
                )

            if '@' in username and r.status_code == 400:
                api_msg = _("Use your username, not your e-mail address.")
            return False, api_msg

        except Exception as e:
            return False, str(e)

    def get_opensubtitles_quota(self) -> Optional[Dict[str, Any]]:
        """Query the daily quota for the active opensubtitles.com account.

        Contas gratuitas têm um limite baixo (20 downloads/dia). Ao estourar,
        a busca continua funcionando e o download passa a falhar — subliminal
        engole o erro e o jellyfix só dizia "Failed to download subtitle
        content", sem pista nenhuma do motivo real.

        Returns:
            dict com ``remaining``, ``allowed``, ``used`` e ``reset_in``,
            ou None se não der para consultar. Nunca lança.
        """
        account = self._active_opensubtitles_account()
        username = account.get('username', '')
        password = account.get('password', '')
        if not (username and password):
            return None
        cache_key = username.casefold()
        if cache_key in self._quota_cache:
            return self._quota_cache[cache_key]

        try:
            import requests
            try:
                from subliminal.providers.opensubtitlescom import (
                    OPENSUBTITLESCOM_API_KEY, OpenSubtitlesComProvider,
                )
                default_key, user_agent = OPENSUBTITLESCOM_API_KEY, OpenSubtitlesComProvider.user_agent
            except Exception:
                default_key, user_agent = 'mij33pjc3kOlup1qOKxnWWxvle2kFbMH', 'Subliminal'

            apikey = (
                account.get('apikey', '')
                or getattr(self.config, 'opensubtitles_apikey', '')
                or default_key
            )
            timeout = int(getattr(self.config, 'subtitle_timeout', 15) or 15)
            headers = {
                'Api-Key': apikey,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': user_agent,
            }

            login = requests.post(
                'https://api.opensubtitles.com/api/v1/login',
                json={'username': username, 'password': password},
                headers=headers, timeout=timeout,
            )
            if login.status_code != 200:
                self._quota_cache[cache_key] = None
                return None

            headers['Authorization'] = f"Bearer {login.json().get('token')}"
            info = requests.get(
                'https://api.opensubtitles.com/api/v1/infos/user',
                headers=headers, timeout=timeout,
            )
            if info.status_code != 200:
                self._quota_cache[cache_key] = None
                return None

            data = info.json().get('data', {})
            quota = {
                'remaining': data.get('remaining_downloads'),
                'allowed': data.get('allowed_downloads'),
                'used': data.get('downloads_count'),
                'reset_in': data.get('reset_time'),
                'vip': data.get('vip'),
            }
            self._quota_cache[cache_key] = quota
            return quota

        except Exception as e:
            self.logger.debug(f"Não foi possível consultar a cota do OpenSubtitles: {e}")
            self._quota_cache[cache_key] = None
            return None

    def _retry_with_next_opensubtitles_account(self, sub: Any) -> bool:
        """Retry an empty OpenSubtitles download with each remaining account."""
        if getattr(sub, 'provider_name', '') != 'opensubtitlescom':
            return False
        account_count = len(self._opensubtitles_accounts)
        if account_count < 2:
            return False

        current = self._opensubtitles_account_index
        # The current account already failed after a fresh-session retry. Do
        # not spend another API call on it for every subtitle in this run.
        self._exhausted_opensubtitles_accounts.add(current)

        tried = {current}
        from subliminal import download_subtitles as subliminal_download

        while len(tried) < account_count:
            next_index = next(
                (
                    (current + offset) % account_count
                    for offset in range(1, account_count + 1)
                    if (current + offset) % account_count not in tried
                    and (current + offset) % account_count
                    not in self._exhausted_opensubtitles_accounts
                ),
                None,
            )
            if next_index is None:
                break

            tried.add(next_index)
            self._activate_opensubtitles_account(next_index)
            current = next_index
            sub.content = None
            try:
                subliminal_download([sub], provider_configs=self._get_provider_configs())
            except Exception as e:
                self.logger.debug(f"OpenSubtitles account retry failed: {e}")
            if sub.content:
                return True

            self._exhausted_opensubtitles_accounts.add(next_index)

        return False

    def _retry_after_token_reset(self, sub: Any, provider_configs: Dict) -> bool:
        """Descarta a sessão guardada e tenta baixar de novo (uma vez).

        Só faz sentido quando AINDA HÁ cota: aí o conteúdo vazio não é limite
        diário, e sim token inválido guardado em disco.
        """
        if getattr(sub, 'provider_name', '') != 'opensubtitlescom':
            return False
        if self._token_reset_done:
            return False

        cota = self.get_opensubtitles_quota()
        if cota and cota.get('remaining') == 0:
            self._exhausted_opensubtitles_accounts.add(
                self._opensubtitles_account_index
            )
            return False  # quota exhausted; relogging cannot help

        self._token_reset_done = True

        # Invalida os valores da região em vez de apagar o arquivo: uma região
        # dogpile já configurada NÃO aceita reconfiguração, então remover o
        # .dbm só deixaria a região apontando para um arquivo que não existe.
        try:
            from subliminal.cache import region
            region.invalidate(hard=True)
            self.logger.info(_("Subtitle session cache cleared (stale session)"))
        except Exception as e:
            self.logger.debug(f"Não foi possível invalidar a sessão: {e}")
            return False

        try:
            from subliminal import download_subtitles as subliminal_download
            subliminal_download([sub], provider_configs=provider_configs)
        except Exception as e:
            self.logger.debug(f"Nova tentativa após limpar a sessão falhou: {e}")
            return False

        return bool(sub.content)

    def _download_failure_hint(self, provider: str) -> str:
        """Return a helpful hint when a content download yields nothing.

        opensubtitles.com requires a logged-in account to download (search is
        anonymous). Without credentials, subliminal swallows the AuthenticationError
        and we just get empty content — so surface an actionable message instead.
        """
        if provider != 'opensubtitlescom':
            return ""

        if not self._has_opensubtitles_login():
            return _(
                "opensubtitles.com requires a free account to download subtitles. "
                "Set opensubtitles_username/opensubtitles_password in "
                "~/.jellyfix/config.json (or the OPENSUBTITLES_USERNAME/"
                "OPENSUBTITLES_PASSWORD environment variables)."
            )

        # Com login configurado, a causa mais comum é a cota diária estourada.
        quota = self.get_opensubtitles_quota()
        if len(self._exhausted_opensubtitles_accounts) >= len(
            self._opensubtitles_accounts
        ) > 1:
            return _(
                "Download refused by all configured opensubtitles.com accounts."
            )
        if quota and quota.get('remaining') == 0:
            return _(
                "opensubtitles.com daily download limit reached "
                "(%(used)s of %(allowed)s used). The subtitle WAS found, only the "
                "download was refused. Quota resets in %(reset)s."
            ) % {
                'used': quota.get('used'),
                'allowed': quota.get('allowed'),
                'reset': quota.get('reset_in') or _("less than 24 hours"),
            }

        if quota and quota.get('remaining') is not None:
            return _(
                "Download refused by opensubtitles.com (%(remaining)s of %(allowed)s "
                "downloads left today)."
            ) % {'remaining': quota.get('remaining'), 'allowed': quota.get('allowed')}

        return _("Download refused by opensubtitles.com. Check the login in Settings.")

    @staticmethod
    def _normalize_requested_languages(languages: List[str]) -> List[str]:
        """Normalize and deduplicate requested language codes in order."""
        from ..utils.helpers import normalize_language_code

        normalized = []
        for language in languages:
            code = normalize_language_code(str(language))
            if code and code not in normalized:
                normalized.append(code)
        return normalized

    def _existing_subtitle_languages(self, video_path: Path) -> Dict[str, List[Path]]:
        """Find language-tagged sidecars belonging to one video."""
        from ..utils.helpers import (
            SUBTITLE_EXTENSIONS, detect_subtitle_language, parse_subtitle_name,
        )

        existing: Dict[str, List[Path]] = {}
        try:
            candidates = video_path.parent.iterdir()
        except OSError:
            return existing

        video_stem = video_path.stem.casefold()
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.lower() not in SUBTITLE_EXTENSIONS:
                continue
            parsed = parse_subtitle_name(candidate.stem)
            language = parsed['language']
            if parsed['forced'] or parsed['base_name'].casefold() != video_stem:
                continue
            if not language:
                language = detect_subtitle_language(
                    candidate,
                    min_portuguese_words=getattr(self.config, 'min_pt_words', 5),
                )
            if language:
                existing.setdefault(language, []).append(candidate)
        return existing

    def download_subtitles(self, video_path: Path, languages: Optional[List[str]] = None, 
                           providers: Optional[List[str]] = None,
                           tmdb_title: Optional[str] = None,
                           tmdb_year: Optional[int] = None,
                           tmdb_id: Optional[int] = None,
                           is_episode: bool = False,
                           season: Optional[int] = None,
                           episode: Optional[int] = None,
                           min_score: int = 0) -> Dict[str, List[Path]]:
        """
        Download subtitles for a video file using multi-level search.

        Level 1: Search by video hash (exact match)
        Level 2: Search by TMDB title/metadata (if Level 1 fails)

        Args:
            video_path: Path to video file
            languages: List of languages to download (e.g., ['por', 'eng'])
                       If None, uses configured defaults.
            providers: List of providers to use (e.g., ['opensubtitles', 'podnapisi'])
                       If None, uses default providers.
            tmdb_title: Title from TMDB for fallback search
            tmdb_year: Year from TMDB for fallback search
            tmdb_id: TMDB ID for additional matching
            is_episode: Whether this is a TV episode
            season: Season number for episodes
            episode: Episode number for episodes
            min_score: Minimum score to accept subtitles (0 = accept all)

        Returns:
            Dictionary mapping language code to list of downloaded subtitle paths
        """
        if not self.is_available():
            self.logger.error("Cannot download subtitles: 'subliminal' library missing.")
            return {}

        if not video_path.exists():
            self.logger.error(f"Video file not found: {video_path}")
            return {}

        # Default languages if not provided
        if not languages:
            if self.config.kept_languages:
                languages = self.config.kept_languages
            else:
                languages = ['por', 'eng']

        languages = self._normalize_requested_languages(languages)
        existing = self._existing_subtitle_languages(video_path)
        satisfied = set(languages) & set(existing)
        missing_langs = set(languages) - satisfied
        all_results: Dict[str, List[Path]] = {language: [] for language in satisfied}

        if satisfied:
            self.logger.info(
                _("Subtitles already present for %(video)s: %(languages)s")
                % {
                    'video': video_path.name,
                    'languages': ', '.join(sorted(satisfied)),
                }
            )
        if not missing_langs:
            return all_results

        # Convert to set of Language objects (see _build_languages for pt-BR handling)
        langs = self._build_languages(list(missing_langs))

        self.logger.info(_("Searching subtitles for: %s (Languages: %s)") %
                         (video_path.name, ", ".join(languages)))

        # Level 1: Search by hash
        result = self._search_by_hash(video_path, langs, providers, min_score)
        
        if result:
            all_results.update(result)
            # Remove found languages from missing
            missing_langs -= set(result.keys())
            self.logger.info(_("Level 1 (hash) found: %s") % ", ".join(result.keys()))
        
        # If we still have missing languages and have TMDB info, try Level 2
        if missing_langs and tmdb_title:
            self.logger.info(_("Missing languages: %s - trying TMDB title search") % 
                           ", ".join(missing_langs))
            
            # Convert missing languages to Language objects
            missing_lang_objs = self._build_languages(list(missing_langs))
            
            result2 = self._search_by_title(
                video_path=video_path,
                title=tmdb_title,
                year=tmdb_year,
                langs=missing_lang_objs,
                providers=providers,
                is_episode=is_episode,
                season=season,
                episode=episode,
                min_score=min_score
            )
            
            if result2:
                all_results.update(result2)
                missing_langs -= set(result2.keys())
                self.logger.info(_("Level 2 (TMDB) found: %s") % ", ".join(result2.keys()))
        
        if missing_langs:
            self.logger.info(_("Still missing: %s (try manual search)") % ", ".join(missing_langs))
        
        if not all_results:
            self.logger.info(_("No subtitles found for: %s") % video_path.name)
        
        return all_results

    def download_subtitles_batch(
        self,
        video_paths: List[Path],
        languages: Optional[List[str]] = None,
        providers: Optional[List[str]] = None,
        metadata_map: Optional[Dict[Path, dict]] = None,
        min_score: int = 0,
        progress_callback=None,
    ) -> Dict[Path, Dict[str, List[Path]]]:
        """
        Batch download subtitles for multiple videos.

        Opens provider connections once and reuses for all videos,
        significantly faster than calling download_subtitles() per video.

        Args:
            video_paths: List of video file paths
            languages: Languages to download (default: config kept_languages)
            providers: Providers to use (default: DEFAULT_PROVIDERS)
            metadata_map: Optional dict mapping Path -> {title, year, is_episode, season, episode}
            min_score: Minimum score to accept
            progress_callback: Optional callable(video_path, index, total) for progress updates

        Returns:
            Dict mapping video path to language->subtitle paths dict
        """
        if not self.is_available() or not video_paths:
            return {}

        if not languages:
            languages = self.config.kept_languages or ["por", "eng"]
        languages = self._normalize_requested_languages(languages)

        use_providers = providers or self._get_providers()
        all_results: Dict[Path, Dict[str, List[Path]]] = {}
        missing_by_video: Dict[Path, Set[str]] = {}
        for video_path in video_paths:
            existing = self._existing_subtitle_languages(video_path)
            satisfied = set(languages) & set(existing)
            if satisfied:
                all_results[video_path] = {language: [] for language in satisfied}
                self.logger.info(
                    _("Subtitles already present for %(video)s: %(languages)s")
                    % {
                        'video': video_path.name,
                        'languages': ', '.join(sorted(satisfied)),
                    }
                )
            missing_by_video[video_path] = set(languages) - satisfied
        total = len(video_paths)

        # Phase 1: group videos by missing languages so the batch provider call
        # never requests a sidecar that already exists for one of them.
        self.logger.info(_("Batch Level 1: scanning %d videos by hash...") % total)
        existing_videos = [
            vpath for vpath in video_paths
            if vpath.exists() and missing_by_video[vpath]
        ]
        scanned: Dict[Path, Any] = {}
        if existing_videos:
            # ffprobe/hashing is I/O-bound — parallelize across cores
            from concurrent.futures import ThreadPoolExecutor
            max_workers = min(8, max(2, (os.cpu_count() or 4)))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_to_path = {pool.submit(scan_video, vp): vp for vp in existing_videos}
                for future in future_to_path:
                    vp = future_to_path[future]
                    try:
                        scanned[vp] = future.result()
                    except Exception as e:
                        self.logger.info(f"scan_video failed for {vp.name}: {e}")

        grouped_paths: Dict[frozenset, List[Path]] = {}
        for video_path in scanned:
            grouped_paths.setdefault(
                frozenset(missing_by_video[video_path]), []
            ).append(video_path)

        for missing_languages, group_paths in grouped_paths.items():
            group_scanned = {path: scanned[path] for path in group_paths}
            try:
                hash_results = download_best_subtitles(
                    set(group_scanned.values()),
                    self._build_languages(list(missing_languages)),
                    providers=use_providers,
                    provider_configs=self._get_provider_configs(),
                    pool_class=AsyncProviderPool,
                    min_score=min_score,
                )
            except Exception as e:
                self.logger.warning(f"Batch hash search failed: {e}")
                hash_results = {}

            # Map results back to paths and save subtitles
            video_to_path = {v: p for p, v in group_scanned.items()}
            for video_obj, subs in hash_results.items():
                vpath = video_to_path.get(video_obj)
                if vpath and subs:
                    saved = self._save_subtitles(video_obj, vpath, subs)
                    if saved:
                        all_results.setdefault(vpath, {}).update(saved)
                        self.logger.info(_("Level 1 (hash) found: %s for %s") % (", ".join(saved.keys()), vpath.name))

        # Phase 2: Level 2 fallback for videos still missing languages
        meta = metadata_map or {}
        missing_videos = []
        for idx, vpath in enumerate(video_paths):
            if progress_callback:
                progress_callback(vpath, idx, total)
            found_langs = set(all_results.get(vpath, {}).keys())
            still_need = set(languages) - found_langs
            if still_need and vpath in meta and meta[vpath].get("title"):
                missing_videos.append((vpath, still_need, meta[vpath]))

        if missing_videos:
            self.logger.info(_("Batch Level 2: title search for %d videos...") % len(missing_videos))
            for vpath, need_langs, info in missing_videos:
                lang_objs = self._build_languages(list(need_langs))
                result2 = self._search_by_title(
                    video_path=vpath,
                    title=info["title"],
                    year=info.get("year"),
                    langs=lang_objs,
                    providers=use_providers,
                    is_episode=info.get("is_episode", False),
                    season=info.get("season"),
                    episode=info.get("episode"),
                    min_score=min_score,
                )
                if result2:
                    existing = all_results.get(vpath, {})
                    existing.update(result2)
                    all_results[vpath] = existing
                    self.logger.info(_("Level 2 (TMDB) found: %s for %s") % (", ".join(result2.keys()), vpath.name))

        # Phase 3: fallback providers only for languages still missing.
        extra_providers = [p for p in self._get_extra_providers() if p not in use_providers]
        if extra_providers:
            for vpath in video_paths:
                need_langs = set(languages) - set(all_results.get(vpath, {}))
                if not need_langs:
                    continue
                info = meta.get(vpath)
                if not info or not info.get("title"):
                    continue
                lang_objs = self._build_languages(list(need_langs))
                result3 = self._search_by_title(
                    video_path=vpath,
                    title=info["title"],
                    year=info.get("year"),
                    langs=lang_objs,
                    providers=extra_providers,
                    is_episode=info.get("is_episode", False),
                    season=info.get("season"),
                    episode=info.get("episode"),
                    min_score=min_score,
                )
                if result3:
                    all_results.setdefault(vpath, {}).update(result3)
                    self.logger.info(_("Level 3 (fallback %s) found: %s for %s")
                                     % (", ".join(extra_providers), ", ".join(result3.keys()), vpath.name))

        return all_results

    def _search_by_hash(self, video_path: Path, langs: Set, 
                        providers: Optional[List[str]] = None,
                        min_score: int = 0) -> Dict[str, List[Path]]:
        """
        Level 1: Search subtitles by video file hash.

        This provides the most accurate match since the hash uniquely identifies the video.
        Uses AsyncProviderPool for parallel provider queries.
        """
        try:
            # Scan video for information (hash, size, etc.)
            video = scan_video(video_path)

            # Download best subtitles using AsyncProviderPool for parallel queries
            subtitles = download_best_subtitles(
                {video},
                langs,
                providers=providers or self._get_providers(),
                provider_configs=self._get_provider_configs(),
                pool_class=AsyncProviderPool,
                min_score=min_score,
            )

            if not subtitles or not subtitles[video]:
                return {}

            downloaded_subs = subtitles[video]
            self.logger.info(_("Found %d subtitles by hash for: %s") % 
                           (len(downloaded_subs), video_path.name))

            return self._save_subtitles(video, video_path, downloaded_subs)

        except Exception as e:
            self.logger.info(f"Hash search failed for {video_path.name}: {e}")
            return {}

    def _search_by_title(self, video_path: Path, title: str, year: Optional[int],
                         langs: Set, providers: Optional[List[str]] = None,
                         is_episode: bool = False,
                         season: Optional[int] = None,
                         episode: Optional[int] = None,
                         min_score: int = 0) -> Dict[str, List[Path]]:
        """
        Level 2: Search subtitles by title (from TMDB metadata).
        
        Uses list_subtitles to get all candidates, then validates each one
        to ensure it matches the correct movie/show before downloading.
        """
        try:
            # Create video object from title
            if is_episode and season is not None and episode is not None:
                # Format: "Show Name S01E01.mkv"
                search_name = f"{title} S{season:02d}E{episode:02d}.mkv"
            else:
                # Format: "Movie Name (Year).mkv"
                if year:
                    search_name = f"{title} ({year}).mkv"
                else:
                    search_name = f"{title}.mkv"

            self.logger.info(f"Level 2 searching: '{search_name}' for {[lg.alpha3 for lg in langs]}")
            video = Video.fromname(search_name)

            # Use list_subtitles to get all candidates (more control than download_best_subtitles)
            with AsyncProviderPool(providers=providers or self._get_providers(),
                                   provider_configs=self._get_provider_configs()) as pool:
                all_subtitles = pool.list_subtitles(video, langs)
            
            # Flatten results and validate each subtitle
            # Note: list_subtitles returns a list of subtitles, not a dict
            validated_subs = []
            title_words = self._words(title)

            self.logger.debug(f"Level 2: Received {len(all_subtitles)} subtitles from providers")
            
            for sub in all_subtitles:
                # Get provider name from subtitle object
                provider = getattr(sub, 'provider_name', 'unknown')
                
                # Get subtitle release info for validation
                release_info = self._subtitle_release_name(sub)
                movie_name = (
                    getattr(sub, 'series_title', '')
                    or getattr(sub, 'movie_name', '')
                    or getattr(sub, 'series', '')
                    or ''
                )
                sub_year = getattr(sub, 'year', None)
                
                # Simplified validation - be very permissive
                # Only reject if we have definitive proof it's wrong
                is_valid = True
                rejection_reason = None
                
                # Check year mismatch (only if both years are available)
                if year and sub_year and abs(year - sub_year) > 2:
                    is_valid = False
                    rejection_reason = f"year mismatch ({sub_year} vs {year})"
                
                # Check if it's clearly a different movie (if movie_name is present)
                if is_valid and movie_name:
                    # Only reject if names are completely different
                    movie_words = self._words(movie_name)
                    common_words = title_words & movie_words
                    # Reject only if NO words in common
                    if len(common_words) == 0 and len(title_words) > 0 and len(movie_words) > 0:
                        is_valid = False
                        rejection_reason = f"different movie: '{movie_name}'"
                
                if is_valid:
                    self.logger.debug(f"  [ACCEPT] {sub.language} from {provider}: {movie_name or release_info[:50]}")
                    validated_subs.append(sub)
                else:
                    self.logger.debug(f"  [REJECT] {sub.language} from {provider}: {rejection_reason}")
            
            if not validated_subs:
                self.logger.info(f"Level 2: No validated subtitles for '{title}' ({year})")
                return {}
            
            # Group by language and pick best for each
            best_by_lang = {}
            for sub in validated_subs:
                lang = self._subtitle_language_code(sub)
                
                if lang not in best_by_lang:
                    best_by_lang[lang] = sub
            
            downloaded_subs = list(best_by_lang.values())
            self.logger.info(_("Found %d validated subtitles by title for: %s") % 
                           (len(downloaded_subs), video_path.name))

            return self._save_subtitles(video, video_path, downloaded_subs)

        except Exception as e:
            self.logger.error(f"Title search failed: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    def _validate_subtitle_match(self, title: str, year: Optional[int],
                                  sub_movie_name: str, sub_year: Optional[int],
                                  release_info: str, is_episode: bool = False,
                                  season: Optional[int] = None,
                                  episode: Optional[int] = None) -> bool:
        """
        Validate if a subtitle matches the target movie/show.
        
        Returns True if the subtitle is likely for the correct content.
        Uses relaxed matching - accepts when we can't definitively reject.
        """
        # Pontuação vira separador (ver _words): "Dr.STONE" precisa casar
        # com "Dr. STONE".
        title_clean = ' '.join(sorted(self._words(title)))

        # If we have a movie name from the subtitle, check it
        if sub_movie_name:
            sub_name_clean = ' '.join(sorted(self._words(sub_movie_name)))

            # Direct match or partial match
            if title_clean in sub_name_clean or sub_name_clean in title_clean:
                # Year must match if both are available (within 1 year tolerance)
                if year and sub_year and abs(year - sub_year) > 1:
                    return False
                return True
            
            # Use similarity ratio for fuzzy matching (config-tunable)
            similarity = self._title_similarity(title_clean, sub_name_clean)
            if similarity >= get_config().title_similarity_threshold:
                if year and sub_year and abs(year - sub_year) > 1:
                    return False
                return True
        
        # Fallback: Check release info for title words
        if release_info:
            release_clean = ' '.join(sorted(self._words(release_info)))
            
            # Check if significant title words appear in release info
            title_words = [w for w in title_clean.split() if len(w) > 2]
            if title_words:
                words_found = sum(1 for w in title_words if w in release_clean)
                match_ratio = words_found / len(title_words) if title_words else 0
                
                # Accept if at least 40% of words match (relaxed from 60%)
                if match_ratio >= 0.4:
                    # For movies, prefer year match but don't require it
                    if year and str(year) in release_info:
                        return True
                    elif year and (str(year - 1) in release_info or str(year + 1) in release_info):
                        return True
                    elif not year:
                        return True
                    # Year in title but not in release - still accept if good word match
                    elif match_ratio >= 0.6:
                        return True
        
        # For episodes, require season/episode match
        if is_episode and season is not None and episode is not None:
            season_ep_pattern = f"s{season:02d}e{episode:02d}"
            if release_info and season_ep_pattern in release_info.lower():
                return True
            return False
        
        # If we have no info to validate, ACCEPT by default (changed from reject)
        # This allows subtitles through when providers don't give us metadata
        # The user can still see and choose from the results
        if not sub_movie_name and not release_info:
            return True
        
        return False
    
    def _title_similarity(self, a: str, b: str) -> float:
        """Calculate simple similarity ratio between two strings."""
        if not a or not b:
            return 0.0
        
        # Use set intersection of words
        words_a = set(a.split())
        words_b = set(b.split())
        
        if not words_a or not words_b:
            return 0.0
        
        intersection = words_a & words_b
        union = words_a | words_b
        
        return len(intersection) / len(union) if union else 0.0
    
    def _get_portuguese_variant(self, sub) -> str:
        """
        Detect if Portuguese subtitle is pt-BR or pt-PT.
        Returns 'por-br' or 'por-pt' for prioritization.
        """
        release_info = self._subtitle_release_name(sub).lower()

        country = self._language_country_code(getattr(sub, 'language', None))
        if country == 'BR':
            return 'por-br'
        if country == 'PT':
            return 'por-pt'
        
        release_text = f" {release_info} "

        # Check for explicit Brazilian/European Portuguese indicators.
        br_indicators = ['brazil', 'brasileiro', 'brazilian', 'pt-br', 'ptbr', '(br)', '[br]', ' br ']
        pt_indicators = ['portugal', 'pt-pt', 'ptpt', '(pt)', '[pt]', ' pt ']
        
        for indicator in br_indicators:
            if indicator in release_text:
                return 'por-br'
        
        for indicator in pt_indicators:
            if indicator in release_text:
                return 'por-pt'
        
        # Default to generic Portuguese
        return 'por'
    
    def _get_language_display_info(self, sub) -> Tuple[str, str]:
        """
        Get human-readable language name and country code from subtitle.
        
        Args:
            sub: Subtitle object
            
        Returns:
            Tuple of (language_name, country_code)
            e.g., ("Português (Brasil)", "BR") or ("English", "")
        """
        lang_code = str(sub.language.alpha3)
        base_name = LANGUAGE_NAMES.get(lang_code, lang_code.upper())
        
        # Get release info for country detection
        release_info = self._subtitle_release_name(sub).lower()

        country = ""
        
        # Detect Portuguese variant
        if lang_code == 'por':
            language_country = self._language_country_code(sub.language)
            if language_country == "BR":
                return "Português (Brasil)", "BR"
            if language_country == "PT":
                return "Português (Portugal)", "PT"

            release_text = f" {release_info} "
            br_indicators = ['brazil', 'brasileiro', 'brazilian', 'pt-br', 'ptbr', '(br)', '[br]', ' br ']
            pt_indicators = ['portugal', 'pt-pt', 'ptpt', '(pt)', '[pt]', ' pt ']
            
            for indicator in br_indicators:
                if indicator in release_text:
                    country = "BR"
                    base_name = "Português (Brasil)"
                    break
            else:
                for indicator in pt_indicators:
                    if indicator in release_text:
                        country = "PT"
                        base_name = "Português (Portugal)"
                        break
        
        # Detect Spanish variant
        elif lang_code == 'spa':
            lat_indicators = ['latino', 'lat ', 'latinoamerica', 'latam', 'spanish-lat', 'mexico', 'mx']
            esp_indicators = ['spain', 'españa', 'castellano', 'spanish-es', '(es)', '[es]']
            
            for indicator in lat_indicators:
                if indicator in release_info:
                    country = "LAT"
                    base_name = "Español (Latino)"
                    break
            else:
                for indicator in esp_indicators:
                    if indicator in release_info:
                        country = "ES"
                        base_name = "Español (España)"
                        break
        
        # Detect English variant
        elif lang_code == 'eng':
            us_indicators = ['english-us', 'en-us', '(us)', '[us]', 'american']
            uk_indicators = ['english-uk', 'en-gb', '(uk)', '[uk]', 'british']
            
            for indicator in us_indicators:
                if indicator in release_info:
                    country = "US"
                    base_name = "English (US)"
                    break
            else:
                for indicator in uk_indicators:
                    if indicator in release_info:
                        country = "UK"
                        base_name = "English (UK)"
                        break
        
        return base_name, country

    def search_subtitles_manual(self, query: str, 
                                languages: Optional[List[str]] = None,
                                is_episode: bool = False,
                                season: Optional[int] = None,
                                episode: Optional[int] = None,
                                year: Optional[int] = None,
                                providers: Optional[List[str]] = None) -> List[SubtitleResult]:
        """
        Level 3: Manual search - returns list of subtitles for user selection.
        
        Args:
            query: Search term (movie/show title)
            languages: Languages to search for
            is_episode: Whether searching for TV episode
            season: Season number for episodes
            episode: Episode number for episodes
            year: Year for movies
            providers: Providers to use
            
        Returns:
            List of SubtitleResult for user to choose from
        """
        if not self.is_available():
            return []

        # Convert to set of Language objects (see _build_languages for pt-BR handling)
        langs = self._build_languages(languages)

        try:
            # Create video from query
            if is_episode and season is not None and episode is not None:
                search_name = f"{query} S{season:02d}E{episode:02d}.mkv"
            else:
                if year:
                    search_name = f"{query} ({year}).mkv"
                else:
                    search_name = f"{query}.mkv"

            self.logger.info(_("Manual search: %s") % search_name)
            video = Video.fromname(search_name)

            provider_configs = self._get_provider_configs()

            # List all subtitles (not just best). If the primary providers return
            # nothing, retry with the extra/fallback providers (user request:
            # "search elsewhere when OpenSubtitles has nothing").
            primary = providers or self._get_providers()
            with AsyncProviderPool(providers=primary,
                                   provider_configs=provider_configs) as pool:
                all_subtitles = pool.list_subtitles(video, langs)

            if not all_subtitles and not providers:
                extra = [p for p in self._get_extra_providers() if p not in primary]
                if extra:
                    self.logger.info(_("No results from primary providers, trying: %s")
                                     % ", ".join(extra))
                    with AsyncProviderPool(providers=extra,
                                           provider_configs=provider_configs) as pool:
                        all_subtitles = pool.list_subtitles(video, langs)

            # Create results from list
            # Note: list_subtitles returns a list of Subtitle objects, not a dict
            results = []
            for sub in all_subtitles:
                # Get provider name from subtitle object
                provider = getattr(sub, 'provider_name', 'unknown')
                
                # Get release name (clean it up)
                release = self._subtitle_release_name(sub) or _("Unknown release")

                # Get language info
                lang_code = self._subtitle_language_code(sub)
                lang_name, lang_country = self._get_language_display_info(sub)

                # Marcadores: usa o booleano do provedor quando existir
                is_forced = self._subtitle_flag(
                    sub, 'foreign_only', ('forced', 'forçada', 'forçado')
                )
                is_hi = self._subtitle_flag(
                    sub, 'hearing_impaired', ('sdh', 'hi ', 'hearing', 'cc', 'closed caption')
                )
                
                # Get file size if available
                file_size = getattr(sub, 'size', 0) or 0
                
                # Get download count if available (popularity)
                download_count = getattr(sub, 'download_count', 0) or 0
                
                results.append(SubtitleResult(
                    id=str(getattr(sub, 'id', hash(sub))),
                    language=lang_code,
                    provider=str(provider),
                    release_name=str(release)[:150],  # Truncate long names
                    score=0,
                    subtitle_obj=sub,
                    language_name=lang_name,
                    language_country=lang_country,
                    is_forced=is_forced,
                    is_hearing_impaired=is_hi,
                    file_size=file_size,
                    download_count=download_count
                ))
            
            # Sort by language, then by download count (popularity), then provider
            results.sort(key=lambda x: (x.language, -x.download_count, x.provider, x.release_name))
            
            self.logger.info(_("Found %d subtitles in manual search") % len(results))
            return results
            
        except Exception as e:
            self.logger.error(f"Manual search failed: {e}")
            import traceback
            traceback.print_exc()
            return []

    def download_selected_subtitle(self, subtitle_result: SubtitleResult, 
                                   video_path: Path) -> Optional[Path]:
        """
        Download a specific subtitle selected by user.
        
        Args:
            subtitle_result: The SubtitleResult chosen by user
            video_path: Path to save subtitle next to
            
        Returns:
            Path to downloaded subtitle or None
        """
        if not self.is_available():
            return None
            
        try:
            sub = subtitle_result.subtitle_obj

            existing = self._existing_subtitle_languages(video_path)
            if subtitle_result.language in existing:
                self.logger.info(
                    _("Subtitle already present; skipping download: %s")
                    % existing[subtitle_result.language][0].name
                )
                return existing[subtitle_result.language][0]

            # Download subtitle content (pass provider_configs so login/quota apply)
            from subliminal import download_subtitles
            download_subtitles([sub], provider_configs=self._get_provider_configs())

            if not sub.content:
                self._retry_after_token_reset(sub, self._get_provider_configs())
            if not sub.content:
                self._retry_with_next_opensubtitles_account(sub)
            
            if not sub.content:
                hint = self._download_failure_hint(subtitle_result.provider)
                if hint:
                    self.logger.error(_("Failed to download subtitle content. %s") % hint)
                else:
                    self.logger.error("Failed to download subtitle content")
                return None

            # Save to file (por-pt vira pt-PT no disco — ver helpers)
            from ..utils.helpers import language_code_for_filename
            lang = language_code_for_filename(subtitle_result.language)
            subtitle_path = video_path.with_suffix(f".{lang}.srt")
            
            # Handle encoding
            encoding = getattr(sub, 'encoding', None) or 'utf-8'
            try:
                content = sub.content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                # Fallback to chardet
                import chardet
                detected = chardet.detect(sub.content)
                content = sub.content.decode(detected.get('encoding', 'utf-8'), errors='replace')
            
            subtitle_path.write_text(content, encoding='utf-8')
            self.logger.info(_("Downloaded subtitle: %s") % subtitle_path.name)
            
            return subtitle_path
            
        except Exception as e:
            self.logger.error(f"Failed to download selected subtitle: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _save_subtitles(self, video, video_path: Path, 
                        downloaded_subs: List) -> Dict[str, List[Path]]:
        """Save downloaded subtitles and normalize language codes to 3-letter format.
        
        Note: We download content manually and save to video_path location to ensure
        the subtitle is saved next to the actual video file, not where subliminal
        thinks the video is (which may be wrong for Level 2 virtual videos).
        """
        from subliminal import download_subtitles as subliminal_download

        result = {}
        existing_languages = self._existing_subtitle_languages(video_path)

        for sub in downloaded_subs:
            try:
                lang_alpha3 = self._subtitle_language_code(sub)
                if lang_alpha3 in existing_languages:
                    result.setdefault(lang_alpha3, [])
                    self.logger.info(
                        _("Subtitle already present; skipping download: %s")
                        % existing_languages[lang_alpha3][0].name
                    )
                    continue

                # Download subtitle content if not already downloaded
                if not sub.content:
                    subliminal_download(
                        [sub], provider_configs=self._get_provider_configs()
                    )

                if not sub.content:
                    # Conteúdo vazio SEM erro é a assinatura de token velho.
                    # Se ainda há cota, o problema não é limite: descarta a
                    # sessão guardada e tenta uma vez mais com login novo.
                    if self._retry_after_token_reset(
                        sub, self._get_provider_configs()
                    ):
                        pass

                if not sub.content:
                    self._retry_with_next_opensubtitles_account(sub)

                if not sub.content:
                    # Diz POR QUE falhou (cota estourada é de longe o motivo
                    # mais comum, e antes ficava invisível).
                    hint = self._download_failure_hint(
                        str(getattr(sub, 'provider_name', '') or '')
                    )
                    if hint:
                        self.logger.error(
                            _("Failed to download subtitle content. %s") % hint
                        )
                    else:
                        self.logger.warning(f"Failed to download subtitle content for {sub}")
                    continue
                
                # Keep 3-letter codes, preserving pt-PT as Jellyfix's por-pt.
                if lang_alpha3 not in result:
                    result[lang_alpha3] = []

                # Save directly to video_path location with 3-letter code.
                # language_code_for_filename() aplica a única exceção do
                # projeto (por-pt → pt-PT), que o Jellyfin sabe resolver.
                from ..utils.helpers import language_code_for_filename
                file_lang = language_code_for_filename(lang_alpha3)
                subtitle_path = video_path.with_suffix(f".{file_lang}.srt")
                
                # Handle encoding
                encoding = getattr(sub, 'encoding', None) or 'utf-8'
                try:
                    content = sub.content.decode(encoding)
                except (UnicodeDecodeError, LookupError):
                    # Fallback to chardet
                    try:
                        import chardet
                        detected = chardet.detect(sub.content)
                        content = sub.content.decode(detected.get('encoding', 'utf-8'), errors='replace')
                    except Exception:
                        content = sub.content.decode('utf-8', errors='replace')
                
                # Write to file
                subtitle_path.write_text(content, encoding='utf-8')
                self.logger.info(f"Saved subtitle: {subtitle_path.name}")
                
                result[lang_alpha3].append(subtitle_path)
                
            except Exception as e:
                self.logger.error(f"Failed to save subtitle: {e}")
                import traceback
                traceback.print_exc()

        return result

    def list_providers(self) -> List[str]:
        """List available subtitle providers"""
        if not self.is_available():
            return []
        
        try:
            from subliminal.extensions import provider_manager
            return [p.name for p in provider_manager]
        except ImportError:
            return []

    @staticmethod
    def extract_tmdb_info_from_path(path: Path) -> Tuple[Optional[int], Optional[str], Optional[int]]:
        """
        Extract TMDB ID, title and year from a file path.
        
        Looks for patterns like:
        - [tmdbid-12345]
        - Movie Name (2020)
        
        Returns:
            Tuple of (tmdb_id, title, year)
        """
        path_str = str(path)
        
        # Extract TMDB ID
        tmdb_match = re.search(r'\[tmdbid-(\d+)\]', path_str)
        tmdb_id = int(tmdb_match.group(1)) if tmdb_match else None
        
        from ..utils.helpers import (
            SUBTITLE_EXTENSIONS, VIDEO_EXTENSIONS, extract_year, normalize_spaces,
        )

        # Extract title and year from filename or folder
        # Pattern: "Title (Year)" or "Title (Year) [tmdbid-XXX]"
        #
        # A extensão é retirada sempre que for de mídia conhecida. Depender de
        # is_file() falhava para caminhos que ainda não existem em disco (o
        # destino planejado, por exemplo) e o "mp4" acabava colado no título
        # enviado para os provedores de legenda.
        if path.suffix.lower() in VIDEO_EXTENSIONS or path.suffix.lower() in SUBTITLE_EXTENSIONS:
            name = path.stem
        else:
            name = path.stem if path.is_file() else path.name
        
        # Remove quality tags and other noise
        name = re.sub(r'\s*-\s*(2160p|1080p|720p|480p|4K|BluRay|WEB-DL|HDRip).*', '', name)
        name = re.sub(r'\s*\[tmdbid-\d+\].*', '', name)
        
        # Extract year
        year_match = re.search(r'\((\d{4})\)', name)
        year = int(year_match.group(1)) if year_match else extract_year(name)
        
        # Extract title (before the year)
        if year_match:
            title = name[:year_match.start()].strip()
        else:
            title = name.strip()
        
        return tmdb_id, normalize_spaces(title), year
