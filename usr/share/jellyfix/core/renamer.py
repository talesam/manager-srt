"""Sistema de renomeação de arquivos para padrão Jellyfin"""

from pathlib import Path
from typing import Optional, List, Dict
from dataclasses import dataclass
import re
import shutil

from ..utils.helpers import (
    clean_filename, normalize_spaces, extract_year,
    detect_subtitle_language, format_season_folder, is_extras_path,
    parse_subtitle_name, build_subtitle_name,
    is_video_file, is_subtitle_file, calculate_subtitle_quality, extract_quality_tag, detect_video_resolution
)
from ..utils.config import get_config
from ..utils.logger import get_logger
from .detector import detect_media_type
from .metadata import MetadataFetcher


@dataclass
class RenameOperation:
    """Representa uma operação de renomeação"""
    source: Path
    destination: Path
    operation_type: str  # 'rename', 'move', 'delete'
    reason: str

    @property
    def will_overwrite(self) -> bool:
        """Verifica se vai sobrescrever um arquivo existente"""
        return self.destination.exists() and self.source != self.destination


class Renamer:
    """Gerenciador de renomeação de arquivos"""

    def __init__(self, metadata_fetcher: Optional[MetadataFetcher] = None):
        self.config = get_config()
        self.logger = get_logger()
        self.operations: List[RenameOperation] = []
        # Usa o metadata_fetcher fornecido (com cache de escolhas) ou cria novo
        if metadata_fetcher:
            self.metadata_fetcher = metadata_fetcher
        else:
            self.metadata_fetcher = MetadataFetcher() if self.config.fetch_metadata else None

    def _is_workdir_media_folder(self, *titles: str) -> bool:
        """Check if work_dir name matches any of the given titles (not a generic container).

        Compares using case-insensitive substring match.  Accepts both the
        original filename-derived title and the TMDB title so that translated
        names don't cause false negatives.
        """
        # normalize dots/underscores → spaces so "The.Crown.S03..." matches "The Crown"
        folder_name = normalize_spaces(self.work_dir.name).lower()
        for t in titles:
            if t and t.lower() in folder_name:
                return True
        return False

    def plan_operations(self, directory: Path, scan_result=None) -> List[RenameOperation]:
        """
        Planeja todas as operações de renomeação.

        Args:
            directory: Diretório a processar
            scan_result: ScanResult opcional (se fornecido, usa arquivos filtrados; caso contrário, escaneia o diretório)

        Returns:
            Lista de operações planejadas
        """
        self.operations = []
        self.planned_destinations = set()  # Rastreia destinos para evitar conflitos
        self.video_operations_map = {}  # Mapa: video_stem -> operação de vídeo
        self.work_dir = directory.resolve()  # Working directory for organizing files

        # Coleta todos os arquivos de legendas para processamento inteligente
        subtitle_files = []
        video_files = []

        if scan_result:
            # Usa arquivos do ScanResult filtrado
            self.logger.debug(
                f"Using filtered ScanResult - videos: {len(scan_result.video_files)}, subtitles: {len(scan_result.subtitle_files)}"
            )
            video_files = scan_result.video_files
            subtitle_files = scan_result.subtitle_files
        else:
            # Escaneia o diretório normalmente
            for file_path in directory.rglob('*'):
                if not file_path.is_file():
                    continue

                if file_path.name.startswith('.'):
                    continue

                # Extras do Jellyfin (trailer.mp4, behind the scenes/, ...)
                # não são mídia principal e não podem ser reorganizados.
                if is_extras_path(file_path):
                    continue

                # Processa vídeos
                if is_video_file(file_path):
                    video_files.append(file_path)

                # Processa legendas
                elif is_subtitle_file(file_path):
                    # Ignora legendas vazias ou muito pequenas
                    if file_path.stat().st_size < self.config.min_subtitle_bytes:
                        continue
                    subtitle_files.append(file_path)

        # Processa arquivos Mirabel se configurado (ANTES de processar vídeos)
        if self.config.fix_mirabel_files:
            subtitle_files = self._plan_mirabel_fixes(subtitle_files)

        # Processa vídeos
        for file_path in video_files:
            self._plan_video_rename(file_path)

        # Processa legendas que acompanham vídeos (move/renomeia junto)
        # Retorna lista de legendas já processadas
        processed_subtitles = self._plan_subtitle_companion(subtitle_files, video_files)

        # Processa legendas de forma inteligente (variações de idioma)
        # Exclui as que já foram processadas
        remaining_subtitles = [s for s in subtitle_files if s not in processed_subtitles]
        self._plan_subtitle_variants(remaining_subtitles, directory)

        # Remove arquivos não-mídia se configurado (ANTES de processar extras)
        if self.config.remove_non_media and scan_result and scan_result.non_media_files:
            self._plan_non_media_removal(scan_result.non_media_files)

        # Processa arquivos extras (NFO, imagens, etc) que devem acompanhar os vídeos
        self._plan_extra_files(directory, video_files, scan_result)

        return self.operations

    def replan_for_video_with_metadata(
        self, video_path: Path, metadata, work_dir: Optional[Path] = None
    ) -> List[RenameOperation]:
        """
        Re-planeja operações para um vídeo específico usando novo metadata fornecido manualmente.
        Retorna lista de novas operações que devem substituir as antigas.

        Args:
            video_path: Caminho do arquivo de vídeo original
            metadata: Novo metadata selecionado manualmente (objeto Metadata)
            work_dir: Raiz da biblioteca (mesma usada no plano original). Sem ela,
                um episódio dentro de "Season 01/" acabava recriando a pasta da
                série DENTRO da pasta de temporada.

        Returns:
            Lista de novas operações (vídeo + legendas + extras) que substituirão as antigas
        """
        from ..utils.helpers import normalize_spaces, is_subtitle_file
        import re

        # Inicializa variáveis de controle
        self.operations = []
        self.planned_destinations = set()
        self.video_operations_map = {}
        self.work_dir = Path(work_dir).resolve() if work_dir else video_path.parent.resolve()

        # Detecta tipo de mídia pelo nome do arquivo (fallback)
        media_info = detect_media_type(video_path)

        # Quando o metadata traz media_type explícito (escolha manual do usuário),
        # ele tem prioridade sobre a detecção por filename — caso contrário um filme
        # com "2" no título pode bater com um padrão de episódio.
        if metadata.media_type == "movie":
            new_video_op = self._plan_movie_rename_with_metadata(video_path, media_info, metadata)
        elif metadata.media_type == "tvshow":
            new_video_op = self._plan_tvshow_rename_with_metadata(video_path, media_info, metadata)
        elif media_info.is_movie():
            new_video_op = self._plan_movie_rename_with_metadata(video_path, media_info, metadata)
        elif media_info.is_tvshow():
            new_video_op = self._plan_tvshow_rename_with_metadata(video_path, media_info, metadata)
        else:
            return []  # Não é filme nem série, não faz nada

        if not new_video_op:
            return []

        # Encontra todos os arquivos relacionados ao vídeo original
        video_stem_original = video_path.stem
        video_normalized = normalize_spaces(video_stem_original)
        related_files = []

        # Busca legendas, NFO, e outros arquivos relacionados no mesmo diretório
        for file_path in video_path.parent.iterdir():
            if not file_path.is_file():
                continue
            if file_path == video_path:
                continue

            # Verifica se o arquivo está relacionado ao vídeo (mesmo base name)
            file_stem = file_path.stem

            # Para legendas, remove código de idioma antes de comparar
            if is_subtitle_file(file_path):
                base_match = re.match(r'(.+?)\.([a-z]{2,3}\d?)(\.forced)?$', file_stem, re.IGNORECASE)
                if base_match:
                    file_base = base_match.group(1)
                else:
                    file_base = file_stem

                if normalize_spaces(file_base) == video_normalized or file_base == video_stem_original:
                    related_files.append(file_path)

            # Para NFO e outros, compara nome completo
            elif file_path.suffix.lower() in ['.nfo', '.jpg', '.png', '.jpeg']:
                if normalize_spaces(file_stem) == video_normalized or file_stem == video_stem_original:
                    related_files.append(file_path)

        # Coleta TODOS os arquivos extras da pasta (Jellyfin convention: backdrop.jpg, folder.jpg, etc.)
        # que não correspondem ao stem do vídeo mas devem acompanhar a mudança de pasta
        from ..utils.helpers import is_video_file

        folder_extras = []
        for file_path in video_path.parent.iterdir():
            if not file_path.is_file():
                continue
            if file_path == video_path:
                continue
            if file_path.name.startswith("."):
                continue
            if is_video_file(file_path) or is_subtitle_file(file_path):
                continue
            if file_path in related_files:
                continue
            folder_extras.append(file_path)

        # Separa por tipo
        subtitle_files = [f for f in related_files if is_subtitle_file(f)]
        nfo_files = [f for f in related_files if f.suffix.lower() == '.nfo']
        image_files = [f for f in related_files if f.suffix.lower() in ['.jpg', '.png', '.jpeg']]

        # Configura mapa de operações de vídeo para _plan_subtitle_companion
        self.video_operations_map[video_stem_original] = new_video_op
        self.video_operations_map[video_normalized] = new_video_op

        # Planeja legendas companheiras (remove estrangeiras, renomeia)
        processed_subs = self._plan_subtitle_companion(subtitle_files, [video_path])

        # Planeja variantes de legendas (escolhe melhor qualidade, remove duplicadas)
        remaining_subs = [s for s in subtitle_files if s not in processed_subs]
        if remaining_subs:
            self._plan_subtitle_variants(remaining_subs, video_path.parent)

        # Planeja arquivos NFO
        if nfo_files and self.config.rename_nfo:
            new_video_stem = new_video_op.destination.stem
            new_video_folder = new_video_op.destination.parent

            for nfo_path in nfo_files:
                new_nfo_name = f"{new_video_stem}.nfo"
                new_nfo_path = new_video_folder / new_nfo_name

                if new_nfo_path != nfo_path:
                    pasta_mudou = new_nfo_path.parent != nfo_path.parent
                    nome_mudou = new_nfo_path.name != nfo_path.name

                    if pasta_mudou and nome_mudou:
                        op_type = 'move_rename'
                    elif pasta_mudou:
                        op_type = 'move'
                    else:
                        op_type = 'rename'

                    self.operations.append(RenameOperation(
                        source=nfo_path,
                        destination=new_nfo_path,
                        operation_type=op_type,
                        reason=f"Acompanhar vídeo: {nfo_path.name} → {new_nfo_name}"
                    ))

        # Planeja arquivos de imagem (com mesmo stem do vídeo)
        if image_files:
            new_video_folder = new_video_op.destination.parent

            for img_path in image_files:
                new_img_path = new_video_folder / img_path.name

                if new_img_path != img_path and new_img_path.parent != img_path.parent:
                    self.operations.append(RenameOperation(
                        source=img_path,
                        destination=new_img_path,
                        operation_type='move',
                        reason="Acompanhar vídeo"
                    ))

        # Handle extras (backdrop.jpg, folder.jpg, logo.png, movie.nfo, etc.)
        # that don't match video stem but belong to the same folder
        new_video_folder = new_video_op.destination.parent
        if new_video_folder != video_path.parent:
            planned_sources = {op.source for op in self.operations}

            # Extras do Jellyfin (trailer.mp4, behind the scenes/...) também
            # precisam migrar na correção manual, senão ficam órfãos na pasta
            # antiga — mesmo caso do planejamento normal. O helper já se protege
            # sozinho contra pastas contêiner.
            self._plan_extras_following_video(
                video_path.parent, new_video_folder, planned_sources
            )
            for extra_path in folder_extras:
                if extra_path in planned_sources:
                    continue
                if self.config.remove_non_media:
                    # Non-media files should be deleted, not moved
                    self.operations.append(
                        RenameOperation(
                            source=extra_path,
                            destination=extra_path,
                            operation_type="delete",
                            reason=f"Remover arquivo não-mídia: {extra_path.suffix}",
                        )
                    )
                else:
                    new_extra_path = new_video_folder / extra_path.name
                    if new_extra_path.exists() and new_extra_path != extra_path:
                        continue
                    self.operations.append(
                        RenameOperation(
                            source=extra_path,
                            destination=new_extra_path,
                            operation_type="move",
                            reason=f"Mover arquivo extra junto com vídeo: {extra_path.name}",
                        )
                    )

        return self.operations

    def _plan_movie_rename_with_metadata(self, file_path: Path, media_info, metadata) -> Optional[RenameOperation]:
        """
        Planeja renomeação de filme usando metadata fornecido (não busca TMDB).
        Retorna a operação planejada ou None.
        """
        title = clean_filename(metadata.title)
        year = metadata.year

        # Build folder suffix with TMDB ID
        folder_suffix = ""
        if metadata.tmdb_id:
            folder_suffix = f" [tmdbid-{metadata.tmdb_id}]"
        elif metadata.imdb_id:
            folder_suffix = f" [imdbid-{metadata.imdb_id}]"

        # Detect quality tag
        quality_tag = None
        if self.config.add_quality_tag:
            quality_tag = extract_quality_tag(file_path.stem)
            if not quality_tag and self.config.use_ffprobe:
                quality_tag = detect_video_resolution(file_path)

        # Build new name
        if year:
            base_name = f"{title} ({year})"
        else:
            base_name = f"{title}"

        if quality_tag:
            new_name = f"{base_name} - {quality_tag}{file_path.suffix}"
        else:
            new_name = f"{base_name}{file_path.suffix}"

        # Expected folder name
        expected_folder = f"{base_name}{folder_suffix}"

        # Determine if we need to organize into folders
        if self.config.organize_folders:
            # Check current location
            parent_folder = file_path.parent

            if parent_folder.name != expected_folder:
                # Determine if work_dir is a media folder or a container folder
                if parent_folder.resolve() == self.work_dir:
                    # Files are directly in work_dir
                    original_title = media_info.title if media_info else None
                    tmdb_original = metadata.original_title if metadata else None
                    if self._is_workdir_media_folder(original_title, title, tmdb_original):
                        # Work dir IS the media folder (e.g., "Avatar (2009)/")
                        # Create sibling folder (effectively renaming)
                        new_folder = self.work_dir.parent / expected_folder
                    else:
                        # Work dir is a container (e.g., "Filmes/")
                        # Create subfolder inside work_dir
                        new_folder = self.work_dir / expected_folder
                else:
                    new_folder = self.work_dir / expected_folder
            else:
                # Already in correct folder
                new_folder = parent_folder
        else:
            # Don't organize folders, keep in current location
            new_folder = file_path.parent

        new_path = new_folder / new_name

        if new_path != file_path:
            pasta_mudou = new_path.parent != file_path.parent
            nome_mudou = new_path.name != file_path.name

            if pasta_mudou and nome_mudou:
                op_type = 'move_rename'
            elif pasta_mudou:
                op_type = 'move'
            else:
                op_type = 'rename'

            op = RenameOperation(
                source=file_path,
                destination=new_path,
                operation_type=op_type,
                reason=f"Atualização manual: {metadata.title} ({metadata.year})"
            )
            self.operations.append(op)
            return op

        return None

    def _resolve_season_episode(self, file_path: Path, media_info):
        """
        Resolve (season, episode_start, episode_end) para um episódio.

        Necessário porque, na escolha manual pelo SearchDialog, o usuário pode
        marcar como série um arquivo cujo nome não tem padrão SxxExx — aí
        media_info.season/episode_start vêm None. Tenta pasta de temporada e
        padrões soltos (Ep 5, Cap. 5, E05) antes de desistir.

        Returns:
            Tupla (season, ep_start, ep_end) ou None se não for possível deduzir.
        """
        season = media_info.season if media_info else None
        ep_start = media_info.episode_start if media_info else None
        ep_end = media_info.episode_end if media_info else None

        stem = file_path.stem

        # Temporada pela pasta pai ("Season 02", "Temporada 2")
        if season is None:
            for folder in (file_path.parent, file_path.parent.parent):
                name = folder.name.lower()
                if name.startswith(('season', 'temporada')):
                    match = re.search(r'(\d+)', name)
                    if match:
                        season = int(match.group(1))
                        break

        # Episódio por padrões soltos, sem número de temporada no nome
        if ep_start is None:
            loose = re.search(
                r'(?:^|[\s._\-\[(])'
                r'(?:e|ep|epis[oó]dio|episode|cap|cap[ií]tulo)\s*\.?\s*'
                r'(\d{1,3})(?:\s*[\-–]\s*(?:e|ep)?\s*(\d{1,3}))?'
                r'(?=$|[\s._\-\])])',
                stem,
                re.IGNORECASE,
            )
            if loose:
                ep_start = int(loose.group(1))
                ep_end = int(loose.group(2)) if loose.group(2) else ep_start

        # Último recurso: número solto no nome, só quando o arquivo já está numa
        # pasta de temporada (contexto suficiente para confiar no número).
        if ep_start is None and file_path.parent.name.lower().startswith(('season', 'temporada')):
            candidates = [
                int(n) for n in re.findall(r'(?<!\d)(\d{1,3})(?!\d)', stem)
                if not (1900 <= int(n) <= 2099)
            ]
            if candidates:
                ep_start = candidates[0]
                ep_end = ep_start

        if ep_start is None:
            return None

        # Sem temporada explícita, assume 1 — convenção do Jellyfin para séries
        # de temporada única.
        if season is None:
            season = 1
        if ep_end is None or ep_end < ep_start:
            ep_end = ep_start

        return (season, ep_start, ep_end)

    def _plan_tvshow_rename_with_metadata(self, file_path: Path, media_info, metadata) -> Optional[RenameOperation]:
        """
        Planeja renomeação de série usando metadata fornecido (não busca TMDB).
        Retorna a operação planejada ou None.
        """
        se_info = self._resolve_season_episode(file_path, media_info)
        if se_info is None:
            self.logger.warning(
                f"✗ Não foi possível identificar temporada/episódio em '{file_path.name}'; "
                "renomeação de série ignorada"
            )
            return None
        season, episode_start, episode_end = se_info

        title = clean_filename(metadata.title)
        year = metadata.year

        # Build folder suffix with TMDB ID
        folder_suffix = ""
        if metadata.tmdb_id:
            folder_suffix = f" [tmdbid-{metadata.tmdb_id}]"
        elif metadata.tvdb_id:
            folder_suffix = f" [tvdbid-{metadata.tvdb_id}]"
        elif metadata.imdb_id:
            folder_suffix = f" [imdbid-{metadata.imdb_id}]"

        # Format episode part
        if episode_end != episode_start:
            episode_part = f"S{season:02d}E{episode_start:02d}-E{episode_end:02d}"
        else:
            episode_part = f"S{season:02d}E{episode_start:02d}"

        new_name = f"{title} - {episode_part}{file_path.suffix}"

        # Determine series folder structure
        season_folder_name = format_season_folder(season)

        # Find series folder
        if file_path.parent.name.lower().startswith('season'):
            series_folder = file_path.parent.parent
        else:
            series_folder = file_path.parent

        # Expected series folder name
        if year:
            expected_series_folder = f"{title} ({year}){folder_suffix}"
        else:
            expected_series_folder = f"{title}{folder_suffix}"

        # Determine new series folder path
        if series_folder.name != expected_series_folder:
            # Determine if work_dir is a media folder or a container folder
            if series_folder.resolve() == self.work_dir:
                # Series folder IS the work_dir
                original_title = media_info.title if media_info else None
                tmdb_original = metadata.original_title if metadata else None
                if self._is_workdir_media_folder(original_title, title, tmdb_original):
                    # Work dir IS the series folder (e.g., "Breaking Bad (2008)/")
                    new_series_folder = self.work_dir.parent / expected_series_folder
                else:
                    # Work dir is a container
                    new_series_folder = self.work_dir / expected_series_folder
            else:
                new_series_folder = self.work_dir / expected_series_folder
        else:
            new_series_folder = series_folder

        # Full path
        new_folder = new_series_folder / season_folder_name
        new_path = new_folder / new_name

        if new_path != file_path:
            pasta_mudou = new_path.parent != file_path.parent
            nome_mudou = new_path.name != file_path.name

            if pasta_mudou and nome_mudou:
                op_type = 'move_rename'
            elif pasta_mudou:
                op_type = 'move'
            else:
                op_type = 'rename'

            if new_series_folder != series_folder:
                reason = f"Atualização manual: {series_folder.name} → {expected_series_folder}"
            else:
                reason = f"Atualização manual: {file_path.name} → {new_name}"

            op = RenameOperation(
                source=file_path,
                destination=new_path,
                operation_type=op_type,
                reason=reason
            )
            self.operations.append(op)
            return op

        return None

    def _plan_video_rename(self, file_path: Path):
        """Planeja renomeação de um arquivo de vídeo"""
        media_info = detect_media_type(file_path)

        # TRAVA ANTI-MISCLASSIFICAÇÃO: se a pasta tem [tmdbid-N] fixado, é um
        # filme já identificado — força o caminho de filme mesmo que o detector
        # ache "série" por causa de número no nome (ex.: "Grease 2" virava
        # S02E02 e ia parar dentro de uma série). O id fixado é a fonte da
        # verdade. (Não vale para pastas com subpastas Season, que são séries
        # de verdade — essas têm o arquivo dentro de uma pasta Season/Temporada.)
        in_season_folder = file_path.parent.name.lower().startswith(("season", "temporada"))
        if self._extract_pinned_tmdbid(file_path) is not None and not in_season_folder:
            self._plan_movie_rename(file_path, media_info)
            return

        if media_info.is_movie():
            self._plan_movie_rename(file_path, media_info)
        elif media_info.is_tvshow():
            self._plan_tvshow_rename(file_path, media_info)

    @staticmethod
    def _extract_pinned_tmdbid(file_path: Path) -> Optional[int]:
        """Extrai um tmdbid fixado na pasta-pai (ex.: 'Filme (2020) [tmdbid-603]').

        Verifica também a pasta avó, caso o arquivo esteja um nível abaixo.
        Retorna o id como int, ou None se não houver.
        """
        import re as _re
        for parent in (file_path.parent, file_path.parent.parent):
            try:
                m = _re.search(r"\[tmdbid-(\d+)\]", parent.name)
            except Exception:
                m = None
            if m:
                return int(m.group(1))
        return None

    def _plan_movie_rename(self, file_path: Path, media_info):
        """Plan movie file rename"""
        # Extract information
        original_title = clean_filename(normalize_spaces(media_info.title or file_path.stem))
        title = original_title
        year = extract_year(file_path.stem)

        if not title:
            return

        # Fetch metadata if configured
        folder_suffix = ""
        metadata = None
        if self.metadata_fetcher and self.config.fetch_metadata:
            # IDEMPOTÊNCIA / CORREÇÃO MANUAL: se a pasta já tem [tmdbid-N],
            # confia nesse id (busca direta) em vez de re-pesquisar por título.
            # Evita "consertar" uma pasta certa pro id errado e respeita ids
            # corrigidos na mão; também é mais rápido.
            pinned_id = self._extract_pinned_tmdbid(file_path)
            if pinned_id is not None:
                self.logger.info(f"📌 ID fixado na pasta: tmdbid-{pinned_id} (pulando busca)")
                metadata = self.metadata_fetcher.get_movie_by_id(pinned_id)
                if not metadata:
                    self.logger.warning(f"✗ tmdbid-{pinned_id} não resolveu; caindo p/ busca por título")
            if metadata is None:
                self.logger.info(f"🔍 Searching: {title}")
                metadata = self.metadata_fetcher.search_movie(title, year, interactive=self.config.interactive)

            if metadata:
                # Use title and year from metadata
                title = clean_filename(metadata.title)
                year = metadata.year or year

                # Add provider ID
                if metadata.tmdb_id:
                    folder_suffix = f" [tmdbid-{metadata.tmdb_id}]"
                elif metadata.imdb_id:
                    folder_suffix = f" [imdbid-{metadata.imdb_id}]"

                self.logger.info(f"✓ Found: {title} ({year}) [ID: {metadata.tmdb_id}]")
            else:
                self.logger.warning(f"✗ Not found: {title}")

        # Detect quality tag
        quality_tag = None
        if self.config.add_quality_tag:
            # First try to extract from filename
            quality_tag = extract_quality_tag(file_path.stem)

            # If not found and ffprobe is enabled, detect from video
            if not quality_tag and self.config.use_ffprobe:
                quality_tag = detect_video_resolution(file_path)

        # Jellyfin format: "Movie Name (YYYY) - 1080p.ext" or "Movie Name (YYYY).ext"
        if year:
            base_name = f"{title} ({year})"
        else:
            base_name = f"{title}"

        if quality_tag:
            new_name = f"{base_name} - {quality_tag}{file_path.suffix}"
        else:
            new_name = f"{base_name}{file_path.suffix}"

        # Check if in correct folder
        parent_folder = file_path.parent.name
        expected_folder = f"{title} ({year}){folder_suffix}" if year else f"{title}{folder_suffix}"

        # Define destination
        if parent_folder != expected_folder:
            # Determine if work_dir is a media folder or a container folder
            if file_path.parent.resolve() == self.work_dir:
                # Files are directly in work_dir
                tmdb_original = metadata.original_title if metadata else None
                if self._is_workdir_media_folder(original_title, title, tmdb_original):
                    # Work dir IS the media folder (e.g., "Avatar (2009)/")
                    # Create sibling folder (effectively renaming)
                    new_folder = self.work_dir.parent / expected_folder
                else:
                    # Work dir is a container (e.g., "Filmes/")
                    # Create subfolder inside work_dir
                    new_folder = self.work_dir / expected_folder
            else:
                new_folder = self.work_dir / expected_folder
            new_path = new_folder / new_name
        else:
            # Just rename
            new_path = file_path.parent / new_name

        if new_path != file_path:
            # Detect operation type precisely
            folder_changed = new_path.parent != file_path.parent
            name_changed = new_path.name != file_path.name

            if folder_changed and name_changed:
                op_type = 'move_rename'
            elif folder_changed:
                op_type = 'move'
            else:
                op_type = 'rename'

            self.operations.append(RenameOperation(
                source=file_path,
                destination=new_path,
                operation_type=op_type,
                reason=f"Standardize movie name: {file_path.name} → {new_name}"
            ))

    def _plan_tvshow_rename(self, file_path: Path, media_info):
        """Planeja renomeação de um episódio de série"""
        if media_info.season is None or media_info.episode_start is None:
            return

        original_title = clean_filename(normalize_spaces(media_info.title or file_path.stem))
        title = original_title

        if not title:
            return

        # Busca metadados se configurado
        folder_suffix = ""
        year = None
        metadata = None
        if self.metadata_fetcher and self.config.fetch_metadata:
            # IDEMPOTÊNCIA: se a pasta da série já tem [tmdbid-N] (inclusive
            # depois de uma correção manual do usuário), confia nesse id em vez
            # de re-pesquisar pelo título — senão a correção era desfeita na
            # execução seguinte.
            pinned_id = self._extract_pinned_tmdbid(file_path)
            if pinned_id is not None:
                self.logger.info(f"📌 ID fixado na pasta: tmdbid-{pinned_id} (pulando busca)")
                metadata = self.metadata_fetcher.get_tvshow_by_id(pinned_id)
                if not metadata:
                    self.logger.warning(f"✗ tmdbid-{pinned_id} não resolveu; caindo p/ busca por título")

            if metadata is None:
                # O ano ajuda a desempatar séries homônimas; vem do nome do
                # arquivo ou da pasta da série.
                search_year = extract_year(file_path.stem) or extract_year(file_path.parent.name) \
                    or extract_year(file_path.parent.parent.name)
                self.logger.info(f"🔍 Buscando série: {title}")
                metadata = self.metadata_fetcher.search_tvshow(
                    title, year=search_year, interactive=self.config.interactive
                )

            if metadata:
                # Usa título dos metadados
                title = clean_filename(metadata.title)
                year = metadata.year

                # Adiciona ID do provedor
                if metadata.tmdb_id:
                    folder_suffix = f" [tmdbid-{metadata.tmdb_id}]"
                elif metadata.tvdb_id:
                    folder_suffix = f" [tvdbid-{metadata.tvdb_id}]"
                elif metadata.imdb_id:
                    folder_suffix = f" [imdbid-{metadata.imdb_id}]"
                self.logger.info(f"✓ Encontrado: {title} ({year}) [ID: {metadata.tmdb_id}]")
            else:
                self.logger.warning(f"✗ Não encontrado: {title}")

        # Jellyfin format: "Series Name - S01E01.ext"
        # Ref: https://jellyfin.org/docs/general/server/media/shows
        if media_info.episode_end and media_info.episode_end != media_info.episode_start:
            episode_part = f"S{media_info.season:02d}E{media_info.episode_start:02d}-E{media_info.episode_end:02d}"
        else:
            episode_part = f"S{media_info.season:02d}E{media_info.episode_start:02d}"

        new_name = f"{title} - {episode_part}{file_path.suffix}"

        # Verifica estrutura de pastas
        # Esperado: SeriesFolder/Season XX/episode.mkv
        season_folder_name = format_season_folder(media_info.season)

        # Encontra a pasta da série
        if file_path.parent.name.lower().startswith('season'):
            # Já está em uma pasta de temporada
            series_folder = file_path.parent.parent
        else:
            # Não está em pasta de temporada
            series_folder = file_path.parent

        # Define o nome esperado da pasta da série (com ano e ID se encontrado metadados)
        if year:
            expected_series_folder = f"{title} ({year}){folder_suffix}"
        else:
            expected_series_folder = f"{title}{folder_suffix}"


        # Verifica se a pasta da série precisa ser renomeada
        if series_folder.name != expected_series_folder:
            # Determine if work_dir is a media folder or a container folder
            if series_folder.resolve() == self.work_dir:
                # Series folder IS the work_dir
                tmdb_original = metadata.original_title if metadata else None
                if self._is_workdir_media_folder(original_title, title, tmdb_original):
                    # Work dir IS the series folder
                    new_series_folder = self.work_dir.parent / expected_series_folder
                else:
                    # Work dir is a container
                    new_series_folder = self.work_dir / expected_series_folder
            else:
                new_series_folder = self.work_dir / expected_series_folder
        else:
            new_series_folder = series_folder

        # Define o caminho completo do arquivo
        new_folder = new_series_folder / season_folder_name
        new_path = new_folder / new_name

        if new_path != file_path:
            # Detecta o tipo de operação com mais precisão
            pasta_mudou = new_path.parent != file_path.parent
            nome_mudou = new_path.name != file_path.name

            if pasta_mudou and nome_mudou:
                op_type = 'move_rename'
            elif pasta_mudou:
                op_type = 'move'
            else:
                op_type = 'rename'

            # Se mudou a pasta da série, inclui isso na razão
            if new_series_folder != series_folder:
                reason = f"Organizar com metadados: {series_folder.name} → {expected_series_folder}"
            else:
                reason = f"Padronizar episódio: {file_path.name} → {new_name}"

            self.operations.append(RenameOperation(
                source=file_path,
                destination=new_path,
                operation_type=op_type,
                reason=reason
            ))

    def _plan_subtitle_companion(self, subtitle_files: List[Path], video_files: List[Path]) -> List[Path]:
        """
        Processa legendas que acompanham vídeos.
        Quando um vídeo é movido/renomeado, a legenda correspondente também é.
        Legendas de idiomas estrangeiros são marcadas para DELETE se configurado.

        Returns:
            Lista de legendas que foram processadas
        """
        processed_subtitles = []

        # Cria mapa de vídeos por base name (normalizado para matching)
        video_operations = {}
        video_file_set = set(video_files)  # lookup O(1) — era O(n) por operação
        for op in self.operations:
            if op.source in video_file_set:
                # Normaliza o nome do vídeo para fazer matching
                video_stem = op.source.stem
                video_normalized = normalize_spaces(video_stem)
                video_operations[video_normalized] = op
                # Também guarda pela chave exata para matching direto
                video_operations[video_stem] = op
        
        # Armazena para uso em _plan_subtitle_variants
        self.video_operations_map = video_operations

        # Processa cada legenda
        for subtitle_path in subtitle_files:
            # Verifica se é arquivo Mirabel (já identificado em _plan_mirabel_fixes)
            mirabel_data = getattr(self, 'mirabel_info', {}).get(subtitle_path)

            if mirabel_data:
                # Usa informações do Mirabel
                subtitle_base = mirabel_data['base_name']
                lang_code_base = mirabel_data['target_lang']
                is_variant = False
                is_forced = mirabel_data['forced']
                is_hearing_impaired = mirabel_data['hearing_impaired']
            else:
                # Parser único (helpers.parse_subtitle_name): conhece os flags
                # do Jellyfin (default/forced/foreign/sdh/cc/hi) e nunca os
                # confunde com código de idioma.
                info = parse_subtitle_name(subtitle_path.stem)
                subtitle_base = info['base_name']
                lang_code_base = info['language']
                is_variant = info['variant'] is not None
                is_forced = info['forced']
                is_hearing_impaired = info['hearing_impaired']

                # Forced subtitles do not enter variant processing, so attach a
                # confidently detected kept language here.
                if lang_code_base is None and is_forced and self.config.rename_no_lang:
                    detected_language = detect_subtitle_language(
                        subtitle_path,
                        min_portuguese_words=self.config.min_pt_words,
                    )
                    if detected_language in self.config.kept_languages:
                        lang_code_base = detected_language

            # Procura vídeo correspondente (primeiro tenta match exato, depois normalizado)
            matching_video_op = video_operations.get(subtitle_base)

            if not matching_video_op:
                # Tenta matching normalizado (mais flexível)
                subtitle_normalized = normalize_spaces(subtitle_base)
                matching_video_op = video_operations.get(subtitle_normalized)

            if matching_video_op:
                # Encontrou vídeo correspondente que será movido/renomeado

                # VERIFICA SE É IDIOMA ESTRANGEIRO (NÃO está na lista de mantidos)
                # .forced nunca é removida (regra do projeto).
                is_foreign = False
                if lang_code_base and self.config.remove_foreign_subs and not is_forced:
                    is_foreign = lang_code_base not in self.config.kept_languages

                if is_foreign:
                    # Legenda estrangeira - marcar como processada e DELETE
                    processed_subtitles.append(subtitle_path)
                    self.operations.append(RenameOperation(
                        source=subtitle_path,
                        destination=subtitle_path,  # Será deletado
                        operation_type='delete',
                        reason=f"Remover legenda em idioma estrangeiro ({lang_code_base})"
                    ))
                elif is_variant:
                    # Variante de idioma mantido (.por2, .eng3)
                    # NÃO processa aqui - deixa para _plan_subtitle_variants
                    # que vai escolher a melhor legenda se não existir .por.srt
                    pass  # Será tratada depois
                else:
                    # Legenda de idioma mantido (não é variante) - mover/renomear junto com vídeo

                    # Se não tem código de idioma, verifica se vai receber um
                    if not lang_code_base:
                        detected_language = detect_subtitle_language(
                            subtitle_path,
                            min_portuguese_words=self.config.min_pt_words,
                        )
                        if self.config.rename_no_lang and detected_language in self.config.kept_languages:
                            # Defer confidently detected subtitles so variant
                            # quality comparison can include .lang2/.lang3.
                            continue

                    processed_subtitles.append(subtitle_path)

                    # Monta novo nome da legenda baseado no novo nome do vídeo,
                    # preservando os flags do Jellyfin (sdh/forced).
                    new_video_stem = matching_video_op.destination.stem
                    new_subtitle_name = build_subtitle_name(
                        new_video_stem,
                        lang_code_base,
                        subtitle_path.suffix,
                        forced=is_forced,
                        hearing_impaired=is_hearing_impaired,
                    )

                    # Destino é na mesma pasta do novo vídeo
                    new_subtitle_path = matching_video_op.destination.parent / new_subtitle_name

                    # VERIFICA CONFLITO: se o destino já foi planejado (ex.: .hi,
                    # .cc e .sdh normalizam para o mesmo nome), leva o arquivo
                    # para a pasta do vídeo com o NOME ORIGINAL. Antes ele era
                    # simplesmente ignorado e ficava órfão na pasta antiga.
                    if new_subtitle_path in self.planned_destinations:
                        fallback_path = matching_video_op.destination.parent / subtitle_path.name
                        self.logger.warning(
                            f"Conflito de destino: {subtitle_path.name} → {new_subtitle_name} "
                            f"(destino já em uso; mantendo nome original)"
                        )
                        if (
                            fallback_path == subtitle_path
                            or fallback_path in self.planned_destinations
                        ):
                            continue
                        new_subtitle_path = fallback_path
                        new_subtitle_name = fallback_path.name

                    if new_subtitle_path != subtitle_path:
                        # Detecta tipo de operação
                        pasta_mudou = new_subtitle_path.parent != subtitle_path.parent
                        nome_mudou = new_subtitle_path.name != subtitle_path.name

                        if pasta_mudou and nome_mudou:
                            op_type = 'move_rename'
                        elif pasta_mudou:
                            op_type = 'move'
                        else:
                            op_type = 'rename'

                        self.operations.append(RenameOperation(
                            source=subtitle_path,
                            destination=new_subtitle_path,
                            operation_type=op_type,
                            reason=f"Acompanhar vídeo: {subtitle_path.name} → {new_subtitle_name}"
                        ))
                        
                        # Marca o destino como usado
                        self.planned_destinations.add(new_subtitle_path)

        return processed_subtitles

    def _plan_subtitle_variants(self, subtitle_files: List[Path], directory: Path):
        """
        Processa legendas de forma inteligente em 2 fases.

        Fase 1: Renomeia variações (lang2, lang3) para lang.srt quando lang.srt não existe
        Fase 2: Remove outras variações duplicadas (se configurado)
        """
        # Organiza legendas por diretório e base name
        from collections import defaultdict

        # Agrupa: {(dir, base_name, lang_code, suffix): [(num, path), ...]}
        grouped = defaultdict(list)

        for file_path in subtitle_files:
            info = parse_subtitle_name(file_path.stem)

            # Pula .forced (nunca mexe)
            if info['forced']:
                self._plan_subtitle_other_operations(file_path)
                continue

            # Variações .lang2 / .lang3 — de QUALQUER idioma e QUALQUER
            # extensão de legenda (antes só .srt era tratado, então variantes
            # .ass/.vtt eram detectadas pelo scanner e nunca processadas).
            if info['variant'] is not None and info['language']:
                key = (file_path.parent, info['base_name'], info['language'], file_path.suffix)
                grouped[key].append((info['variant'], file_path))
                continue

            detected_language = None
            if info['language'] is None and self.config.rename_no_lang:
                detected_language = detect_subtitle_language(
                    file_path,
                    min_portuguese_words=self.config.min_pt_words,
                )
            if detected_language in self.config.kept_languages:
                key = (
                    file_path.parent,
                    info['base_name'],
                    detected_language,
                    file_path.suffix,
                )
                # Usa 0 como número para ter prioridade sobre variantes
                grouped[key].append((0, file_path))
                continue

            # Não é variação, processa normalmente
            self._plan_subtitle_other_operations(file_path)

        # Processa cada grupo de variações
        for (parent_dir, base_name, lang_code, suffix), variants in grouped.items():
            # Calcula qualidade de cada variação
            scored_variants = []
            for num, path in variants:
                try:
                    file_size = path.stat().st_size
                except OSError:
                    file_size = 0
                quality = calculate_subtitle_quality(path, file_size=file_size)
                scored_variants.append((quality, num, path, file_size))

                # Log de debug (apenas em modo verbose)
                self.logger.debug(
                    f"Legenda .{lang_code}{num}{suffix}: "
                    f"qualidade={quality:.1f}, tamanho={file_size} bytes"
                )

            # Ordena por qualidade (MELHOR primeiro, depois menor número como desempate)
            scored_variants.sort(key=lambda x: (-x[0], x[1]))

            # Verifica se existe .lang.<ext> (sem número)
            target_name = build_subtitle_name(base_name, lang_code, suffix)
            target_path = parent_dir / target_name

            # Verifica se há operação de vídeo correspondente (para usar a pasta de destino)
            video_op = self.video_operations_map.get(base_name) or \
                       self.video_operations_map.get(normalize_spaces(base_name))

            if video_op:
                # Usa a pasta de destino do vídeo
                new_video_stem = video_op.destination.stem
                final_target_name = build_subtitle_name(new_video_stem, lang_code, suffix)
                final_target_path = video_op.destination.parent / final_target_name
            else:
                # Mantém na pasta original
                final_target_path = target_path

            if not target_path.exists():
                # NÃO existe .lang.srt → renomeia a MELHOR variação
                best_quality, best_num, best_path, best_size = scored_variants[0]

                # Verifica se a melhor tem qualidade > 0 (não é vazia/inválida)
                if best_quality > 0:
                    # Verifica conflito de destino
                    if final_target_path in self.planned_destinations:
                        self.logger.warning(
                            f"Conflito de destino: {best_path.name} → {final_target_path.name} "
                            f"(destino já em uso, ignorando)"
                        )
                    else:
                        # Determina tipo de operação
                        pasta_mudou = final_target_path.parent != best_path.parent
                        nome_mudou = final_target_path.name != best_path.name
                        
                        if pasta_mudou and nome_mudou:
                            op_type = 'move_rename'
                        elif pasta_mudou:
                            op_type = 'move'
                        else:
                            op_type = 'rename'
                        
                        self.operations.append(RenameOperation(
                            source=best_path,
                            destination=final_target_path,
                            operation_type=op_type,
                            reason=f"Renomear .{lang_code}{best_num}{suffix} para .{lang_code}{suffix} (melhor: {best_size} bytes, qualidade {best_quality:.0f})"
                        ))
                        self.planned_destinations.add(final_target_path)

                    # Marca as outras para remoção (se configurado)
                    if self.config.remove_language_variants and len(scored_variants) > 1:
                        for quality, num, path, size in scored_variants[1:]:
                            self.operations.append(RenameOperation(
                                source=path,
                                destination=path,
                                operation_type='delete',
                                reason=f"Remover variação .{lang_code}{num}{suffix} ({size} bytes, inferior)"
                            ))
                    else:
                        self._plan_variant_followers(
                            scored_variants[1:], lang_code, suffix, video_op
                        )
                else:
                    # Todas as variações têm qualidade 0 (vazias/inválidas)
                    self.logger.warning(
                        f"Todas as variações .{lang_code}X{suffix} estão vazias ou inválidas - não renomeando"
                    )
                    self._plan_variant_followers(scored_variants, lang_code, suffix, video_op)
            else:
                # JÁ existe .lang.<ext> → remove TODAS as variações (se configurado)
                if self.config.remove_language_variants:
                    for quality, num, path, size in scored_variants:
                        self.operations.append(RenameOperation(
                            source=path,
                            destination=path,
                            operation_type='delete',
                            reason=f"Remover variação .{lang_code}{num}{suffix} (já existe .{lang_code}{suffix})"
                        ))
                else:
                    # NÃO remover é o padrão — mas as variantes precisam
                    # acompanhar o vídeo, senão ficam órfãs na pasta antiga.
                    self._plan_variant_followers(scored_variants, lang_code, suffix, video_op)

    def _plan_extras_following_video(self, old_folder: Path, new_folder: Path, planned_sources: set):
        """Move os extras de uma pasta de mídia para o novo destino do vídeo.

        Fonte única usada tanto pelo planejamento normal quanto pela correção
        manual da GUI — para não existir uma segunda cópia que esquece o caso.
        Preserva a subpasta ("behind the scenes/Making of.mp4").

        Só age quando ``old_folder`` é a pasta DEDICADA de um filme. Numa pasta
        contêiner (vários filmes soltos), varrer recursivamente arrastaria os
        extras de um filme para dentro de outro.
        """
        try:
            candidates = sorted(old_folder.rglob('*'))
        except OSError as e:
            self.logger.debug(f"Não foi possível listar extras em {old_folder}: {e}")
            return

        # Pasta dedicada = contém no máximo UM vídeo principal (fora extras).
        main_videos = [
            p for p in candidates
            if is_video_file(p) and not is_extras_path(p)
        ]
        if len(main_videos) > 1:
            self.logger.debug(
                f"{old_folder} tem {len(main_videos)} vídeos: tratada como contêiner, "
                f"extras não são movidos"
            )
            return

        for extra_path in candidates:
            try:
                if not extra_path.is_file():
                    continue
            except OSError:
                continue

            if extra_path.name.startswith('.'):
                continue
            if not is_extras_path(extra_path):
                continue
            if extra_path in planned_sources:
                continue

            new_path = new_folder / extra_path.relative_to(old_folder)

            if new_path == extra_path:
                continue
            if new_path.exists():
                self.logger.warning(f"Extra já existe no destino, pulando: {extra_path.name}")
                continue

            self.operations.append(RenameOperation(
                source=extra_path,
                destination=new_path,
                operation_type='move',
                reason=f"Mover extra junto com o vídeo: {extra_path.name}"
            ))
            planned_sources.add(extra_path)

    def _plan_variant_followers(self, scored_variants, lang_code: str, suffix: str, video_op):
        """Faz variantes que NÃO serão promovidas nem removidas seguirem o vídeo.

        Sem isso, com ``remove_language_variants=False`` (o padrão) uma
        ``.por2.srt`` simplesmente não recebia operação nenhuma: o vídeo mudava
        de pasta e ela ficava órfã na pasta antiga — que por consequência nem
        era removida por estar "não vazia".
        """
        if not video_op:
            return  # vídeo não muda de lugar: variante pode ficar onde está

        new_video_stem = video_op.destination.stem
        target_dir = video_op.destination.parent

        for _quality, num, path, _size in scored_variants:
            new_name = f"{new_video_stem}.{lang_code}{num}{suffix}"
            new_path = target_dir / new_name

            if new_path == path or new_path in self.planned_destinations:
                continue

            folder_changed = new_path.parent != path.parent
            name_changed = new_path.name != path.name
            if folder_changed and name_changed:
                op_type = 'move_rename'
            elif folder_changed:
                op_type = 'move'
            else:
                op_type = 'rename'

            self.operations.append(RenameOperation(
                source=path,
                destination=new_path,
                operation_type=op_type,
                reason=f"Acompanhar vídeo (variação preservada): {path.name} → {new_name}"
            ))
            self.planned_destinations.add(new_path)

    def _plan_subtitle_other_operations(self, file_path: Path):
        """Outras operações de legendas (idiomas estrangeiros, sem idioma, etc.)"""
        info = parse_subtitle_name(file_path.stem)
        lang_code = info['language']

        # Remove legendas estrangeiras (que NÃO estão na lista de idiomas mantidos).
        # .forced nunca é removida.
        if self.config.remove_foreign_subs and not info['forced']:
            known_languages = set(self.config.all_languages.keys())
            if (
                lang_code
                and lang_code in known_languages
                and lang_code not in self.config.kept_languages
            ):
                self.operations.append(RenameOperation(
                    source=file_path,
                    destination=file_path,  # Será deletado
                    operation_type='delete',
                    reason=f"Remover legenda em idioma estrangeiro ({lang_code})"
                ))
                return

        # 3. Adiciona código de idioma a legendas sem código
        if self.config.rename_no_lang and lang_code is None:
            detected_language = detect_subtitle_language(
                file_path,
                min_portuguese_words=self.config.min_pt_words,
            )
            if detected_language in self.config.kept_languages:
                new_name = build_subtitle_name(
                    info['base_name'],
                    detected_language,
                    file_path.suffix,
                    forced=info['forced'],
                    hearing_impaired=info['hearing_impaired'],
                    default=info['default'],
                )
                new_path = file_path.parent / new_name
                if new_path != file_path:
                    self.operations.append(RenameOperation(
                        source=file_path,
                        destination=new_path,
                        operation_type='rename',
                        reason=(
                            "Adicionar código de idioma detectado "
                            f"(.{detected_language})"
                        )
                    ))

    def _plan_extra_files(self, directory: Path, video_files: List[Path], scan_result=None):
        """
        Planeja movimentação e renomeação de arquivos extras (NFO, imagens, etc) que acompanham vídeos.

        Quando um vídeo é movido para uma nova pasta, todos os arquivos extras da pasta
        original devem ser movidos junto. Arquivos NFO são também renomeados para
        corresponder ao nome do vídeo se a opção rename_nfo estiver habilitada.

        Args:
            directory: Diretório base
            video_files: Lista de arquivos de vídeo processados
            scan_result: Resultado do scan (opcional) para filtrar arquivos permitidos
        """
        from ..utils.helpers import is_video_file, is_subtitle_file

        # Se temos um scan_result (filtrado), cria um set de arquivos permitidos
        allowed_files = None
        if scan_result:
            allowed_files = set()
            allowed_files.update(scan_result.video_files)
            allowed_files.update(scan_result.subtitle_files)
            allowed_files.update(scan_result.image_files)
            allowed_files.update(scan_result.nfo_files)
            allowed_files.update(scan_result.other_files)
            allowed_files.update(scan_result.non_media_files)
            # Inclui também as listas categorizadas para garantir
            allowed_files.update(scan_result.variant_subtitles)
            allowed_files.update(scan_result.no_lang_subtitles)
            allowed_files.update(scan_result.foreign_subtitles)
            allowed_files.update(scan_result.kept_subtitles)
            allowed_files.update(scan_result.unwanted_images)

        # Cria mapa de vídeos: pasta_original -> (nova_pasta, video_stem_antigo, video_stem_novo)
        video_folder_map = {}
        video_rename_map = {}  # old_stem -> new_stem para renomear NFO
        video_file_set = set(video_files)  # lookup O(1)

        for op in self.operations:
            if op.source in video_file_set:
                old_folder = op.source.parent
                new_folder = op.destination.parent
                old_stem = op.source.stem
                new_stem = op.destination.stem
                
                # Mapeia pastas
                if old_folder != new_folder:
                    if old_folder not in video_folder_map:
                        video_folder_map[old_folder] = new_folder
                
                # Mapeia renomeação de stem (para NFO)
                if old_stem != new_stem:
                    video_rename_map[old_stem] = (new_stem, new_folder)
                elif old_folder != new_folder:
                    # Mesmo stem mas pasta diferente
                    video_rename_map[old_stem] = (old_stem, new_folder)

        # Para cada pasta que está sendo esvaziada, move os arquivos extras
        planned_sources = {op.source for op in self.operations}
        for old_folder, new_folder in video_folder_map.items():
            # Lista todos os arquivos na pasta antiga
            for file_path in old_folder.iterdir():
                if not file_path.is_file():
                    continue

                # Verifica se o arquivo é permitido (se houver filtro)
                if allowed_files is not None and file_path not in allowed_files:
                    continue

                # Ignora arquivos ocultos
                if file_path.name.startswith('.'):
                    continue

                # Extras pertencem à pasta da mídia e não são realocados aqui
                if is_extras_path(file_path):
                    continue

                # Ignora vídeos e legendas (já foram processados)
                if is_video_file(file_path) or is_subtitle_file(file_path):
                    continue

                # Verifica se o arquivo já tem uma operação planejada
                if file_path in planned_sources:
                    continue

                # Verifica se é arquivo NFO e se deve renomear
                is_nfo = file_path.suffix.lower() == '.nfo'
                
                if is_nfo and self.config.rename_nfo:
                    # Tenta encontrar o vídeo correspondente para renomear o NFO
                    nfo_stem = file_path.stem
                    
                    if nfo_stem in video_rename_map:
                        # NFO corresponde a um vídeo renomeado
                        new_stem, target_folder = video_rename_map[nfo_stem]
                        new_name = f"{new_stem}.nfo"
                        new_path = target_folder / new_name
                        
                        # Verifica conflito
                        if new_path.exists() and new_path != file_path:
                            self.logger.warning(f"NFO já existe no destino, pulando: {file_path.name}")
                            continue
                        
                        # Determina tipo de operação
                        pasta_mudou = new_path.parent != file_path.parent
                        nome_mudou = new_path.name != file_path.name
                        
                        if pasta_mudou and nome_mudou:
                            op_type = 'move_rename'
                        elif pasta_mudou:
                            op_type = 'move'
                        else:
                            op_type = 'rename'
                        
                        self.operations.append(RenameOperation(
                            source=file_path,
                            destination=new_path,
                            operation_type=op_type,
                            reason=f"Renomear NFO para corresponder ao vídeo: {file_path.name} → {new_name}"
                        ))
                        planned_sources.add(file_path)
                        continue

                # Move o arquivo extra para a nova pasta (sem renomear)
                new_path = new_folder / file_path.name

                # Verifica se já existe um arquivo com esse nome no destino
                if new_path.exists() and new_path != file_path:
                    self.logger.warning(f"Arquivo extra já existe no destino, pulando: {file_path.name}")
                    continue

                self.operations.append(RenameOperation(
                    source=file_path,
                    destination=new_path,
                    operation_type='move',
                    reason=f"Mover arquivo extra junto com vídeo: {file_path.name}"
                ))
                planned_sources.add(file_path)

        # Extras acompanham o vídeo, preservando a subpasta.
        #
        # Extras não são mídia principal (não viram filme), mas PERTENCEM à
        # pasta da mídia: "trailer.mp4" e "behind the scenes/Making of.mp4" têm
        # de ir junto quando o filme muda de pasta. Sem isso eles ficavam
        # órfãos na pasta antiga — que sobrevivia como lixo por não estar vazia.
        #
        # IMPORTANTE: só vale quando o vídeo tinha PASTA PRÓPRIA. Para arquivos
        # soltos na raiz da biblioteca, a "pasta de origem" é o próprio
        # diretório de trabalho — varrê-lo recursivamente arrastaria os extras
        # de OUTROS filmes para dentro do primeiro que aparecesse.
        media_folder_map = {}
        for op in self.operations:
            if op.source not in video_file_set:
                continue
            old_folder, new_folder = op.source.parent, op.destination.parent
            if old_folder == new_folder:
                continue
            if old_folder.resolve() == self.work_dir:
                continue  # vídeo solto na raiz: não há pasta de mídia própria
            media_folder_map.setdefault(old_folder, new_folder)

        for old_folder, new_folder in media_folder_map.items():
            self._plan_extras_following_video(old_folder, new_folder, planned_sources)

        # Processar tvshow.nfo de séries
        # Para séries, o tvshow.nfo fica na pasta raiz (ex: /Serie/tvshow.nfo)
        # Precisamos movê-lo quando a pasta da série é renomeada
        series_root_map = {}  # old_series_root -> new_series_root

        for old_folder, new_folder in video_folder_map.items():
            # Detecta se é uma pasta de temporada (Season XX)
            if 'season' in old_folder.name.lower():
                old_series_root = old_folder.parent
                new_series_root = new_folder.parent

                if old_series_root != new_series_root:
                    series_root_map[old_series_root] = new_series_root

        # Mover tvshow.nfo da raiz da série
        for old_series_root, new_series_root in series_root_map.items():
            tvshow_nfo = old_series_root / 'tvshow.nfo'

            if tvshow_nfo.exists() and tvshow_nfo.is_file():
                # Verifica se já tem operação planejada
                if tvshow_nfo in planned_sources:
                    continue

                new_tvshow_path = new_series_root / 'tvshow.nfo'

                # Verifica conflito
                if new_tvshow_path.exists() and new_tvshow_path != tvshow_nfo:
                    self.logger.warning("tvshow.nfo já existe no destino, pulando")
                    continue

                self.operations.append(RenameOperation(
                    source=tvshow_nfo,
                    destination=new_tvshow_path,
                    operation_type='move',
                    reason="Mover tvshow.nfo para nova pasta da série"
                ))
                planned_sources.add(tvshow_nfo)

    def _plan_non_media_removal(self, non_media_files: List[Path]):
        """
        Planeja remoção de arquivos que não sejam .srt ou .mp4.

        Args:
            non_media_files: Lista de arquivos não-mídia a serem removidos
        """
        planned_sources = {op.source for op in self.operations}
        for file_path in non_media_files:
            # Verifica se o arquivo ainda não tem operação planejada
            if file_path in planned_sources:
                continue

            # Adiciona operação de remoção
            self.operations.append(RenameOperation(
                source=file_path,
                destination=file_path,  # Será deletado
                operation_type='delete',
                reason=f"Remover arquivo não-mídia: {file_path.suffix}"
            ))
            planned_sources.add(file_path)

    def execute_operations(self, dry_run: bool = True) -> Dict[str, int]:
        """
        Executa as operações planejadas.

        Args:
            dry_run: Se True, apenas simula as operações

        Returns:
            Dicionário com estatísticas
        """
        stats = {
            'renamed': 0,
            'moved': 0,
            'deleted': 0,
            'failed': 0,
            'skipped': 0,
            'cleaned': 0,  # Pastas vazias removidas
            'reverted': 0,  # Operações desfeitas por rollback
        }

        # Rastreia pastas de origem para limpeza posterior
        source_folders = set()

        # Rollback log: stores completed operations for reversal on failure
        completed_ops: List[RenameOperation] = []

        # Irreversible deletes run last. If a reversible operation fails, abort
        # before deleting anything.
        ordered_operations = sorted(
            self.operations,
            key=lambda op: op.operation_type == "delete"
        )

        for operation in ordered_operations:
            try:
                # Verifica se vai sobrescrever
                if operation.will_overwrite:
                    self.logger.warning(
                        f"Pulando (destino existe): {operation.source.name} → {operation.destination.name}"
                    )
                    stats['skipped'] += 1
                    continue

                if dry_run:
                    # Modo dry-run: apenas loga
                    self.logger.debug(
                        f"[DRY-RUN] {operation.operation_type.upper()}: "
                        f"{operation.source} → {operation.destination}"
                    )
                else:
                    # Executa a operação
                    if operation.operation_type == 'delete':
                        operation.source.unlink()
                        self.logger.action(f"Removido: {operation.source.name}")
                        stats['deleted'] += 1

                    elif operation.operation_type in ('move', 'move_rename'):
                        # Rastreia pasta de origem para limpeza posterior
                        source_folders.add(operation.source.parent)

                        # Cria pasta de destino se não existir
                        operation.destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(operation.source), str(operation.destination))

                        if operation.operation_type == 'move_rename':
                            self.logger.action(
                                f"Movido e renomeado: {operation.source} → {operation.destination}"
                            )
                            stats['moved'] += 1
                            stats['renamed'] += 1
                        else:
                            self.logger.action(
                                f"Movido: {operation.source} → {operation.destination}"
                            )
                            stats['moved'] += 1
                        completed_ops.append(operation)

                    elif operation.operation_type == 'rename':
                        operation.source.rename(operation.destination)
                        self.logger.action(
                            f"Renomeado: {operation.source.name} → {operation.destination.name}"
                        )
                        stats['renamed'] += 1
                        completed_ops.append(operation)

            except Exception as e:
                self.logger.error(f"Erro ao processar {operation.source}: {e}")
                stats["failed"] += 1

                # Rollback reversible operations on failure. Deletes are last and
                # cannot be restored, so a delete failure only aborts the tail.
                if operation.operation_type != "delete" and completed_ops and not dry_run:
                    self.logger.warning(f"Falha detectada, revertendo {len(completed_ops)} operações concluídas...")
                    reverted = self._rollback(completed_ops)
                    # Estatísticas refletem o estado FINAL: o que foi revertido
                    # não conta como concluído (antes as reversões eram somadas
                    # a 'failed', inflando o número, e renamed/moved eram
                    # zerados mesmo numa reversão parcial).
                    stats["reverted"] = reverted
                    stats["renamed"] = 0
                    stats["moved"] = 0
                break

        # Remove pastas vazias após mover arquivos.
        # SEMPRE limitado ao diretório de trabalho: sem essa âncora a subida na
        # hierarquia podia chegar a pastas do sistema (ex.: /mnt/media) e
        # removê-las caso ficassem vazias.
        work_dir = getattr(self, 'work_dir', None)
        if not dry_run and source_folders and work_dir:
            work_dir = Path(work_dir).resolve()
            folders_to_check = set()
            for folder in source_folders:
                current = folder.resolve()
                # Sobe até o work_dir INCLUSIVE, e para por aí.
                #
                # O próprio work_dir precisa entrar: quando o usuário aponta o
                # jellyfix direto para a pasta da mídia
                # ("The.Death.of.Robin.Hood.2026.../"), os arquivos vão para uma
                # pasta irmã e a original fica vazia — ela é justamente a que
                # precisa sumir. Exigir "estritamente dentro" deixava esse caso
                # de fora e a pasta vazia ficava para trás.
                while current == work_dir or work_dir in current.parents:
                    folders_to_check.add(current)
                    if current == work_dir:
                        break
                    current = current.parent

            for folder in sorted(folders_to_check, key=lambda p: len(str(p)), reverse=True):
                try:
                    if folder.exists() and folder.is_dir():
                        if not any(folder.iterdir()):
                            folder.rmdir()
                            self.logger.action(f"Removida pasta vazia: {folder}")
                            stats['cleaned'] += 1
                except Exception as e:
                    self.logger.debug(f"Não foi possível remover pasta {folder}: {e}")

        return stats

    def _rollback(self, completed_ops: List[RenameOperation]) -> int:
        """Reverte operações concluídas em ordem inversa.

        Move/rename operations are reversed (destination → source).
        Delete operations cannot be reversed and are logged as warnings.

        Returns:
            Quantidade de operações efetivamente revertidas.
        """
        reverted = 0
        for op in reversed(completed_ops):
            try:
                if op.operation_type == "delete":
                    self.logger.warning(f"Não é possível reverter exclusão: {op.source}")
                    continue

                if op.destination.exists():
                    op.source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(op.destination), str(op.source))
                    self.logger.action(f"Revertido: {op.destination} → {op.source}")
                    reverted += 1
            except Exception as e:
                self.logger.error(f"Falha ao reverter {op.destination}: {e}")
        return reverted

    def _plan_mirabel_fixes(self, subtitle_files: List[Path]) -> List[Path]:
        """
        Identifica arquivos Mirabel e guarda informações para renomeação posterior.

        NÃO cria operações aqui - apenas prepara as informações para que
        _plan_subtitle_companion crie uma única operação direta do arquivo
        original para o destino final.

        Padrões reconhecidos (o ``hi`` é PRESERVADO como ``.sdh``, que é o flag
        canônico do Jellyfin para legenda de surdos — antes ele era descartado
        e a legenda SDH virava uma legenda comum, colidindo com a original):
        - .pt-BR.hi.srt → .por.sdh.srt
        - .br.hi.srt → .por.sdh.srt
        - .pt-BR.hi.forced.srt → .por.sdh.forced.srt
        - .en.hi.srt → .eng.sdh.srt

        Args:
            subtitle_files: Lista de arquivos de legenda

        Returns:
            Lista de arquivos de legenda (paths originais, não modificados)
        """
        # Patterns para detectar arquivos Mirabel
        # Grupo 1: base_name, Grupo 2: código do idioma, Grupo 3: .forced (opcional)
        mirabel_patterns = [
            # Português: pt-BR, br, pt_BR, etc → por
            (re.compile(r'^(.+?)\.(pt-BR|pt-br|br|BR|pt_BR|pt_br)\.hi(\.forced)?\.srt$', re.IGNORECASE), 'por'),
            # Inglês: en, EN → eng
            (re.compile(r'^(.+?)\.(en|EN)\.hi(\.forced)?\.srt$', re.IGNORECASE), 'eng'),
        ]

        # Inicializa o mapa de informações Mirabel
        self.mirabel_info = {}  # Mapa: old_path -> {base_name, target_lang, forced}

        updated_subtitle_files = []
        mirabel_count = 0

        for file_path in subtitle_files:
            matched = False
            for pattern, target_lang in mirabel_patterns:
                match = pattern.match(file_path.name)
                if match:
                    matched = True
                    base_name = match.group(1)
                    forced = match.group(3)  # '.forced' ou None

                    # Constrói novo nome preservando o marcador de surdez (.sdh)
                    new_name = build_subtitle_name(
                        base_name, target_lang, '.srt',
                        forced=bool(forced), hearing_impaired=True,
                    )

                    new_path = file_path.parent / new_name

                    # Verifica se destino já existe
                    if new_path.exists() and new_path != file_path:
                        # Destino existe - marca para deleção
                        self.operations.append(RenameOperation(
                            source=file_path,
                            destination=file_path,
                            operation_type='delete',
                            reason=f"Mirabel duplicado: {new_name} já existe"
                        ))
                        self.logger.debug(f"Mirabel duplicado será deletado: {file_path.name}")
                    else:
                        # Guarda informações para renomeação posterior
                        self.mirabel_info[file_path] = {
                            'base_name': base_name,
                            'target_lang': target_lang,
                            'forced': bool(forced),
                            'hearing_impaired': True,  # o "hi" do nome Mirabel
                        }
                        mirabel_count += 1
                        # Mantém o path ORIGINAL na lista
                        updated_subtitle_files.append(file_path)
                        self.logger.debug(f"Mirabel identificado: {file_path.name} → {new_name}")
                    break  # Sai do loop de patterns após match

            if not matched:
                # Não é arquivo Mirabel, mantém na lista
                updated_subtitle_files.append(file_path)

        if mirabel_count > 0:
            self.logger.info(f"Encontrados {mirabel_count} arquivos Mirabel para correção")

        return updated_subtitle_files
