"""Busca de metadados via TMDB e TVDB"""

import time
from typing import Optional, List
from dataclasses import dataclass
import re

from ..utils.config import get_config
from ..utils.logger import get_logger


@dataclass
class Metadata:
    """Movie or TV show metadata"""
    title: str
    year: Optional[int] = None
    tmdb_id: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    original_title: Optional[str] = None
    overview: Optional[str] = None
    # Image paths
    poster_path: Optional[str] = None      # Relative path (e.g., '/abc123.jpg')
    backdrop_path: Optional[str] = None    # Relative path (e.g., '/xyz789.jpg')
    poster_url: Optional[str] = None       # Full CDN URL
    backdrop_url: Optional[str] = None     # Full CDN URL
    # "movie" or "tvshow" — set when source is unambiguous (manual user choice
    # or TMDB endpoint type). When None, callers fall back to filename detection.
    media_type: Optional[str] = None


class MetadataFetcher:
    """Busca metadados via TMDB e TVDB"""

    def __init__(self):
        self.config = get_config()
        self.logger = get_logger()
        self._tmdb = None
        self._tvdb = None
        # Cache de escolhas interativas por (título, ano)
        # Evita perguntar múltiplas vezes para arquivos do mesmo filme
        self._interactive_choices_cache = {}
        # Cache de buscas sem resultado para evitar re-pesquisa
        self._failed_searches: set = set()
        # Matches de baixa confiança registrados nesta execução (revisão manual)
        self._low_confidence: list = []
        # Rate limiting: TMDB free tier = 40 req / 10 sec
        self._last_request_time: float = 0.0
        self._min_request_interval: float = 0.25  # 4 req/sec max

    def _rate_limit(self) -> None:
        """Enforce minimum interval between TMDB API requests."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.monotonic()

    # ------------------------------------------------------------------
    # Verificação de match (anti-erro): similaridade de título + ano
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_for_match(text: str) -> str:
        """Normaliza p/ comparação: minúsculas, sem acento, sem pontuação."""
        if not text:
            return ""
        import unicodedata
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
        text = text.lower()
        # Remove pontuação, mas PRESERVA letras não-latinas (CJK, cirílico…).
        # Se removêssemos tudo que não é [a-z0-9], um título como "1989放暑假"
        # viraria só "1989" e casaria falsamente com qualquer filme de 1989.
        # Mantemos qualquer caractere >= U+0080 (acentos latinos já foram
        # decompostos e removidos acima, então sobram só scripts estrangeiros).
        kept = []
        for ch in text:
            if ch.isalnum() or ord(ch) >= 0x80:
                kept.append(ch)
            else:
                kept.append(" ")
        text = "".join(kept)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _title_match_ratio(cls, a: str, b: str) -> float:
        """Similaridade 0..1 entre dois títulos (char + token), robusta a ordem."""
        na, nb = cls._normalize_for_match(a), cls._normalize_for_match(b)
        if not na or not nb:
            return 0.0
        if na == nb:
            return 1.0
        from difflib import SequenceMatcher
        char_ratio = SequenceMatcher(None, na, nb).ratio()
        wa, wb = set(na.split()), set(nb.split())
        token_ratio = len(wa & wb) / len(wa | wb) if (wa | wb) else 0.0
        # Bônus se um título contém o outro (ex.: original vs PT com subtítulo)
        contains = 1.0 if (na in nb or nb in na) else 0.0
        return max(char_ratio, token_ratio, contains * 0.9)

    def _score_candidate(self, query_title: str, query_year, cand) -> float:
        """
        Pontua um candidato do TMDB 0..1 combinando similaridade de título
        (melhor entre título PT e título original) e proximidade de ano.
        Penaliza forte quando o ano não bate (a guarda de ano sozinha falhava
        quando o filme errado tinha o mesmo ano — aqui o título desempata).
        """
        cand_title = getattr(cand, "title", "") or getattr(cand, "name", "")
        cand_orig = getattr(cand, "original_title", "") or getattr(cand, "original_name", "")
        title_sim = max(
            self._title_match_ratio(query_title, cand_title),
            self._title_match_ratio(query_title, cand_orig),
        )
        return title_sim * self._year_factor(query_year, cand)

    @staticmethod
    def _year_factor(query_year, cand) -> float:
        """Fator 0..1 de proximidade entre o ano da busca e o do candidato."""
        cand_year = None
        date_attr = getattr(cand, "release_date", None) or getattr(cand, "first_air_date", None)
        if date_attr:
            m = re.search(r"^(\d{4})", date_attr)
            if m:
                cand_year = int(m.group(1))

        if not query_year or cand_year is None:
            return 0.85  # sem ano p/ comparar: neutro-levemente-cauteloso
        diff = abs(cand_year - query_year)
        if diff == 0:
            return 1.0
        if diff == 1:
            return 0.9
        if diff <= 2:
            return 0.5
        return 0.15  # ano muito diferente: quase certamente errado

    def _best_candidate(self, results, query_title: str, query_year, limit: int = 10):
        """Itera os candidatos, pontua cada um e devolve (melhor, score)."""
        best, best_score = None, -1.0
        count = 0
        for cand in results:
            if count >= limit:
                break
            count += 1
            score = self._score_candidate(query_title, query_year, cand)
            if score > best_score:
                best, best_score = cand, score
        return best, best_score

    def _alt_title_rescue(self, tmdb, results, query_title: str, query_year, threshold: float):
        """
        Segunda chance para o gate de confiança usando TÍTULOS ALTERNATIVOS.

        Arquivos costumam usar o título de lançamento internacional (ex.:
        "Like Stars on Earth"), mas o resultado da busca só expõe o título
        pt-BR ("Como Estrelas na Terra") e o original ("Taare Zameen Par") —
        a similaridade fica baixa e o gate rejeitaria um match CORRETO.

        Para os melhores candidatos cujo ano bate (±1), consulta
        /movie/{id}/alternative_titles e re-pontua. Só aceita se atingir o
        threshold — então o gate continua barrando matches realmente ruins.

        Returns:
            (candidato, score) se algum candidato passar; senão (None, 0.0).
        """
        # Rankeia os candidatos e guarda o year_factor de cada um
        scored = []
        count = 0
        for cand in results:
            if count >= 10:
                break
            count += 1
            scored.append((self._score_candidate(query_title, query_year, cand), cand))
        scored.sort(key=lambda t: t[0], reverse=True)

        checked = 0
        for base_score, cand in scored:
            if checked >= 3:  # no máximo 3 chamadas extras à API
                break
            yf = self._year_factor(query_year, cand)
            if yf < 0.85:  # só vale a pena se o ano bate (±1) ou é desconhecido
                continue
            cand_id = getattr(cand, "id", None)
            if not cand_id:
                continue
            checked += 1
            try:
                self._rate_limit()
                alts = tmdb['movie'].alternative_titles(cand_id)
                # AsObj/dict: a lista fica em 'titles'
                titles_obj = None
                if isinstance(alts, dict):
                    titles_obj = alts.get('titles')
                else:
                    titles_obj = getattr(alts, 'titles', None) or alts
                alt_titles = []
                for item in (titles_obj or []):
                    t = item.get('title') if isinstance(item, dict) else getattr(item, 'title', None)
                    if t:
                        alt_titles.append(t)
            except Exception as e:
                self.logger.debug(f"alternative_titles({cand_id}) falhou: {e}")
                continue

            best_alt_sim = max(
                (self._title_match_ratio(query_title, t) for t in alt_titles),
                default=0.0,
            )
            alt_score = best_alt_sim * yf
            if alt_score >= threshold:
                self.logger.info(
                    f"✓ Resgate por título alternativo ({alt_score:.2f}): "
                    f"'{query_title}' ({query_year}) → "
                    f"'{getattr(cand, 'title', '?')}' [id {cand_id}]"
                )
                return cand, alt_score

        return None, 0.0

    def _record_low_confidence(self, query_title, query_year, cand, score) -> None:
        """Registra um match de baixa confiança para revisão manual posterior.

        Grava em ~/.jellyfix/review_pendente.txt e mantém em memória. Assim,
        em vez de renomear errado silenciosamente, os casos duvidosos ficam
        visíveis para o usuário decidir.
        """
        try:
            cand_title = getattr(cand, "title", None) or getattr(cand, "name", "?")
            cand_id = getattr(cand, "id", "?")
            cand_date = getattr(cand, "release_date", None) or getattr(cand, "first_air_date", "") or ""
            cand_year = cand_date[:4] if cand_date else "?"
            # Série ou filme? O link precisa apontar para o endpoint certo.
            kind = "tv" if getattr(cand, "first_air_date", None) or getattr(cand, "name", None) else "movie"
            line = (
                f"BAIXA_CONFIANCA score={score:.2f} | busca='{query_title}' ({query_year}) "
                f"| melhor_palpite='{cand_title}' ({cand_year}) [tmdbid-{cand_id}] "
                f"https://www.themoviedb.org/{kind}/{cand_id}"
            )
            self._low_confidence.append(line)
            from pathlib import Path
            review = Path.home() / ".jellyfix" / "review_pendente.txt"
            review.parent.mkdir(parents=True, exist_ok=True)
            with review.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as e:  # nunca deixar o relatório quebrar a execução
            self.logger.debug(f"Falha ao registrar baixa confiança: {e}")

    def _init_tmdb(self):
        """Inicializa cliente TMDB"""
        if self._tmdb is not None:
            return self._tmdb

        if not self.config.tmdb_api_key:
            self.logger.warning("TMDB API key não configurada. Use: export TMDB_API_KEY=sua_chave")
            return None

        try:
            from tmdbv3api import TMDb, Movie, TV, Search

            tmdb = TMDb()
            tmdb.api_key = self.config.tmdb_api_key
            tmdb.language = 'pt-BR'

            self._tmdb = {
                'client': tmdb,
                'movie': Movie(),
                'tv': TV(),
                'search': Search()
            }
            return self._tmdb

        except ImportError:
            self.logger.error("tmdbv3api não instalado. Instale com: pip install tmdbv3api")
            return None
        except Exception as e:
            self.logger.error(f"Erro ao inicializar TMDB: {e}")
            return None

    def get_movie_by_id(self, tmdb_id: int) -> Optional[Metadata]:
        """
        Busca metadados de filme diretamente pelo TMDB ID.

        Args:
            tmdb_id: TMDB ID do filme

        Returns:
            Metadata ou None se não encontrado
        """
        tmdb = self._init_tmdb()
        if not tmdb:
            return None

        try:
            # Busca diretamente pelo ID
            self._rate_limit()
            movie = tmdb['movie'].details(tmdb_id)

            if not movie:
                self.logger.debug(f"Filme não encontrado com ID: {tmdb_id}")
                return None

            # Extrai ano do release_date
            movie_year = None
            if hasattr(movie, 'release_date') and movie.release_date:
                match = re.search(r'^(\d{4})', movie.release_date)
                if match:
                    movie_year = int(match.group(1))

            # Build image URLs
            poster_path = getattr(movie, 'poster_path', None)
            backdrop_path = getattr(movie, 'backdrop_path', None)

            base_url = "https://image.tmdb.org/t/p"
            poster_url = f"{base_url}/w500{poster_path}" if poster_path else None
            backdrop_url = f"{base_url}/w1280{backdrop_path}" if backdrop_path else None

            return Metadata(
                title=movie.title,
                year=movie_year,
                tmdb_id=movie.id,
                imdb_id=getattr(movie, 'imdb_id', None),
                original_title=getattr(movie, 'original_title', None),
                overview=getattr(movie, 'overview', None),
                poster_path=poster_path,
                backdrop_path=backdrop_path,
                poster_url=poster_url,
                backdrop_url=backdrop_url
            )

        except Exception as e:
            self.logger.error(f"Erro ao buscar filme por ID {tmdb_id}: {e}")
            return None

    def get_tvshow_by_id(self, tmdb_id: int) -> Optional[Metadata]:
        """
        Busca metadados de série diretamente pelo TMDB ID.

        Args:
            tmdb_id: TMDB ID da série

        Returns:
            Metadata ou None se não encontrado
        """
        tmdb = self._init_tmdb()
        if not tmdb:
            return None

        try:
            # Busca diretamente pelo ID
            self._rate_limit()
            show = tmdb['tv'].details(tmdb_id)

            if not show:
                self.logger.debug(f"Série não encontrada com ID: {tmdb_id}")
                return None

            # Extrai ano
            show_year = None
            if hasattr(show, 'first_air_date') and show.first_air_date:
                match = re.search(r'^(\d{4})', show.first_air_date)
                if match:
                    show_year = int(match.group(1))

            # Build image URLs
            poster_path = getattr(show, 'poster_path', None)
            backdrop_path = getattr(show, 'backdrop_path', None)

            base_url = "https://image.tmdb.org/t/p"
            poster_url = f"{base_url}/w500{poster_path}" if poster_path else None
            backdrop_url = f"{base_url}/w1280{backdrop_path}" if backdrop_path else None

            return Metadata(
                title=show.name,
                year=show_year,
                tmdb_id=show.id,
                original_title=getattr(show, 'original_name', None),
                overview=getattr(show, 'overview', None),
                poster_path=poster_path,
                backdrop_path=backdrop_path,
                poster_url=poster_url,
                backdrop_url=backdrop_url
            )

        except Exception as e:
            self.logger.error(f"Erro ao buscar série por ID {tmdb_id}: {e}")
            return None

    def _search_movie_with_fallback(self, search_api, title: str, year: Optional[int] = None):
        """
        Busca filme com fallback incremental.
        Se não encontrar, remove palavras do final até achar.

        Args:
            search_api: API do TMDB Search
            title: Título limpo
            year: Ano (opcional, melhora a precisão da busca)

        Returns:
            Resultados da busca ou None
        """
        words = title.split()
        min_words = 1  # Mínimo de palavras para tentar

        # Tenta com título completo primeiro
        for i in range(len(words), min_words - 1, -1):
            current_title = ' '.join(words[:i])

            if i < len(words):
                self.logger.debug(f"Tentando busca alternativa: '{current_title}'")

            try:
                # Inclui o ano na busca se fornecido (melhora muito a precisão)
                self._rate_limit()
                if year:
                    results = search_api.movies(current_title, year=year)
                    if i == len(words):
                        self.logger.debug(f"Buscando: '{current_title}' (ano: {year})")
                else:
                    results = search_api.movies(current_title)

                # Se encontrou resultados, retorna
                if results and hasattr(results, 'total_results') and results.total_results > 0:
                    if i < len(words):
                        self.logger.info(f"✓ Encontrado usando: '{current_title}' (removidas {len(words) - i} palavras)")
                    return results

            except Exception as e:
                self.logger.debug(f"Erro ao buscar '{current_title}': {e}")
                continue

        # Não encontrou nada
        return None

    def _search_tvshow_with_fallback(self, tv_api, title: str):
        """
        Busca série com fallback incremental.
        Se não encontrar, remove palavras do final até achar.

        Args:
            tv_api: API do TMDB TV
            title: Título limpo

        Returns:
            Resultados da busca ou None
        """
        words = title.split()
        min_words = 1  # Mínimo de palavras para tentar

        # Tenta com título completo primeiro
        for i in range(len(words), min_words - 1, -1):
            current_title = ' '.join(words[:i])

            if i < len(words):
                self.logger.debug(f"Tentando busca alternativa: '{current_title}'")

            try:
                self._rate_limit()
                results = tv_api.search(current_title)

                # Se encontrou resultados, retorna
                if results and hasattr(results, 'total_results') and results.total_results > 0:
                    if i < len(words):
                        self.logger.info(f"✓ Encontrado usando: '{current_title}' (removidas {len(words) - i} palavras)")
                    return results

            except Exception as e:
                self.logger.debug(f"Erro ao buscar '{current_title}': {e}")
                continue

        # Não encontrou nada
        return None

    def search_movie(self, title: str, year: Optional[int] = None, interactive: bool = False) -> Optional[Metadata]:
        """
        Busca metadados de um filme.

        Args:
            title: Título do filme
            year: Ano (opcional, melhora a busca)
            interactive: Se True, permite escolher entre múltiplos resultados

        Returns:
            Metadata ou None se não encontrado
        """
        tmdb = self._init_tmdb()
        if not tmdb:
            return None

        try:
            # Limpa o título
            clean_title = self._clean_search_title(title)

            # Cria chave de cache para evitar perguntar múltiplas vezes
            # quando há vários arquivos do mesmo filme (ex: vídeo + legendas)
            cache_key = (clean_title.lower(), year)

            # Verifica se já temos uma escolha em cache
            if cache_key in self._interactive_choices_cache:
                cached_choice = self._interactive_choices_cache[cache_key]
                if cached_choice is None:
                    # Usuário escolheu "pular" anteriormente
                    return None
                # Reutiliza a escolha anterior
                self.logger.debug(f"Usando escolha em cache para '{clean_title}' ({year})")
                return cached_choice

            # Skip re-querying titles that already returned no results
            if cache_key in self._failed_searches:
                self.logger.debug(f"Busca já falhou anteriormente para '{clean_title}' ({year}), pulando")
                return None

            # Busca incremental: tenta com título completo, depois vai removendo palavras do final
            results = self._search_movie_with_fallback(tmdb['search'], clean_title, year)

            # Verifica se há resultados reais (total_results > 0)
            if not results or results.total_results == 0:
                self.logger.debug(f"Nenhum resultado para: {clean_title}")
                self._failed_searches.add(cache_key)
                return None

            # Se modo interativo e múltiplos resultados, pede escolha
            if interactive and len(results) > 1 and self.config.ask_on_multiple_results:
                movie = self._choose_movie_interactive(results, clean_title, year)
                if not movie:
                    # Salva no cache que usuário pulou
                    self._interactive_choices_cache[cache_key] = None
                    return None
            else:
                # ANTI-ERRO: em vez de "pega o primeiro", rankeia os candidatos
                # por similaridade de título (PT + original) combinada com a
                # proximidade de ano, e exige confiança mínima — senão NÃO chuta.
                movie, score = self._best_candidate(results, clean_title, year)
                if not movie:
                    self._failed_searches.add(cache_key)
                    return None

                threshold = getattr(self.config, "match_confidence_threshold", 0.55)
                if score < threshold:
                    # Segunda chance: o arquivo pode usar um título alternativo
                    # (lançamento internacional) que não aparece no resultado
                    # da busca — re-pontua com /alternative_titles antes de desistir.
                    rescued, rescued_score = self._alt_title_rescue(
                        tmdb, results, clean_title, year, threshold
                    )
                    if rescued is not None:
                        movie, score = rescued, rescued_score
                    else:
                        self.logger.warning(
                            f"✗ Baixa confiança ({score:.2f} < {threshold:.2f}) para "
                            f"'{clean_title}' ({year}) → melhor candidato: "
                            f"'{getattr(movie, 'title', '?')}' "
                            f"({getattr(movie, 'release_date', '?')[:4] if getattr(movie, 'release_date', None) else '?'}) "
                            f"[id {getattr(movie, 'id', '?')}]. Pulando (revisar manualmente)."
                        )
                        self._record_low_confidence(clean_title, year, movie, score)
                        self._interactive_choices_cache[cache_key] = None
                        return None
                self.logger.debug(
                    f"✓ Match confiável ({score:.2f}) '{clean_title}' ({year}) → "
                    f"'{getattr(movie, 'title', '?')}' [id {getattr(movie, 'id', '?')}]"
                )

            # Extrai ano do release_date
            movie_year = None
            if hasattr(movie, 'release_date') and movie.release_date:
                match = re.search(r'^(\d{4})', movie.release_date)
                if match:
                    movie_year = int(match.group(1))

            # Build image URLs
            poster_path = getattr(movie, 'poster_path', None)
            backdrop_path = getattr(movie, 'backdrop_path', None)

            base_url = "https://image.tmdb.org/t/p"
            poster_url = f"{base_url}/w500{poster_path}" if poster_path else None
            backdrop_url = f"{base_url}/w1280{backdrop_path}" if backdrop_path else None

            metadata = Metadata(
                title=movie.title,
                year=movie_year,
                tmdb_id=movie.id,
                imdb_id=getattr(movie, 'imdb_id', None),
                original_title=getattr(movie, 'original_title', None),
                overview=getattr(movie, 'overview', None),
                poster_path=poster_path,
                backdrop_path=backdrop_path,
                poster_url=poster_url,
                backdrop_url=backdrop_url
            )

            # Salva no cache para reutilizar em arquivos subsequentes do mesmo filme
            self._interactive_choices_cache[cache_key] = metadata

            return metadata

        except Exception as e:
            self.logger.error(f"Erro ao buscar filme '{title}': {e}")
            return None

    def search_tvshow(self, title: str, year: Optional[int] = None, interactive: bool = False) -> Optional[Metadata]:
        """
        Busca metadados de uma série.

        Args:
            title: Título da série
            year: Ano (opcional)
            interactive: Se True, permite escolher entre múltiplos resultados

        Returns:
            Metadata ou None se não encontrado
        """
        tmdb = self._init_tmdb()
        if not tmdb:
            return None

        try:
            # Limpa o título
            clean_title = self._clean_search_title(title)

            # Cria chave de cache para evitar perguntar múltiplas vezes
            cache_key = (clean_title.lower(), year)

            # Verifica se já temos uma escolha em cache
            if cache_key in self._interactive_choices_cache:
                cached_choice = self._interactive_choices_cache[cache_key]
                if cached_choice is None:
                    return None
                self.logger.debug(f"Usando escolha em cache para '{clean_title}' ({year})")
                return cached_choice

            # Skip re-querying titles that already returned no results
            if cache_key in self._failed_searches:
                self.logger.debug(f"Busca já falhou anteriormente para série '{clean_title}' ({year}), pulando")
                return None

            # Busca incremental: tenta com título completo, depois vai removendo palavras do final
            results = self._search_tvshow_with_fallback(tmdb['tv'], clean_title)

            # Verifica se há resultados reais (total_results > 0)
            if not results or results.total_results == 0:
                self.logger.debug(f"Nenhum resultado para série: {clean_title}")
                self._failed_searches.add(cache_key)
                return None

            # Se modo interativo e múltiplos resultados, pede escolha
            if interactive and len(results) > 1 and self.config.ask_on_multiple_results:
                show = self._choose_tvshow_interactive(results, clean_title, year)
                if not show:
                    self._interactive_choices_cache[cache_key] = None
                    return None
            else:
                # ANTI-ERRO: mesma trava de confiança já usada para filmes.
                # Antes a série pegava o PRIMEIRO resultado sem nenhuma
                # verificação — foi assim que "Dr STONE" (que a limpeza de
                # nome tinha reduzido a "Dr") virou "Dr. House" e arrastou a
                # temporada inteira para a pasta errada.
                show, score = self._best_candidate(results, clean_title, year)
                if not show:
                    self._failed_searches.add(cache_key)
                    return None

                threshold = getattr(self.config, "match_confidence_threshold", 0.55)
                if score < threshold:
                    self.logger.warning(
                        f"✗ Baixa confiança ({score:.2f} < {threshold:.2f}) para série "
                        f"'{clean_title}' ({year}) → melhor candidato: "
                        f"'{getattr(show, 'name', '?')}' "
                        f"[id {getattr(show, 'id', '?')}]. Pulando (revisar manualmente)."
                    )
                    self._record_low_confidence(clean_title, year, show, score)
                    self._interactive_choices_cache[cache_key] = None
                    return None

                self.logger.debug(
                    f"✓ Match confiável ({score:.2f}) série '{clean_title}' ({year}) → "
                    f"'{getattr(show, 'name', '?')}' [id {getattr(show, 'id', '?')}]"
                )

            if not show:
                # Nenhum resultado iterável retornou objeto válido
                self._interactive_choices_cache[cache_key] = None
                return None

            # Extrai ano
            show_year = None
            if hasattr(show, 'first_air_date') and show.first_air_date:
                match = re.search(r'^(\d{4})', show.first_air_date)
                if match:
                    show_year = int(match.group(1))

            # Build image URLs
            poster_path = getattr(show, 'poster_path', None)
            backdrop_path = getattr(show, 'backdrop_path', None)

            base_url = "https://image.tmdb.org/t/p"
            poster_url = f"{base_url}/w500{poster_path}" if poster_path else None
            backdrop_url = f"{base_url}/w1280{backdrop_path}" if backdrop_path else None

            metadata = Metadata(
                title=show.name,
                year=show_year,
                tmdb_id=show.id,
                original_title=getattr(show, 'original_name', None),
                overview=getattr(show, 'overview', None),
                poster_path=poster_path,
                backdrop_path=backdrop_path,
                poster_url=poster_url,
                backdrop_url=backdrop_url
            )

            # Salva no cache para reutilizar em arquivos subsequentes
            self._interactive_choices_cache[cache_key] = metadata

            return metadata

        except Exception as e:
            self.logger.error(f"Erro ao buscar série '{title}': {e}")
            return None

    def _clean_search_title(self, title: str) -> str:
        """
        Limpa o título para busca usando heurísticas estruturais.

        Estratégia:
        1. Detecta o ano e pega apenas até ele (geralmente após o ano é lixo)
        2. Remove informações técnicas óbvias
        3. Remove grupos de release

        Args:
            title: Título original

        Returns:
            Título limpo
        """
        original = title

        # Remove informações entre colchetes e parênteses (exceto ano)
        title = re.sub(r'\[[^\]]*\]', '', title)
        title = re.sub(r'\([^\)]*(?:1080|720|480|BluRay|WEB|HDTV|DVDRip)[^\)]*\)', '', title)

        # Substitui separadores por espaços
        title = title.replace('.', ' ').replace('_', ' ').replace('-', ' ')

        # HEURÍSTICA 1: Se tem ano (1900-2099), pega apenas até o ano
        # Ex: "Movie Name 2020 1080p BluRay" -> "Movie Name 2020"
        # IMPORTANTE: só trunca num ano que tenha TÍTULO antes dele. Arquivos
        # com o ano no começo ("1989 Sexta 13 Parte VIII ...") truncariam para
        # só "1989" e casariam com qualquer filme daquele ano (bug real visto
        # com um filme chinês). Nesses casos, remove o ano inicial e segue.
        year_iters = list(re.finditer(r'\b(19\d{2}|20\d{2})\b', title))
        chosen_year = None
        for ym in year_iters:
            if len(title[:ym.start()].strip()) >= 2:  # há texto real antes do ano
                chosen_year = ym
                break
        if chosen_year:
            # Pega tudo até o final do ano
            title = title[:chosen_year.end()].strip()
        elif year_iters:
            # Ano(s) só no início: remove os anos iniciais e limpa o resto abaixo
            title = re.sub(r'^\s*(?:19\d{2}|20\d{2})\b\s*', '', title).strip()
            year_match = None
        else:
            year_match = None
        if not chosen_year:
            # HEURÍSTICA 2: Se não tem ano, detecta onde começa a parte técnica
            # Procura pela primeira ocorrência de padrões técnicos
            technical_start = None

            # Padrões que indicam início de metadados técnicos
            technical_patterns = [
                r'\b(1080p|720p|480p|2160p|4K|8K)\b',  # Resoluções
                r'\b(BluRay|BRRip|WEB-?DL|WEBRip|HDTV|DVDRip|BDRip)\b',  # Formatos
                r'\b(x264|x265|H\.?264|H\.?265|HEVC|XviD)\b',  # Codecs
                r'\b(AAC|AC3|DTS|DD|MP3|FLAC)\b',  # Áudio
                r'\b(DUAL|Dual\.?Audio)\b',  # Dual audio
            ]

            for pattern in technical_patterns:
                match = re.search(pattern, title, re.IGNORECASE)
                if match:
                    if technical_start is None or match.start() < technical_start:
                        technical_start = match.start()

            if technical_start is not None and technical_start > 0:
                title = title[:technical_start].strip()

        # Remove parênteses/colchetes soltos que sobraram (ex.: "Frozen (2013"
        # ficava com um '(' órfão e poluía a busca no TMDB).
        title = re.sub(r'[\(\)\[\]]', ' ', title)

        # Remove espaços múltiplos
        title = re.sub(r'\s+', ' ', title).strip()

        # Se ficou muito curto (< 2 palavras), usa o original limpo
        if len(title.split()) < 2:
            fallback = original.replace('.', ' ').replace('_', ' ')
            fallback = re.sub(r'[\(\)\[\]]', ' ', fallback)
            fallback = re.sub(r'\s+', ' ', fallback).strip()
            if fallback:  # restaura mesmo se 1 palavra (ex.: "1917", "1984")
                title = fallback

        # O ANO vai SEPARADO no parâmetro year= da API. Mantê-lo como texto na
        # string de busca distorce os resultados (ex.: "Frozen 2013" não retorna
        # o Frozen da Disney; "Frozen" retorna). Remove o ano do texto da busca.
        title_no_year = re.sub(r'\b(?:19\d{2}|20\d{2})\b', ' ', title)
        title_no_year = re.sub(r'\s+', ' ', title_no_year).strip()
        if title_no_year:  # não deixa vazio (caso o "título" fosse só o ano)
            title = title_no_year

        return title

    def get_folder_name(self, metadata: Metadata, provider_id: bool = False) -> str:
        """
        Gera nome de pasta no padrão Jellyfin.

        Args:
            metadata: Metadados
            provider_id: Se deve incluir ID do provedor

        Returns:
            Nome da pasta formatado
        """
        if metadata.year:
            folder_name = f"{metadata.title} ({metadata.year})"
        else:
            folder_name = metadata.title

        # Adiciona ID do provedor se solicitado
        if provider_id:
            if metadata.tmdb_id:
                folder_name += f" [tmdbid-{metadata.tmdb_id}]"
            elif metadata.imdb_id:
                folder_name += f" [imdbid-{metadata.imdb_id}]"
            elif metadata.tvdb_id:
                folder_name += f" [tvdbid-{metadata.tvdb_id}]"

        return folder_name

    def _choose_movie_interactive(self, results: List, search_title: str, year: Optional[int] = None):
        """
        Permite escolher interativamente entre múltiplos resultados de filme.

        Args:
            results: Lista de resultados do TMDB
            search_title: Título da busca
            year: Ano da busca (opcional, mostrado na mensagem)

        Returns:
            Resultado escolhido ou None
        """
        try:
            import questionary
            from rich.console import Console

            console = Console()
            search_info = f"{search_title}" + (f" ({year})" if year else "")
            console.print(f"\n[yellow]⚠️  Múltiplos resultados encontrados para:[/yellow] [cyan]{search_info}[/cyan]")
            console.print("[dim]💡 Sua escolha será aplicada a todos os arquivos com este título[/dim]\n")

            # Prepara opções para seleção
            choices = []
            # Itera diretamente (sem slice, pois AsObj não suporta)
            for i, movie in enumerate(results):
                if i >= 10:  # Máximo 10 resultados
                    break
                year = ""
                if hasattr(movie, 'release_date') and movie.release_date:
                    match = re.search(r'^(\d{4})', movie.release_date)
                    if match:
                        year = f" ({match.group(1)})"

                # Link do TMDB
                tmdb_link = f"https://www.themoviedb.org/movie/{movie.id}"

                # Descrição resumida
                overview = ""
                if hasattr(movie, 'overview') and movie.overview:
                    overview = movie.overview[:80] + "..." if len(movie.overview) > 80 else movie.overview

                label = f"{movie.title}{year}"
                if overview:
                    label += f" - {overview}"

                choices.append(questionary.Choice(
                    title=label,
                    value=(movie, tmdb_link)
                ))

            # Adiciona opção para pular
            choices.append(questionary.Choice(
                title="❌ Nenhum destes / Pular",
                value=None
            ))

            # Pergunta ao usuário
            from ..cli.interactive import custom_style
            result = questionary.select(
                "Escolha o resultado correto:",
                choices=choices,
                style=custom_style,
                instruction="(Use ↑↓ para navegar, ENTER para confirmar)"
            ).ask()

            if result:
                selected_movie, tmdb_link = result
                console.print(f"\n[green]✓ Selecionado:[/green] {selected_movie.title}")
                console.print(f"[dim]🔗 Link: {tmdb_link}[/dim]\n")
                return selected_movie

            return None

        except ImportError:
            # Se questionary não disponível, usa o primeiro resultado
            self.logger.warning("Modo interativo não disponível. Usando primeiro resultado.")
            for result in results:
                return result
        except Exception as e:
            self.logger.error(f"Erro na escolha interativa: {e}")
            # Retorna primeiro resultado (itera pois AsObj não suporta indexação)
            for result in results:
                return result
            return None

    def _choose_tvshow_interactive(self, results: List, search_title: str, year: Optional[int] = None):
        """
        Permite escolher interativamente entre múltiplos resultados de série.

        Args:
            results: Lista de resultados do TMDB
            search_title: Título da busca
            year: Ano da busca (opcional, mostrado na mensagem)

        Returns:
            Resultado escolhido ou None
        """
        try:
            import questionary
            from rich.console import Console

            console = Console()
            search_info = f"{search_title}" + (f" ({year})" if year else "")
            console.print(f"\n[yellow]⚠️  Múltiplos resultados encontrados para:[/yellow] [cyan]{search_info}[/cyan]")
            console.print("[dim]💡 Sua escolha será aplicada a todos os arquivos com este título[/dim]\n")

            # Prepara opções para seleção
            choices = []
            # Itera diretamente (sem slice, pois AsObj não suporta)
            for i, show in enumerate(results):
                if i >= 10:  # Máximo 10 resultados
                    break
                year = ""
                if hasattr(show, 'first_air_date') and show.first_air_date:
                    match = re.search(r'^(\d{4})', show.first_air_date)
                    if match:
                        year = f" ({match.group(1)})"

                # Link do TMDB
                tmdb_link = f"https://www.themoviedb.org/tv/{show.id}"

                # Descrição resumida
                overview = ""
                if hasattr(show, 'overview') and show.overview:
                    overview = show.overview[:80] + "..." if len(show.overview) > 80 else show.overview

                label = f"{show.name}{year}"
                if overview:
                    label += f" - {overview}"

                choices.append(questionary.Choice(
                    title=label,
                    value=(show, tmdb_link)
                ))

            # Adiciona opção para pular
            choices.append(questionary.Choice(
                title="❌ Nenhum destes / Pular",
                value=None
            ))

            # Pergunta ao usuário
            from ..cli.interactive import custom_style
            result = questionary.select(
                "Escolha o resultado correto:",
                choices=choices,
                style=custom_style,
                instruction="(Use ↑↓ para navegar, ENTER para confirmar)"
            ).ask()

            if result:
                selected_show, tmdb_link = result
                console.print(f"\n[green]✓ Selecionado:[/green] {selected_show.name}")
                console.print(f"[dim]🔗 Link: {tmdb_link}[/dim]\n")
                return selected_show

            return None

        except ImportError:
            # Se questionary não disponível, usa o primeiro resultado
            self.logger.warning("Modo interativo não disponível. Usando primeiro resultado.")
            for result in results:
                return result
        except Exception as e:
            self.logger.error(f"Erro na escolha interativa: {e}")
            # Retorna primeiro resultado (itera pois AsObj não suporta indexação)
            for result in results:
                return result
            return None
