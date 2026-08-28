"""Funções auxiliares e utilitários"""

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

# Palavras comuns em português para detecção
PORTUGUESE_WORDS = [
    "que", "não", "para", "com", "uma", "mais", "muito", "está", "você",
    "seu", "sua", "ele", "ela", "são", "mas", "por", "até", "também",
    "bem", "foi", "ser", "vai", "pode", "ainda", "onde", "quando",
    "como", "porque", "sem", "sobre", "todo", "tinha", "foram", "fazer"
]

# Caracteres proibidos no Jellyfin
FORBIDDEN_CHARS = r'[<>"/\\|?*]'  # Removido ':' para permitir em Linux

# Extensões de vídeo suportadas
VIDEO_EXTENSIONS = {
    '.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm',
    '.m4v', '.mpg', '.mpeg', '.3gp', '.ogv'
}

# Extensões de legenda
SUBTITLE_EXTENSIONS = {'.srt', '.ass', '.ssa', '.sub', '.vtt'}

# Extensões de imagem
IMAGE_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
    '.tiff', '.ico', '.svg'
}

# ---------------------------------------------------------------------------
# Extras do Jellyfin (doc oficial: "Extras").
# Vídeos dentro dessas pastas, ou com esses nomes/sufixos, NÃO são filmes:
# são material extra que pertence à pasta da mídia. Antes o jellyfix tratava
# "trailer.mp4" e "behind the scenes/Making of.mp4" como filmes próprios e
# os arrancava da pasta, quebrando exatamente a estrutura documentada.
# ---------------------------------------------------------------------------
EXTRAS_FOLDER_NAMES = frozenset({
    'behind the scenes', 'deleted scenes', 'interviews', 'scenes', 'samples',
    'shorts', 'featurettes', 'clips', 'other', 'extras', 'trailers',
    'theme-music', 'backdrops',
})

# Nomes de arquivo que, sozinhos, marcam um extra.
EXTRAS_FILE_STEMS = frozenset({'trailer', 'sample'})

# Sufixos de extra. Conforme a doc, com poucas exceções NÃO contêm espaços.
EXTRAS_SUFFIXES = (
    '-trailer', '.trailer', '_trailer', ' trailer',
    '-sample', '.sample', '_sample', ' sample',
    '-scene', '-clip', '-interview', '-behindthescenes', '-deleted',
    '-deletedscene', '-featurette', '-short', '-other', '-extra',
)

# Nomes de imagem que o Jellyfin reconhece como arte da mídia (doc oficial:
# "Metadata Images"). Podem aparecer sozinhos (logo.png) ou como sufixo
# (movie-logo.png). Faltavam justamente os mais comuns — cover e folder —
# e por isso cover.jpg/folder.jpg eram classificados como "indesejados"
# (e apagados quando remove_non_media estava ligado).
JELLYFIN_IMAGE_NAMES = frozenset({
    'poster', 'folder', 'cover', 'default', 'movie', 'show', 'jacket', 'thumb',
    'backdrop', 'fanart', 'background', 'art', 'extrafanart', 'banner',
    'logo', 'clearlogo', 'clearart', 'landscape', 'disc', 'discart', 'cdart',
})


def is_extras_folder(name: str) -> bool:
    """A pasta é uma pasta de extras do Jellyfin?"""
    return name.strip().lower() in EXTRAS_FOLDER_NAMES


def is_extras_path(file_path: Path) -> bool:
    """O arquivo é um extra (por pasta, nome ou sufixo)?"""
    for parent in file_path.parents:
        if is_extras_folder(parent.name):
            return True

    stem = file_path.stem.strip().lower()
    if stem in EXTRAS_FILE_STEMS:
        return True

    return any(stem.endswith(suffix) for suffix in EXTRAS_SUFFIXES)


def is_jellyfin_image(file_path: Path) -> bool:
    """A imagem é uma arte reconhecida pelo Jellyfin?

    Aceita o nome puro (``cover.jpg``), como sufixo (``movie-logo.png``,
    ``S01E01 Some Episode-thumb.jpg``) e numerada (``backdrop-1.jpg``,
    ``backdrop2.jpg``), como descrito na documentação.
    """
    stem = file_path.stem.strip().lower()
    # Remove numeração de backdrops múltiplos: backdrop-1 / backdrop2
    stem = re.sub(r'[-_ ]?\d+$', '', stem) or stem

    if stem in JELLYFIN_IMAGE_NAMES:
        return True

    # Forma de sufixo: "<qualquer coisa><separador><nome>"
    return any(
        stem.endswith(sep + name)
        for name in JELLYFIN_IMAGE_NAMES
        for sep in ('-', '_', '.', ' ')
    )

# Pre-compiled regex patterns (avoid recompilation on every call)
_RE_FORBIDDEN = re.compile(FORBIDDEN_CHARS)
_RE_MULTI_SPACE = re.compile(r"\s+")
_RE_BRACKET_RELEASE = re.compile(r"\[(?!19|20)\w+[\w\s\.\-]*\]")
_RE_PAREN_NON_YEAR = re.compile(r"\((?!19\d{2}|20\d{2})[^\)]*\)")
_RE_YEAR_LOOSE = re.compile(r"\s+(19\d{2}|20\d{2})(?!\))\s*")
_RE_AUDIO_CHANNELS = re.compile(r"\b([257])\s+([01])\b")
_RE_REPEATED_SUFFIX = re.compile(r"(-\w+)\1+")
_RE_CONVERTED = re.compile(r"-converted", re.IGNORECASE)
# Grupo de release colado por hífen — SOMENTE no fim do nome e somente quando o
# token "parece" um grupo (ver _looks_like_release_group).
#
# O padrão antigo (r"-[A-Z0-9]{2,}\b" com IGNORECASE, em qualquer posição)
# destruía títulos hifenizados legítimos: "Spider-Man" → "Spider",
# "X-Men" → "X", "Ant-Man" → "Ant". O hífen NÃO é proibido pelo Jellyfin
# (caracteres reservados: < > : " / \ | ? *) e a própria limpeza do Jellyfin
# (NamingOptions.CleanStrings) só remove tokens de uma whitelist fechada.
_RE_RELEASE_GROUP_HYPHEN = re.compile(r"-([A-Za-z0-9]{2,})\s*$")
_RE_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,\.!?;:])")
_RE_TRAILING_JUNK = re.compile(r"[\s\-\.]+$")
_RE_LEADING_JUNK = re.compile(r"^[\s\-\.]+")
# O ano não pode estar colado em outro dígito/letra: o CRC32 que os grupos de
# anime põem no nome ("[75012039]") contém "2039" e virava ano, envenenando a
# busca no TMDB. Separadores ( ) [ ] . _ - e espaço continuam valendo.
_RE_YEAR = re.compile(r"(?<![0-9A-Za-z])(19\d{2}|20\d{2})(?![0-9A-Za-z])")
_RE_SXXEXX = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,2})(?:-?[Ee](\d{1,2}))?")
_RE_NxNN = re.compile(r"\b(\d{1,2})x(\d{1,2})\b")

_RE_QUALITY_PATTERNS = [
    re.compile(r"\b(1080p|720p|480p|2160p|4K|HD|UHD|FHD)\b", re.IGNORECASE),
    re.compile(r"\b(BluRay|BRRip|BDRip|WEB-?DL|WEBRip|HDTV|DVDRip|DVD-?Rip|CAMRip|TS|TC)\b", re.IGNORECASE),
    re.compile(r"\b(x264|x265|H\.?264|H\.?265|HEVC|XviD|DivX|AVC)\b", re.IGNORECASE),
    re.compile(r"\b(AMZNWEB|AMZN|Amazon|Netflix|Hulu|HBO|HMAX|Disney|Apple|Paramount|Peacock|Showtime|Starz)\b", re.IGNORECASE),
    re.compile(r"\b(Dual\.?Audio|DUAL)\b", re.IGNORECASE),
    re.compile(r"\b(Audio)\b", re.IGNORECASE),
    re.compile(r"\b(AAC|AC3|E-?AC-?3|DTS|DD\+?|MP3|FLAC|Dolby|Atmos|TrueHD)\b", re.IGNORECASE),
    re.compile(r"\b(5\.1|7\.1|2\.0)\b", re.IGNORECASE),
    re.compile(r"\b(EXTENDED|UNRATED|REMASTERED|DIRECTORS?\.?CUT|DC|IMAX)\b", re.IGNORECASE),
    re.compile(r"\b(converted|rip|web|hdtv|bluray)\b", re.IGNORECASE),
]

_RE_RESOLUTION_TAGS = [
    (re.compile(r"(?:^|[\s\._\-\[\(])(2160p|4K)(?:[\s\._\-\]\)]|$)", re.IGNORECASE), "2160p"),
    (re.compile(r"(?:^|[\s\._\-\[\(])(1080p)(?:[\s\._\-\]\)]|$)", re.IGNORECASE), "1080p"),
    (re.compile(r"(?:^|[\s\._\-\[\(])(720p)(?:[\s\._\-\]\)]|$)", re.IGNORECASE), "720p"),
    (re.compile(r"(?:^|[\s\._\-\[\(])(480p)(?:[\s\._\-\]\)]|$)", re.IGNORECASE), "480p"),
    (re.compile(r"(?:^|[\s\._\-\[\(])(8K)(?:[\s\._\-\]\)]|$)", re.IGNORECASE), "8K"),
]

_RELEASE_GROUPS = [
    "BRHD",
    "YTS",
    "YIFY",
    "RARBG",
    "ETRG",
    "PSA",
    "AMIABLE",
    "SPARKS",
    "FLEET",
    "ION10",
    "CMRG",
    "EVO",
    "NTb",
    "AMRAP",
    "FGT",
    "STUTTERSHIT",
    "VYNDROS",
    "MkvCage",
    "GalaxyRG",
    "DEFLATE",
    "NOGRP",
    "W4F",
    "ETHEL",
    "TOMMY",
    "AFG",
    "GECKOS",
]
_RE_RELEASE_GROUPS = [re.compile(rf"\b{g}\b", re.IGNORECASE) for g in _RELEASE_GROUPS]

def _looks_like_release_group(token: str) -> bool:
    """Heurística: o token colado por hífen no fim é grupo de release?

    Grupos de release são MAIÚSCULOS (RARBG, YTS, FGT), têm dígitos
    (3LT0N, W4F) ou capitalização interna (BiOMA, GalaxyRG).
    Palavras reais de título são Title case ("Man", "Men", "Marie") ou
    minúsculas — essas NUNCA podem ser removidas.
    """
    if any(ch.isdigit() for ch in token):
        return True
    if token.isupper():
        return True
    # Maiúscula depois da primeira letra: BiOMA, GalaxyRG, MkvCage
    return any(ch.isupper() for ch in token[1:])


# ---------------------------------------------------------------------------
# Flags de faixa externa reconhecidas pelo Jellyfin.
# Fonte: Emby.Naming/Common/NamingOptions.cs (MediaDefaultFlags,
# MediaForcedFlags, MediaHearingImpairedFlags) e a doc oficial
# "External Subtitles and Audio Tracks".
#
# Isso NÃO é código de idioma: 'hi' e 'cc' já foram confundidos com idioma e
# faziam legendas válidas (Movie.eng.cc.srt) serem apagadas como "estrangeiras".
# ---------------------------------------------------------------------------
SUBTITLE_FLAGS_DEFAULT = frozenset({"default"})
SUBTITLE_FLAGS_FORCED = frozenset({"forced", "foreign"})
SUBTITLE_FLAGS_HEARING_IMPAIRED = frozenset({"sdh", "cc", "hi"})
SUBTITLE_FLAGS = SUBTITLE_FLAGS_DEFAULT | SUBTITLE_FLAGS_FORCED | SUBTITLE_FLAGS_HEARING_IMPAIRED

_RE_LANG_CODE = re.compile(r"\.([a-z]{2,3}(?:[-_][a-z]{2})?)(?:\d)?(?:\.(forced|sdh|default))?\.(srt|ass|ssa|sub|vtt)$")
_RE_LANG_SUFFIX = re.compile(r"\.[a-z]{2,3}(?:[-_][a-z]{2})?$", re.IGNORECASE)
_RE_LANG_PART = re.compile(r"^[a-z]{2,3}(?:[-_][a-z]{2})?$")

_RE_SE_ALT_PATTERNS = [
    re.compile(
        r"(?:Book|Volume|Vol|Part|Season|Temporada|Temp)\s*(\d{1,2})\s*[-\s]+(?:Episode|Episodio|Ep\.?|E)?\s*(\d{1,2})",
        re.IGNORECASE,
    ),
    re.compile(r"T(?:emp)?\.?\s*(\d{1,2})\s*E(?:p)?\.?\s*(\d{1,2})", re.IGNORECASE),
    re.compile(r"[\[\(\{]\s*(\d{1,2})x(\d{1,2})\s*[\]\)\}]", re.IGNORECASE),
    # Apenas marcadores EXPLÍCITOS de episódio (Cap/Capítulo/Ep/Episódio).
    # NÃO incluir "E" sozinho: o "e" de "Grease 2", "Blade 2" casava com " 2" e
    # classificava o FILME como série (S02E02). Exige fronteira de palavra.
    re.compile(r"\b(?:Cap(?:[íi]tulo)?|Ep(?:is[óo]dio)?)\.?\s*(\d{1,2})\b", re.IGNORECASE),
    # Episódio compacto "- 101" (=S01E01). Guardas para não pegar resolução
    # (720p/480p) nem ano (2015): não seguido de p/k/i nem de mais dígitos,
    # e não precedido por dígito (parte de número maior).
    re.compile(r"(?<!\d)[-\s](\d)(\d{2})(?![\dpPkKiI])(?:\D|$)"),
    # Numeração absoluta de anime: "[Grupo] Título - 01 [tags]", "Título - 12v2".
    # Sem isso cada episódio virava um FILME e todos casavam com o mesmo título
    # no TMDB, indo parar no mesmo destino. Só episódio (1 grupo) => temporada 1.
    # Exige " - " com espaços e 2+ dígitos zero-padded: sequência de filme se
    # escreve "Blade 2", não "Blade - 02". A guarda [\dpPkKiI] descarta
    # resolução ("Filme - 720p") e o lookahead descarta ano ("Filme - 2015"),
    # sem perder anime de 4 dígitos ("One Piece - 1015").
    re.compile(r"\s-\s(?!(?:19|20)\d{2}(?!\d))(\d{2,4})(?:v\d)?(?![\dpPkKiI])"),
]


# Detecção de português por PALAVRA INTEIRA (\b). Substring dava falso
# positivo em inglês ("por" em "important", "ele" em "element"...).
_RE_PT_WORDS = re.compile(r"\b(?:" + "|".join(PORTUGUESE_WORDS) + r")\b")
_RE_SUBTITLE_TIMING = re.compile(
    r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{1,2}[,.]\d{1,3}\s+-->"
)
_RE_SUBTITLE_HTML = re.compile(r"<[^>]+>")
_RE_SUBTITLE_ASS_TAG = re.compile(r"\{\\[^}]*\}")
_RE_SUBTITLE_MICRODVD = re.compile(r"^\{\d+\}\{\d+\}")
_RE_SUBTITLE_SDH_CUE = re.compile(r"\[[^\]\n]{1,80}\]")

LANGUAGE_DETECTION_MIN_CHARS = 80
LANGUAGE_DETECTION_MIN_CONFIDENCE = 0.85
LANGUAGE_DETECTION_MIN_MARGIN = 0.20

# Subtitle quality scoring weights
_QUALITY_BLOCK_WEIGHT = 10
_QUALITY_LINE_WEIGHT = 2
_QUALITY_TINY_FILE_PENALTY = 0.1
_QUALITY_MIN_FILE_SIZE = 100  # bytes
_QUALITY_TINY_THRESHOLD = 1024  # bytes


def read_subtitle_text(file_path: Path, max_bytes: int = 512 * 1024) -> str:
    """
    Lê o texto de uma legenda lidando com os encodings comuns.

    Muitas legendas antigas são ISO-8859-1/Windows-1252 (não UTF-8). Ler com
    utf-8 + errors='ignore' DESTRÓI as palavras acentuadas ("não" vira "no",
    "está" vira "est"), o que quebrava a detecção de idioma por conteúdo.

    Ordem: BOM (UTF-8/UTF-16) → UTF-8 estrito → Latin-1 (nunca falha).
    """
    with open(file_path, 'rb') as f:
        raw = f.read(max_bytes)

    if raw.startswith(b'\xef\xbb\xbf'):
        return raw.decode('utf-8-sig', errors='replace')
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16', errors='replace')
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('latin-1', errors='replace')


def calculate_subtitle_quality(file_path: Path, file_size: Optional[int] = None) -> float:
    """
    Calcula a "qualidade" de um arquivo de legenda baseado em:
    - Tamanho do arquivo
    - Número de blocos de legenda
    - Número de linhas de texto

    Args:
        file_path: Path to subtitle file.
        file_size: Optional pre-computed size in bytes (avoids redundant stat()).

    Returns:
        Pontuação de qualidade (maior = melhor)
        0 = arquivo vazio ou inválido
    """
    try:
        if file_size is None:
            file_size = file_path.stat().st_size

        if file_size < _QUALITY_MIN_FILE_SIZE:
            return 0.0

        # Lê o conteúdo (com detecção de encoding)
        content = read_subtitle_text(file_path)

        lines = content.strip().split('\n')

        # Conta blocos de legenda (linhas que são apenas números)
        subtitle_blocks = 0
        text_lines = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Bloco de legenda (número sequencial)
            if line.isdigit():
                subtitle_blocks += 1
            # Linha de texto (não é timestamp)
            elif '-->' not in line and not line.isdigit():
                text_lines += 1

        # Calcula pontuação
        # Base: tamanho em KB
        size_score = file_size / 1024

        # Bônus: número de blocos de legenda (mais blocos = mais completo)
        blocks_score = subtitle_blocks * _QUALITY_BLOCK_WEIGHT

        # Bônus: número de linhas de texto
        text_score = text_lines * _QUALITY_LINE_WEIGHT

        if file_size < _QUALITY_TINY_THRESHOLD:
            size_score *= _QUALITY_TINY_FILE_PENALTY

        total_score = size_score + blocks_score + text_score

        return total_score

    except (OSError, UnicodeDecodeError) as e:
        _log.debug("calculate_subtitle_quality(%s) failed: %s", file_path, e)
        return 0.0


def extract_subtitle_dialogue(file_path: Path) -> str:
    """Return dialogue text with subtitle markup and timing removed.

    Supports textual SRT, ASS/SSA, VTT and MicroDVD SUB files. Binary SUB
    files remain unknown; treating their bytes as text produces confident but
    meaningless language guesses.
    """
    if not file_path.exists() or file_path.suffix.lower() not in SUBTITLE_EXTENSIONS:
        return ""

    if file_path.suffix.lower() == '.sub':
        try:
            with open(file_path, 'rb') as subtitle_file:
                if b'\0' in subtitle_file.read(4096):
                    return ""
        except OSError:
            return ""

    try:
        content = read_subtitle_text(file_path)
    except (OSError, UnicodeDecodeError):
        return ""

    dialogue = []
    for raw_line in content.splitlines():
        line = raw_line.strip().lstrip('\ufeff')
        if not line or line.isdigit() or _RE_SUBTITLE_TIMING.match(line):
            continue

        upper = line.upper()
        if upper in {'WEBVTT', '[SCRIPT INFO]', '[V4+ STYLES]', '[EVENTS]'}:
            continue
        if upper.startswith(('NOTE ', 'STYLE ', 'REGION ', 'FORMAT:', 'COMMENT:')):
            continue
        if upper.startswith(('TITLE:', 'SCRIPT TYPE:', 'PLAYRESX:', 'PLAYRESY:', 'WRAPSTYLE:')):
            continue

        if upper.startswith('DIALOGUE:'):
            fields = line.split(',', 9)
            if len(fields) < 10:
                continue
            line = fields[-1]

        line = _RE_SUBTITLE_MICRODVD.sub('', line)
        line = _RE_SUBTITLE_ASS_TAG.sub('', line)
        line = _RE_SUBTITLE_HTML.sub('', line)
        line = _RE_SUBTITLE_SDH_CUE.sub('', line)
        line = line.replace(r'\N', ' ').replace(r'\n', ' ').replace('♪', ' ')
        line = re.sub(r'\s+', ' ', line).strip(' -–—')
        if line:
            dialogue.append(line)

    return '\n'.join(dialogue)


@lru_cache(maxsize=512)
def _detect_subtitle_language_cached(
    path: str,
    file_size: int,
    modified_ns: int,
    min_confidence: float,
    min_margin: float,
    min_chars: int,
    min_portuguese_words: int,
) -> Optional[str]:
    """Cached implementation keyed by file identity and detector settings."""
    del file_size, modified_ns  # Values form the cache key.
    text = extract_subtitle_dialogue(Path(path))
    alphabetic_chars = sum(character.isalpha() for character in text)
    if alphabetic_chars < min_chars:
        return None

    try:
        from langdetect import DetectorFactory, detect_langs
        from langdetect.lang_detect_exception import LangDetectException

        DetectorFactory.seed = 0
        try:
            probabilities = detect_langs(text)
        except LangDetectException:
            return None

        if not probabilities:
            return None
        best = probabilities[0]
        runner_up = probabilities[1].prob if len(probabilities) > 1 else 0.0
        if best.prob < min_confidence or best.prob - runner_up < min_margin:
            return None

        language = normalize_language_code(best.lang)
        if language not in KNOWN_LANGUAGE_CODES:
            return None
        if language == 'por':
            portuguese_words = len(set(_RE_PT_WORDS.findall(text.lower())))
            if portuguese_words < min_portuguese_words:
                return None
        return language
    except ImportError:
        # Compatibility fallback for installations not updated yet.
        words = len(set(_RE_PT_WORDS.findall(text.lower())))
        return 'por' if words >= min_portuguese_words else None


def detect_subtitle_language(
    file_path: Path,
    min_confidence: float = LANGUAGE_DETECTION_MIN_CONFIDENCE,
    min_margin: float = LANGUAGE_DETECTION_MIN_MARGIN,
    min_chars: int = LANGUAGE_DETECTION_MIN_CHARS,
    min_portuguese_words: int = 5,
) -> Optional[str]:
    """Detect an untagged textual subtitle language with confidence gates."""
    try:
        stat = file_path.stat()
    except OSError:
        return None
    return _detect_subtitle_language_cached(
        str(file_path.resolve()),
        stat.st_size,
        stat.st_mtime_ns,
        float(min_confidence),
        float(min_margin),
        int(min_chars),
        int(min_portuguese_words),
    )


def is_portuguese_subtitle(file_path: Path, min_words: int = 5) -> bool:
    """
    Detecta se uma legenda textual é uma legenda em português.

    Args:
        file_path: Caminho para o arquivo de legenda
        min_words: Número mínimo de palavras portuguesas para considerar português

    Returns:
        True se for detectado como português
    """
    return detect_subtitle_language(
        file_path,
        min_portuguese_words=min_words,
    ) == 'por'


def clean_filename(name: str) -> str:
    """
    Remove caracteres proibidos do nome do arquivo.

    Args:
        name: Nome do arquivo

    Returns:
        Nome limpo
    """
    # Substitui ':' por espaço (Jellyfin não suporta dois pontos; ':' é
    # caractere reservado). Não usamos hífen porque ' - ' é o separador de
    # título de episódio do Jellyfin ("Series Name - S01E01"); um hífen no
    # meio do título faria o Jellyfin ler só o texto antes dele como nome
    # da série. Espaços extras são colapsados logo abaixo.
    cleaned = name.replace(":", " ")

    # Substitui caracteres proibidos
    cleaned = _RE_FORBIDDEN.sub("", cleaned)

    # Remove espaços extras
    cleaned = _RE_MULTI_SPACE.sub(" ", cleaned).strip()

    return cleaned


def normalize_spaces(name: str) -> str:
    """
    Normaliza espaços: substitui pontos por espaços, remove múltiplos espaços.

    Args:
        name: Nome do arquivo

    Returns:
        Nome normalizado
    """
    original = name

    # Substitui pontos, underscores e hífen duplo por espaços
    name = name.replace('.', ' ').replace('_', ' ').replace('--', ' ')

    # Remove colchetes com conteúdo de release (mas preserva ano)
    # Remove: [1080p], [BluRay], [HEVC], [DUAL], etc
    name = _RE_BRACKET_RELEASE.sub("", name)

    # Remove parênteses que NÃO são ano (1900-2099)
    # Remove: (BluRay), (DUAL), etc, mas preserva (1999), (2024)
    name = _RE_PAREN_NON_YEAR.sub("", name)

    # Remove ano solto (sem parênteses) quando está no meio/final do nome
    # Ex: "Matrix 1999 1080p" -> "Matrix 1080p"
    # Preserva apenas se estiver entre parênteses: (1999)
    name = _RE_YEAR_LOOSE.sub(" ", name)

    # Remove informações de qualidade e release comuns (padrões específicos)
    for pattern in _RE_QUALITY_PATTERNS:
        name = pattern.sub("", name)

    # Remove APENAS padrões de canais de áudio (5.1, 7.1, 2.0 -> "5 1", "7 1", "2 0")
    # NÃO remove dígitos isolados para preservar títulos como "Super 8", "District 9"
    name = _RE_AUDIO_CHANNELS.sub(" ", name)

    # Remove sufixos repetidos como "-converted-converted" (antes de remover grupos)
    name = _RE_REPEATED_SUFFIX.sub(r"\1", name)  # Remove repetições
    name = _RE_CONVERTED.sub("", name)

    # Remove grupo de release colado por hífen NO FIM do nome (-3LT0N, -RARBG,
    # -BiOMA), preservando títulos hifenizados (Spider-Man, X-Men, Anne-Marie).
    group_match = _RE_RELEASE_GROUP_HYPHEN.search(name)
    if group_match and _looks_like_release_group(group_match.group(1)):
        name = name[: group_match.start()]

    # Remove grupos de release comuns que aparecem soltos (sem hífen)
    # Ex: BRHD, YTS, YIFY, RARBG, ETRG, etc.
    for pattern in _RE_RELEASE_GROUPS:
        name = pattern.sub("", name)

    # NOTA: aqui existia uma heurística que removia QUALQUER palavra de 2-6
    # letras maiúsculas no fim do nome. Ela comia palavras reais do título
    # quando o release vinha em caixa alta: "Dr.STONE.S01E20..." virava só
    # "Dr", e o TMDB devolvia "Dr. House". Grupos de release já são tratados
    # pela lista explícita acima e pela regra de hífen — falso-negativo (lixo
    # sobrando na busca) é muito mais barato que casar com a série errada.

    # Remove espaços múltiplos
    name = _RE_MULTI_SPACE.sub(" ", name).strip()

    # Remove espaços antes de pontuação
    name = _RE_SPACE_BEFORE_PUNCT.sub(r"\1", name)

    # Limpeza final: remove hífens, espaços e pontos isolados no final
    name = _RE_TRAILING_JUNK.sub("", name)
    name = _RE_LEADING_JUNK.sub("", name)  # Remove também do início se houver

    name = name.strip()

    # Rede de segurança: se a limpeza destruiu o nome, é melhor devolver o
    # original só com separadores normalizados do que um título vazio/1 letra
    # que casaria com qualquer coisa no TMDB.
    if len(name) < 2:
        fallback = _RE_MULTI_SPACE.sub(" ", original.replace(".", " ").replace("_", " ")).strip()
        fallback = _RE_TRAILING_JUNK.sub("", fallback)
        if len(fallback) > len(name):
            return fallback

    return name


def extract_quality_tag(name: str) -> Optional[str]:
    """
    Extrai tag de qualidade do nome do arquivo.

    Suporta formatos:
    - Resoluções: 480p, 720p, 1080p, 2160p, 4K, 8K
    - Dentro ou fora de colchetes/parênteses
    - Com ou sem separadores (_1080p_, .1080p., 1080p)

    Args:
        name: Nome do arquivo

    Returns:
        Tag de qualidade ou None
    """
    # Resoluções (aceita word boundary OU underscore/ponto)
    for pattern, tag in _RE_RESOLUTION_TAGS:
        match = pattern.search(name)
        if match:
            return tag

    return None


def detect_video_resolution(file_path: Path) -> Optional[str]:
    """
    Detecta resolução de vídeo usando ffprobe.

    Args:
        file_path: Caminho do arquivo de vídeo

    Returns:
        Tag de resolução (480p, 720p, 1080p, 2160p) ou None
    """
    try:
        import subprocess
        import json

        # Verifica se ffprobe está disponível
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', str(file_path)],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)

        # Procura stream de vídeo
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video':
                height = stream.get('height')
                if height:
                    # Mapeia altura para tag de qualidade
                    if height >= 2160:
                        return '2160p'
                    elif height >= 1080:
                        return '1080p'
                    elif height >= 720:
                        return '720p'
                    elif height >= 480:
                        return '480p'
                    else:
                        return None

        return None

    except (ImportError, FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def extract_year(name: str) -> Optional[int]:
    """
    Extrai o ano de um nome de arquivo.

    Args:
        name: Nome do arquivo

    Returns:
        Ano extraído ou None
    """
    # Procura padrão (YYYY) ou YYYY
    match = _RE_YEAR.search(name)
    if match:
        return int(match.group(1))
    return None


def extract_season_episode(name: str) -> Optional[tuple]:
    """
    Extrai informações de temporada e episódio do nome.

    Formatos suportados:
    - S01E01, s01e01
    - 1x01
    - S01E01-E02 (múltiplos episódios)
    - Book 1 - 01, Volume 1 - 01, Part 1 - 01
    - Season 1 Episode 01, Temporada 1 Episodio 01

    Args:
        name: Nome do arquivo

    Returns:
        Tupla (season, episode_start, episode_end) ou None
    """
    # Padrão S01E01 ou s01e01
    match = _RE_SXXEXX.search(name)
    if match:
        season = int(match.group(1))
        ep_start = int(match.group(2))
        ep_end = int(match.group(3)) if match.group(3) else ep_start
        return (season, ep_start, ep_end)

    # Padrão 1x01 (com word boundaries para não pegar anos como "2018" → "20x18")
    match = _RE_NxNN.search(name)
    if match:
        # Verifica se não é um ano (ex: "2018" não deve virar "20x18")
        # Anos válidos: 1900-2099
        match.group(0)  # Ex: "20x18"
        # Se parece com ano, ignora
        potential_year = match.group(1) + match.group(2)  # Ex: "2018"
        if len(potential_year) == 4 and potential_year.isdigit():
            year_val = int(potential_year)
            if 1900 <= year_val <= 2099:
                # É um ano, não é SxxExx
                return None

        season = int(match.group(1))
        episode = int(match.group(2))
        return (season, episode, episode)

    # Padrões alternativos: Book 1 - 01, T01E01, [01x01], etc
    for pattern in _RE_SE_ALT_PATTERNS:
        match = pattern.search(name)
        if match:
            # Verifica se o match não está dentro de um ano
            # Ex: "Movie 2018" não deve ser S20E18 ou S2E01
            match_start = match.start()
            match_end = match.end()

            # Verifica se há um dígito antes do match (formando ano)
            if match_start > 0 and name[match_start - 1].isdigit():
                # Pode ser parte de um ano maior
                continue

            # Verifica se há dígito depois (formando ano)
            if match_end < len(name) and name[match_end].isdigit():
                # Pode ser parte de um ano maior
                continue

            if len(match.groups()) > 1 and match.group(2) is not None:
                season = int(match.group(1))
                episode = int(match.group(2))
            else:
                # Marcador só de episódio ("Cap 5", "Ep 3"): temporada não foi
                # informada, então assume 1 — antes virava S05E05/S03E03.
                season = 1
                episode = int(match.group(1))
            return (season, episode, episode)

    return None


def is_video_file(file_path: Path) -> bool:
    """Verifica se é um arquivo de vídeo"""
    return file_path.suffix.lower() in VIDEO_EXTENSIONS


def is_subtitle_file(file_path: Path) -> bool:
    """Verifica se é um arquivo de legenda"""
    return file_path.suffix.lower() in SUBTITLE_EXTENSIONS


def is_image_file(file_path: Path) -> bool:
    """Verifica se é um arquivo de imagem"""
    return file_path.suffix.lower() in IMAGE_EXTENSIONS


def normalize_language_code(lang_code: str) -> str:
    """
    Normaliza códigos de idioma de 2 ou 3 caracteres para o padrão de 3 letras.

    Args:
        lang_code: Código de idioma (pode ser en, eng, pt, pt-BR, pt-PT, br, etc.)

    Returns:
        Código normalizado (eng, por, por-pt, spa, etc.)
    """
    normalized = (lang_code or "").strip().lower().replace('_', '-')

    # Preserve the Portuguese Portugal variant so users can keep/search it
    # separately from the existing generic/Brazilian Portuguese preference.
    if normalized in {'pt-pt', 'por-pt'}:
        return 'por-pt'
    if normalized in {'pt-br', 'por-br'}:
        return 'por'

    # Remove qualquer outra região/país do código (en-US -> en)
    base_code = normalized.split('-')[0]

    # Mapa de códigos de 2 letras para 3 letras (ISO 639-1 -> ISO 639-2)
    code_map = {
        'en': 'eng',  # English
        'pt': 'por',  # Portuguese
        'br': 'por',  # Brazilian (não é código ISO, mas comum em legendas)
        'es': 'spa',  # Spanish
        'fr': 'fre',  # French
        'de': 'ger',  # German
        'it': 'ita',  # Italian
        'ja': 'jpn',  # Japanese
        'ko': 'kor',  # Korean
        'zh': 'chi',  # Chinese
        'ru': 'rus',  # Russian
        'ar': 'ara',  # Arabic
        'hi': 'hin',  # Hindi
        'nl': 'dut',  # Dutch
        'sv': 'swe',  # Swedish
        'no': 'nor',  # Norwegian
        'da': 'dan',  # Danish
        'fi': 'fin',  # Finnish
        'pl': 'pol',  # Polish
        'tr': 'tur',  # Turkish
        'he': 'heb',  # Hebrew
        'el': 'gre',  # Greek
        'cs': 'cze',  # Czech
        'hu': 'hun',  # Hungarian
        'ro': 'rum',  # Romanian
        'uk': 'ukr',  # Ukrainian
        'th': 'tha',  # Thai
        'vi': 'vie',  # Vietnamese
        'id': 'ind',  # Indonesian
        'ms': 'may',  # Malay
        'tl': 'fil',  # Filipino
        'bg': 'bul',  # Bulgarian
        'ca': 'cat',  # Catalan
        'hr': 'hrv',  # Croatian
        'lt': 'lit',  # Lithuanian
        'lv': 'lav',  # Latvian
        'sk': 'slo',  # Slovak
        'sl': 'slv',  # Slovenian
        'ta': 'tam',  # Tamil
        'te': 'tel',  # Telugu
    }

    # Se já está no formato de 3 letras, retorna normalizado
    if len(base_code) == 3:
        return base_code

    # Se é 2 letras, converte usando o mapa
    if len(base_code) == 2:
        return code_map.get(base_code, base_code)

    # Se não se encaixa em nenhum padrão, retorna como está
    return base_code


# Códigos ISO 639-2 aceitos como idioma de legenda. Usado para não confundir
# um flag ("cc", "hi", "sdh") ou um pedaço do título ("sub", "the") com idioma.
KNOWN_LANGUAGE_CODES = frozenset({
    'ara', 'baq', 'bul', 'cat', 'chi', 'cze', 'dan', 'dut', 'eng', 'fil', 'fin',
    'fre', 'ger', 'glg', 'gre', 'heb', 'hin', 'hrv', 'hun', 'ind', 'ita', 'jpn',
    'kor', 'lav', 'lit', 'may', 'nob', 'nor', 'pol', 'por', 'por-pt', 'rum',
    'rus', 'slo', 'slv', 'spa', 'swe', 'tam', 'tel', 'tha', 'tur', 'ukr', 'vie',
})

_RE_LANG_TOKEN = re.compile(r'^([a-z]{2,3})([-_][a-z]{2})?(\d)?$', re.IGNORECASE)


def parse_subtitle_name(stem: str) -> dict:
    """Separa o nome de uma legenda em base + idioma + variante + flags.

    Fonte da verdade única para o projeto — antes existiam DOIS parsers
    divergentes (``has_language_code`` aqui e um regex inline no renamer), e o
    do renamer lia o flag como se fosse idioma: ``Movie.eng.cc.srt`` virava
    idioma "cc", caía fora de ``kept_languages`` e era APAGADO. O mesmo
    acontecia com ``.eng.hi.srt`` (virava "hin") e ``.en.sdh.srt`` ("sdh") —
    todos nomes válidos segundo a documentação oficial do Jellyfin.

    Regra do ``hi`` (doc oficial): sozinho é Hindi; junto de outro idioma é
    marcador de surdez.

    Args:
        stem: nome do arquivo SEM a extensão (ex.: "Movie.eng.sdh").

    Returns:
        dict com ``base_name``, ``language`` (3 letras ou None), ``variant``
        (int ou None, de .por2/.eng3), ``forced``, ``default``,
        ``hearing_impaired`` e ``flags`` (conjunto de tokens originais).
    """
    parts = stem.split('.')
    language: Optional[str] = None
    variant: Optional[int] = None
    flags: set = set()
    pending_hi = False
    cut = len(parts)

    # Caminha da direita para a esquerda; parts[0] nunca é consumido, pois é
    # sempre parte do nome base.
    for i in range(len(parts) - 1, 0, -1):
        token = parts[i].strip().lower()
        if not token:
            break

        if token in SUBTITLE_FLAGS:
            if token == 'hi':
                pending_hi = True
            else:
                flags.add(token)
            cut = i
            continue

        match = _RE_LANG_TOKEN.match(token)
        if match and language is None:
            candidate = match.group(1) + (match.group(2) or '')
            code = normalize_language_code(candidate)
            if code in KNOWN_LANGUAGE_CODES:
                language = code
                variant = int(match.group(3)) if match.group(3) else None
                cut = i
                continue

        break

    if pending_hi:
        if language is None:
            language = 'hin'  # ".hi" sozinho = Hindi
        else:
            flags.add('hi')

    return {
        'base_name': '.'.join(parts[:cut]),
        'language': language,
        'variant': variant,
        'forced': bool(flags & SUBTITLE_FLAGS_FORCED),
        'default': bool(flags & SUBTITLE_FLAGS_DEFAULT),
        'hearing_impaired': bool(flags & SUBTITLE_FLAGS_HEARING_IMPAIRED),
        'flags': flags,
    }


# ---------------------------------------------------------------------------
# Código de idioma gravado NO ARQUIVO.
#
# Regra geral: 3 letras (por, eng, spa...) — é o padrão do projeto e o que o
# Jellyfin resolve via ThreeLetterISOLanguageNames, exibindo o idioma certo.
#
# ÚNICA exceção: Português de Portugal. O ISO 639-2 não tem código de 3 letras
# que separe pt-PT de pt-BR (os dois são "por"), então o código interno
# 'por-pt' não existe para o Jellyfin: FindLanguageInfo() não casa com nada e
# a legenda entra SEM idioma (o token vira título da faixa). O servidor aceita
# a forma com região — em iso6392.txt há a linha "por||pt-pt|Portuguese
# (Portugal)" e o ExternalPathParser preserva nomes de cultura com '-'.
# Portanto, só para esse caso, gravamos 'pt-PT'.
# ---------------------------------------------------------------------------
FILENAME_LANGUAGE_OVERRIDES = {
    'por-pt': 'pt-PT',
}


def language_code_for_filename(language: Optional[str]) -> Optional[str]:
    """Converte o código interno no token que vai para o nome do arquivo."""
    if not language:
        return language
    return FILENAME_LANGUAGE_OVERRIDES.get(language.lower(), language)


def build_subtitle_name(base_name: str, language: Optional[str], suffix: str,
                        forced: bool = False, hearing_impaired: bool = False,
                        default: bool = False) -> str:
    """Monta o nome de uma legenda no padrão do Jellyfin.

    Mantém o código de idioma de 3 letras (por/eng), que é o que o Jellyfin
    resolve via ``ThreeLetterISOLanguageNames`` e exibe corretamente na
    interface. A ordem segue o exemplo oficial ``Film.en.sdh.srt``.
    A única exceção é pt-PT — ver ``FILENAME_LANGUAGE_OVERRIDES``.
    """
    name = base_name
    language = language_code_for_filename(language)
    if language:
        name += f".{language}"
    if hearing_impaired:
        name += ".sdh"
    if forced:
        name += ".forced"
    if default:
        name += ".default"
    return name + suffix


def has_language_code(filename: str) -> Optional[str]:
    """
    Verifica se o nome do arquivo já tem código de idioma.

    Args:
        filename: Nome do arquivo

    Returns:
        Código de idioma encontrado (normalizado para 3 letras) ou None
    """
    # Procura por padrões como .pt, .pt-BR, .pt_BR, .eng, .en, .eng2, .eng.forced, etc.
    # IMPORTANTE: Apenas ANTES da extensão do arquivo para evitar falsos positivos
    # Exemplos aceitos:
    #   "file.eng.srt" -> "eng"
    #   "file.en.srt" -> "eng"
    #   "file.eng2.srt" -> "eng"
    #   "file.eng.forced.srt" -> "eng"
    #   "file.por.srt" -> "por"
    #   "file.pt.srt" -> "por"
    #   "file.pt-BR.srt" -> "por"
    #   "file.pt_BR.srt" -> "por"
    #   "The.Great.Flood.srt" -> None (não pega "gre" de Great)

    # Delega ao parser único (que conhece TODOS os flags do Jellyfin), para
    # que scanner e renamer nunca mais discordem sobre o mesmo arquivo.
    name = Path(filename).name
    suffix = Path(name).suffix.lower()
    if suffix not in SUBTITLE_EXTENSIONS:
        return None
    return parse_subtitle_name(Path(name).stem)['language']


def get_base_name(file_path: Path) -> str:
    """
    Obtém o nome base do arquivo sem extensões de idioma e arquivo.

    Exemplo:
        "Filme.pt-BR.srt" -> "Filme"
        "Serie S01E01.mkv" -> "Serie S01E01"

    Args:
        file_path: Caminho do arquivo

    Returns:
        Nome base
    """
    name = file_path.stem

    # Remove código de idioma se presente
    name = _RE_LANG_SUFFIX.sub("", name)

    return name


def format_season_folder(season: int) -> str:
    """
    Formata nome da pasta de temporada.

    Args:
        season: Número da temporada

    Returns:
        Nome formatado (ex: "Season 01")
    """
    return f"Season {season:02d}"


def parse_subtitle_filename(file_path: Path) -> dict:
    """
    Analisa nome de arquivo de legenda e extrai informações.

    Args:
        file_path: Caminho do arquivo de legenda

    Returns:
        Dicionário com: base_name, language, flags (default, forced, sdh)
    """
    name = file_path.stem
    parts = name.split('.')

    info = {
        'base_name': parts[0],
        'language': None,
        'default': False,
        'forced': False,
        'sdh': False,
    }

    # Processa as partes do nome
    for part in parts[1:]:
        part_lower = part.lower()

        # Verifica flags
        if part_lower == 'default':
            info['default'] = True
        elif part_lower == 'forced':
            info['forced'] = True
        elif part_lower == 'sdh':
            info['sdh'] = True
        # Verifica código de idioma (2-3 letras, opcionalmente com região como pt-BR ou pt_BR)
        elif _RE_LANG_PART.match(part_lower):
            # Normaliza o código de idioma para 3 letras
            info['language'] = normalize_language_code(part_lower)

    return info


_RE_QUALITY_TAG_TRAILING = re.compile(r'\s*-\s*(2160p|1080p|720p|480p|4K).*', re.IGNORECASE)
_RE_EPISODE_DASH = re.compile(r'(.+?)\s+-\s+S(\d+)E(\d+)', re.IGNORECASE)
_RE_EPISODE_PLAIN = re.compile(r'(.+?)\s+S(\d+)E(\d+)', re.IGNORECASE)
_RE_PAREN_YEAR = re.compile(r'\((\d{4})\)')


def parse_destination_for_search(destination: Path) -> dict:
    """
    Parse a renamed destination Path into the components needed for a metadata or
    subtitle search.

    Recognized patterns:
      - "Title (YYYY) - 1080p" → movie with title + year
      - "Title (YYYY) - S01E01" or "Title S01E01" → episode (year may come from parent folder)

    Args:
        destination: Path to the planned destination file (operation.destination).

    Returns:
        Dict with keys: title (str), year (Optional[int]), is_episode (bool),
        season (Optional[int]), episode (Optional[int]).
    """
    dest_name = destination.stem
    # Strip trailing quality tags so they don't get glued onto the title.
    dest_name = _RE_QUALITY_TAG_TRAILING.sub('', dest_name)

    episode_match = _RE_EPISODE_DASH.search(dest_name) or _RE_EPISODE_PLAIN.search(dest_name)
    year_match = _RE_PAREN_YEAR.search(dest_name)

    if episode_match:
        title = normalize_spaces(episode_match.group(1).strip())
        season = int(episode_match.group(2))
        episode = int(episode_match.group(3))
        # Episodes usually omit the year — try the parent folder ("Show (YYYY)/Season XX").
        folder_year_match = _RE_PAREN_YEAR.search(str(destination.parent))
        year = int(folder_year_match.group(1)) if folder_year_match else None
        return {
            'title': title,
            'year': year,
            'is_episode': True,
            'season': season,
            'episode': episode,
        }

    if year_match:
        return {
            'title': normalize_spaces(dest_name[: year_match.start()].strip()),
            'year': int(year_match.group(1)),
            'is_episode': False,
            'season': None,
            'episode': None,
        }

    bare_year = extract_year(dest_name)

    return {
        'title': normalize_spaces(dest_name),
        'year': bare_year,
        'is_episode': False,
        'season': None,
        'episode': None,
    }


def parse_source_for_search(source: Path) -> dict:
    """Extrai título/ano/episódio a partir do arquivo ORIGINAL.

    Usa o detector de mídia sobre o nome de arquivo cru, sem passar pelo
    resultado do TMDB. É a única fonte confiável quando o match automático
    errou — que é exatamente o momento em que o usuário abre a busca manual.
    """
    from ..core.detector import detect_media_type

    media_info = detect_media_type(source)
    title = normalize_spaces(media_info.title or source.stem)

    return {
        'title': title,
        'year': media_info.year or extract_year(source.stem),
        'is_episode': media_info.is_tvshow(),
        'season': media_info.season,
        'episode': media_info.episode_start,
    }


def parse_operation_for_search(operation) -> dict:
    """Dados de busca para uma operação, preferindo o arquivo de origem.

    O destino só é usado para completar o que o nome do arquivo não tem
    (tipicamente o ANO, que vem da pasta ``Série (2004)``) — nunca para
    substituir o título lido do arquivo original.
    """
    parsed = parse_source_for_search(operation.source)
    dest_parsed = parse_destination_for_search(operation.destination)

    if not parsed['title']:
        parsed['title'] = dest_parsed['title']

    if not parsed['is_episode'] and dest_parsed['is_episode']:
        parsed['is_episode'] = True
        parsed['season'] = parsed['season'] or dest_parsed['season']
        parsed['episode'] = parsed['episode'] or dest_parsed['episode']

    # O ano do destino vem da pasta criada pelo match do TMDB. Só dá para
    # confiar nele se o título do destino de fato corresponde ao do arquivo —
    # senão herdaríamos o ano do título ERRADO (Dr. House → 2004) e a busca
    # continuaria envenenada.
    if parsed['year'] is None and _titles_agree(parsed['title'], dest_parsed['title']):
        parsed['year'] = dest_parsed['year']

    return parsed


def _titles_agree(a: str, b: str) -> bool:
    """Dois títulos se referem à mesma obra? (comparação tolerante)"""
    if not a or not b:
        return False

    def tokens(text: str) -> set:
        return {t for t in re.split(r"[^0-9a-z]+", text.lower()) if t}

    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta
