"""Scanner de arquivos e análise de bibliotecas"""

from pathlib import Path
from typing import List
from dataclasses import dataclass, field
from ..utils.helpers import (
    detect_subtitle_language, is_video_file, is_subtitle_file, is_image_file,
    is_extras_path, is_jellyfin_image, parse_subtitle_name
)
from ..utils.config import get_config
from ..utils.logger import get_logger
from .detector import detect_media_type


@dataclass
class ScanResult:
    """Resultado do scan de uma biblioteca"""

    # Arquivos encontrados
    video_files: List[Path] = field(default_factory=list)
    subtitle_files: List[Path] = field(default_factory=list)
    image_files: List[Path] = field(default_factory=list)
    other_files: List[Path] = field(default_factory=list)

    # Legendas por categoria
    variant_subtitles: List[Path] = field(default_factory=list)  # .lang2.srt, .lang3.srt, etc.
    no_lang_subtitles: List[Path] = field(default_factory=list)  # .srt sem código
    foreign_subtitles: List[Path] = field(default_factory=list)  # Idiomas estrangeiros
    kept_subtitles: List[Path] = field(default_factory=list)  # Idiomas mantidos (.por, .eng, etc.)

    # Arquivos indesejados
    unwanted_images: List[Path] = field(default_factory=list)
    nfo_files: List[Path] = field(default_factory=list)
    non_media_files: List[Path] = field(default_factory=list)  # Arquivos que não são .srt ou .mp4

    # Extras do Jellyfin (trailers, bastidores, samples...). Coletados só para
    # exibição/estatística: NUNCA entram em video_files, para não serem
    # renomeados como se fossem filmes.
    extras_files: List[Path] = field(default_factory=list)

    # Estatísticas
    total_movies: int = 0
    total_episodes: int = 0

    @property
    def total_files(self) -> int:
        """Total calculado dinamicamente após arquivos serem adicionados"""
        return (
            len(self.video_files) +
            len(self.subtitle_files) +
            len(self.image_files) +
            len(self.other_files)
        )


class LibraryScanner:
    """Scanner de bibliotecas de mídia"""

    def __init__(self):
        self.config = get_config()
        self.logger = get_logger()

    def scan(self, directory: Path) -> ScanResult:
        """
        Escaneia um diretório e categoriza os arquivos.

        Args:
            directory: Diretório a escanear

        Returns:
            ScanResult com os arquivos categorizados
        """
        result = ScanResult()

        if not directory.exists() or not directory.is_dir():
            return result

        # Escaneia recursivamente (lazy — não materializa toda a árvore em memória)
        for file_path in self._iter_files(directory):
            # Hidden files (starting with '.') are only collected for removal
            if file_path.name.startswith('.'):
                if self.config.remove_non_media:
                    result.other_files.append(file_path)
                    result.non_media_files.append(file_path)
                continue

            # Extras do Jellyfin ficam de fora de QUALQUER operação: não são
            # filmes, não são lixo e não podem sair da pasta da mídia.
            if is_extras_path(file_path):
                result.extras_files.append(file_path)
                continue

            # Categoriza por tipo
            if is_video_file(file_path):
                result.video_files.append(file_path)

                # Detecta tipo de mídia
                media_info = detect_media_type(file_path)
                if media_info.is_movie():
                    result.total_movies += 1
                elif media_info.is_tvshow():
                    result.total_episodes += 1

            elif is_subtitle_file(file_path):
                # Ignora legendas vazias ou muito pequenas
                if file_path.stat().st_size < self.config.min_subtitle_bytes:
                    continue

                result.subtitle_files.append(file_path)
                self._categorize_subtitle(file_path, result)

            elif is_image_file(file_path):
                result.image_files.append(file_path)
                self._categorize_image(file_path, result)
                # remove_non_media é explícito ("manter só vídeos/legendas") e
                # vem desligado por padrão — então respeita a escolha do
                # usuário e inclui as imagens. O que mudou foi a CLASSIFICAÇÃO
                # em unwanted_images (ver _categorize_image), que antes
                # marcava cover.jpg/folder.jpg como indesejados.
                if self.config.remove_non_media:
                    result.non_media_files.append(file_path)

            elif file_path.suffix.lower() == '.nfo':
                result.nfo_files.append(file_path)
                # Marca NFO como non-media se configurado
                if self.config.remove_non_media:
                    result.non_media_files.append(file_path)

            else:
                result.other_files.append(file_path)
                # Marca arquivos que não são vídeos ou legendas para possível remoção
                if self.config.remove_non_media:
                    result.non_media_files.append(file_path)

        return result

    def _iter_files(self, directory: Path):
        """Percorre a árvore devolvendo apenas arquivos, tolerando erros de I/O.

        Um único diretório sem permissão (ou link simbólico quebrado) derrubava
        o scan inteiro com OSError.
        """
        try:
            entries = directory.rglob('*')
        except OSError as e:
            self.logger.warning(f"Não foi possível ler {directory}: {e}")
            return

        while True:
            try:
                file_path = next(entries)
            except StopIteration:
                return
            except OSError as e:
                self.logger.debug(f"Ignorando entrada ilegível: {e}")
                continue

            try:
                if not file_path.is_file():
                    continue
            except OSError:
                continue

            yield file_path

    def _categorize_subtitle(self, file_path: Path, result: ScanResult):
        """Categoriza um arquivo de legenda"""
        info = parse_subtitle_name(file_path.stem)
        lang_code = info['language']

        # .forced nunca é removida nem reclassificada (regra do projeto)
        if info['forced']:
            result.kept_subtitles.append(file_path)
            return

        # Variações (.por2.srt, .eng3.ass) de QUALQUER idioma e extensão
        if info['variant'] is not None:
            result.variant_subtitles.append(file_path)
            return

        if lang_code:
            if lang_code in self.config.kept_languages:
                result.kept_subtitles.append(file_path)
            else:
                result.foreign_subtitles.append(file_path)
        else:
            # Untagged subtitles are only actionable when content detection is
            # confident and the language is configured to be kept.
            detected_language = detect_subtitle_language(
                file_path,
                min_portuguese_words=self.config.min_pt_words,
            )
            if detected_language in self.config.kept_languages:
                result.no_lang_subtitles.append(file_path)
            else:
                # Sem código e sem detecção: idioma DESCONHECIDO, não
                # "estrangeiro". Marcá-la como estrangeira fazia a interface
                # contar legendas em inglês como candidatas a remoção.
                result.other_files.append(file_path)

    def _categorize_image(self, file_path: Path, result: ScanResult):
        """Categoriza um arquivo de imagem"""
        if not is_jellyfin_image(file_path):
            result.unwanted_images.append(file_path)


def scan_library(directory: Path) -> ScanResult:
    """
    Escaneia uma biblioteca de mídia.

    Args:
        directory: Diretório da biblioteca

    Returns:
        Resultado do scan
    """
    scanner = LibraryScanner()
    return scanner.scan(directory)
