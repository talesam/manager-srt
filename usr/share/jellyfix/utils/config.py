"""Configuration system for Jellyfix"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import os

# Application version
APP_VERSION = "2.9.3"


@dataclass
class Config:
    """Configurações do jellyfix"""

    # Diretórios
    work_dir: Path = field(default_factory=Path.cwd)
    backup_dir: Optional[Path] = None
    log_file: Optional[Path] = None

    # Operações
    rename_por2: bool = True  # Mantido por compatibilidade, mas agora renomeia TODAS as variações
    rename_no_lang: bool = True
    remove_foreign_subs: bool = True
    remove_language_variants: bool = False  # Remove eng2, por3, etc. quando já existe eng, por
    remove_unwanted: bool = True
    organize_folders: bool = True
    fetch_metadata: bool = True
    add_quality_tag: bool = True  # Adiciona tag de qualidade (1080p, 720p, etc)
    use_ffprobe: bool = False  # Usa ffprobe para detectar resolução (mais lento mas preciso)
    ask_on_multiple_results: bool = False  # Pergunta ao usuário quando há múltiplos resultados TMDB
    rename_nfo: bool = True  # Renomeia arquivos NFO para corresponder ao vídeo
    remove_non_media: bool = False  # Remove arquivos que não sejam .srt ou .mp4
    fix_mirabel_files: bool = True  # Corrige legendas Mirabel (.pt-BR.hi → .por)

    # Detecção de português
    min_pt_words: int = 5

    # Network / API tunables
    image_download_timeout: int = 10  # seconds for poster/backdrop HTTP requests
    max_search_results: int = 10  # max TMDB/subtitle results shown in pickers
    title_similarity_threshold: float = 0.5  # min ratio for fuzzy title matching
    # Confiança mínima (similaridade de título PT/original x proximidade de ano)
    # para aceitar um match do TMDB no modo não-interativo. Abaixo disso o
    # jellyfix NÃO renomeia (evita match errado) e registra p/ revisão manual.
    match_confidence_threshold: float = 0.55
    min_subtitle_bytes: int = 20  # files smaller than this are skipped as junk

    # Modos de execução
    dry_run: bool = True
    interactive: bool = True
    verbose: bool = False
    quiet: bool = False
    auto_confirm: bool = False
    workdir_explicit: bool = False  # True when --workdir was explicitly provided

    # APIs
    tmdb_api_key: str = ""
    tvdb_api_key: str = ""

    # Subtitle download (subliminal)
    # Primary providers, queried in parallel for every search.
    subtitle_providers: list = field(
        default_factory=lambda: ["opensubtitlescom", "podnapisi", "gestdown"]
    )
    # Fallback providers, queried only when the primary ones return nothing.
    # Kept login-free on purpose so downloads work without any account
    # (bsplayer = movies+TV, tvsubtitles = TV). addic7ed is great but needs login.
    subtitle_extra_providers: list = field(
        default_factory=lambda: ["bsplayer", "tvsubtitles"]
    )
    # Max result pages to fetch per provider. The opensubtitles.com API rejects
    # deep/unbounded pagination (HTTP 400) for anonymous clients, so keep this low.
    subtitle_max_pages: int = 1
    # Per-request network timeout for subtitle providers (seconds).
    subtitle_timeout: int = 15
    # OpenSubtitles.com credentials. Anonymous search works, but logging in is
    # required to actually download subtitle content beyond a tiny daily quota.
    opensubtitles_username: str = ""
    opensubtitles_password: str = ""
    opensubtitles_apikey: str = ""

    # Subtitle languages to KEEP (will NOT be removed)
    # Default: Portuguese and English
    kept_languages: list = field(default_factory=lambda: ["por", "eng"])

    # Complete list of known languages (for selection interface)
    all_languages: dict = field(default_factory=lambda: {
        "ara": "Arabic",
        "baq": "Basque",
        "bul": "Bulgarian",
        "cat": "Catalan",
        "chi": "Chinese",
        "cze": "Czech",
        "dan": "Danish",
        "dut": "Dutch",
        "eng": "English",
        "fil": "Filipino",
        "fin": "Finnish",
        "fre": "French",
        "ger": "German",
        "glg": "Galician",
        "gre": "Greek",
        "heb": "Hebrew",
        "hin": "Hindi",
        "hrv": "Croatian",
        "hun": "Hungarian",
        "ind": "Indonesian",
        "ita": "Italian",
        "jpn": "Japanese",
        "kor": "Korean",
        "lav": "Latvian",
        "lit": "Lithuanian",
        "may": "Malay",
        "nob": "Norwegian (Bokmål)",
        "nor": "Norwegian",
        "pol": "Polish",
        "por": "Portuguese",
        "por-pt": "Portuguese (Portugal)",
        "rum": "Romanian",
        "rus": "Russian",
        "slo": "Slovak",
        "slv": "Slovenian",
        "spa": "Spanish",
        "swe": "Swedish",
        "tam": "Tamil",
        "tel": "Telugu",
        "tha": "Thai",
        "tur": "Turkish",
        "ukr": "Ukrainian",
        "vie": "Vietnamese"
    })

    def __post_init__(self):
        """Converte strings para Path objects (sem I/O de disco)"""
        if isinstance(self.work_dir, str):
            self.work_dir = Path(self.work_dir)
        if self.backup_dir and isinstance(self.backup_dir, str):
            self.backup_dir = Path(self.backup_dir)
        if self.log_file and isinstance(self.log_file, str):
            self.log_file = Path(self.log_file)

    def load_persistent_settings(self, explicit_keys=None):
        """Carrega configurações do arquivo persistente e variáveis de ambiente.

        Chamado separadamente de __post_init__ para evitar I/O no construtor.

        Prioridade (documentada no CLAUDE.md): argumento de linha de comando >
        variável de ambiente > arquivo JSON > padrão.

        Args:
            explicit_keys: nomes de opções que vieram EXPLICITAMENTE da linha
                de comando e portanto não podem ser sobrescritas pelo arquivo.
                Sem isso, ``--no-remove-foreign`` (e as outras flags) eram
                silenciosamente revertidas pelo valor salvo em config.json.
        """
        from .config_manager import ConfigManager
        config_mgr = ConfigManager()
        explicit = set(explicit_keys or ())

        # API keys
        if not self.tmdb_api_key:
            self.tmdb_api_key = config_mgr.get_tmdb_api_key() or os.getenv("TMDB_API_KEY", "")

        if not self.tvdb_api_key:
            self.tvdb_api_key = config_mgr.get_tvdb_api_key() or os.getenv("TVDB_API_KEY", "")

        # Carrega configurações do arquivo persistente
        saved_languages = config_mgr.get('kept_languages')
        if saved_languages and 'kept_languages' not in explicit:
            from .helpers import normalize_language_code
            self.kept_languages = [normalize_language_code(lang) for lang in saved_languages]

        # Carrega opções booleanas.
        # add_quality_tag e use_ffprobe estavam FALTANDO nesta lista: as duas
        # interfaces (CLI e GUI) as gravavam em config.json, mas elas nunca
        # eram lidas de volta — a preferência do usuário voltava ao padrão a
        # cada execução.
        for key in ['rename_por2', 'rename_no_lang', 'remove_foreign_subs',
                    'remove_language_variants', 'organize_folders', 'fetch_metadata',
                    'ask_on_multiple_results', 'rename_nfo', 'remove_non_media',
                    'fix_mirabel_files', 'add_quality_tag', 'use_ffprobe']:
            if key in explicit:
                continue
            saved_value = config_mgr.get(key)
            if saved_value is not None:
                setattr(self, key, saved_value)

        # Carrega valores numéricos ajustáveis
        for key in ['min_pt_words', 'match_confidence_threshold',
                    'title_similarity_threshold', 'min_subtitle_bytes',
                    'image_download_timeout', 'max_search_results']:
            if key in explicit:
                continue
            saved_value = config_mgr.get(key)
            if saved_value is not None:
                setattr(self, key, saved_value)

        # Subtitle download settings (file > env var > default)
        for key in ['subtitle_providers', 'subtitle_extra_providers',
                    'subtitle_max_pages', 'subtitle_timeout']:
            saved_value = config_mgr.get(key)
            if saved_value is not None:
                setattr(self, key, saved_value)

        if not self.opensubtitles_username:
            self.opensubtitles_username = (
                config_mgr.get('opensubtitles_username')
                or os.getenv("OPENSUBTITLES_USERNAME", "")
            )
        if not self.opensubtitles_password:
            self.opensubtitles_password = (
                config_mgr.get('opensubtitles_password')
                or os.getenv("OPENSUBTITLES_PASSWORD", "")
            )
        if not self.opensubtitles_apikey:
            self.opensubtitles_apikey = (
                config_mgr.get('opensubtitles_apikey')
                or os.getenv("OPENSUBTITLES_APIKEY", "")
            )


# Configuração global (singleton pattern)
_config: Optional[Config] = None


def get_config() -> Config:
    """Retorna a configuração global"""
    global _config
    if _config is None:
        _config = Config()
        _config.load_persistent_settings()
    return _config


def set_config(config: Config):
    """Define a configuração global"""
    global _config
    _config = config
