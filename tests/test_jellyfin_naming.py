"""Testes ancorados na documentação oficial do Jellyfin.

As fixtures aqui são, sempre que possível, os exemplos LITERAIS da doc:

  - https://jellyfin.org/docs/general/server/media/movies/
  - https://jellyfin.org/docs/general/server/media/shows/
  - docs/general/server/media/_video-external-streams.md   (legendas/áudio)
  - docs/general/server/media/_video-external-extras.md    (extras)
  - docs/general/server/media/_metadata-images.md          (artes)

e o comportamento esperado é o do parser real do servidor
(``Emby.Naming``). A ideia é que qualquer regressão nesses casos quebre a
suíte antes de chegar na biblioteca de alguém.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "usr" / "share"))

from jellyfix.core.renamer import RenameOperation  # noqa: E402
from jellyfix.utils.config import Config, set_config  # noqa: E402
from jellyfix.utils.helpers import (  # noqa: E402
    build_subtitle_name,
    has_language_code,
    is_extras_path,
    is_jellyfin_image,
    normalize_spaces,
    parse_operation_for_search,
    parse_subtitle_name,
)

PT_BODY = (
    "1\n00:00:01,000 --> 00:00:02,000\n"
    "que não para com uma mais muito está você ele ela\n\n"
) * 30
EN_BODY = "1\n00:00:01,000 --> 00:00:02,000\nHello there my friend\n\n" * 30


@pytest.fixture(autouse=True)
def _config(tmp_path):
    """Config limpa por teste (o singleton global é compartilhado)."""
    cfg = Config(work_dir=tmp_path, fetch_metadata=False, dry_run=True)
    set_config(cfg)
    return cfg


# ---------------------------------------------------------------------------
# Títulos: hífen é permitido pelo Jellyfin (não está entre < > : " / \ | ? *)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,expected", [
    ("Spider-Man.2002.1080p.BluRay.x264-RARBG", "Spider-Man"),
    ("X-Men.Days.of.Future.Past.2014.1080p", "X-Men Days of Future Past"),
    ("Ant-Man.and.the.Wasp.2018", "Ant-Man and the Wasp"),
    ("WALL-E.2008.1080p", "WALL-E"),
    ("Anne-Marie.Live.2019", "Anne-Marie Live"),
])
def test_hifen_no_titulo_e_preservado(filename, expected):
    """Regressão: '-Man'/'-Men' eram removidos como se fossem release group."""
    assert normalize_spaces(filename) == expected


@pytest.mark.parametrize("filename", [
    "Filme.2020.1080p.BluRay.x264-3LT0N",
    "Movie.2019.720p.WEB-DL-GalaxyRG",
    "Serie.2021.1080p-RARBG",
])
def test_grupo_de_release_ainda_e_removido(filename):
    assert "-" not in normalize_spaces(filename).split()[-1]


def test_palavra_maiuscula_do_titulo_nao_e_removida():
    """Regressão real: 'Dr.STONE' virava 'Dr' e o TMDB devolvia 'Dr. House'."""
    assert normalize_spaces("Dr.STONE.") == "Dr STONE"


def test_busca_manual_parte_do_arquivo_de_origem():
    """A busca manual existe para corrigir um match errado.

    Se ela for pré-preenchida a partir do destino (já errado), continua
    procurando a obra errada — foi o que aconteceu com Dr. Stone/Dr. House.
    """
    class _Op:
        source = Path("/dl/Dr.STONE.S01E20.1080p.CR.WEB-DL.AAC2.0.H.264.DUAL-BiOMA.mkv")
        destination = Path("/dl/Dr. House (2004) [tmdbid-1408]/Season 01/Dr. House - S01E20.mkv")

    parsed = parse_operation_for_search(_Op())
    assert parsed["title"] == "Dr STONE"
    assert parsed["is_episode"] is True
    assert (parsed["season"], parsed["episode"]) == (1, 20)
    # O ano do destino errado não pode contaminar a busca
    assert parsed["year"] is None


# ---------------------------------------------------------------------------
# Legendas externas — _video-external-streams.md
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stem,language,forced,hi", [
    ("Film.default", None, False, False),
    ("Film.default.en.forced", "eng", True, False),
    ("Film.forced.en", "eng", True, False),
    ("Film.en.sdh", "eng", False, True),
    ("Film.eng.cc", "eng", False, True),
    # "hi" sozinho = Hindi; com outro idioma = surdez (regra da doc)
    ("Film.hi", "hin", False, False),
    ("Film.en.hi", "eng", False, True),
    ("Film.hi.en", "eng", False, True),
    ("Film.English Commentary.en", "eng", False, False),
    ("The.Great.Flood", None, False, False),
])
def test_flags_de_legenda_da_doc(stem, language, forced, hi):
    info = parse_subtitle_name(stem)
    assert info["language"] == language
    assert info["forced"] is forced
    assert info["hearing_impaired"] is hi


def test_base_name_preserva_pontos_do_titulo():
    assert parse_subtitle_name("The.Great.Flood")["base_name"] == "The.Great.Flood"
    assert parse_subtitle_name("Dr. House - S01E20.eng")["base_name"] == "Dr. House - S01E20"


def test_codigo_de_idioma_de_3_letras():
    """O jellyfix escreve por/eng — é o que o Jellyfin resolve e exibe certo."""
    assert build_subtitle_name("Movie", "por", ".srt") == "Movie.por.srt"
    assert build_subtitle_name("Movie", "eng", ".srt") == "Movie.eng.srt"
    assert build_subtitle_name("Movie", "spa", ".srt") == "Movie.spa.srt"
    assert build_subtitle_name("Movie", "por", ".srt", hearing_impaired=True) == "Movie.por.sdh.srt"
    assert build_subtitle_name("Movie", "eng", ".srt", forced=True) == "Movie.eng.forced.srt"


def test_pt_pt_e_a_unica_excecao_as_3_letras():
    """ISO 639-2 não separa pt-PT de pt-BR (ambos "por").

    ``por-pt`` é código interno do jellyfix e não existe para o Jellyfin:
    ``FindLanguageInfo()`` não casa com nada e a legenda entra sem idioma.
    O servidor aceita a forma com região — ``iso6392.txt`` traz
    "por||pt-pt|Portuguese (Portugal)" e ``ExternalPathParser`` preserva nomes
    de cultura contendo '-'. Só nesse caso gravamos ``pt-PT``.
    """
    assert build_subtitle_name("Movie", "por-pt", ".srt") == "Movie.pt-PT.srt"
    assert build_subtitle_name("Movie", "por-pt", ".srt", forced=True) == "Movie.pt-PT.forced.srt"
    assert build_subtitle_name("Movie", "por-pt", ".srt", hearing_impaired=True) == "Movie.pt-PT.sdh.srt"
    # pt-BR continua sendo o "por" genérico de 3 letras
    assert build_subtitle_name("Movie", "por", ".srt") == "Movie.por.srt"


@pytest.mark.parametrize("filename,internal", [
    ("Movie.pt-PT.srt", "por-pt"),
    ("Movie.pt-pt.srt", "por-pt"),
    ("Movie.pt-PT.sdh.srt", "por-pt"),
    ("Movie.pt-BR.srt", "por"),
    ("Movie.por.srt", "por"),
])
def test_ida_e_volta_do_codigo_de_idioma(filename, internal):
    """O que o jellyfix grava, ele precisa saber reler (idempotência)."""
    assert has_language_code(filename) == internal


def test_pt_pt_sobrevive_a_um_segundo_passe(tmp_path, _config):
    """Reprocessar uma pasta não pode mexer numa legenda pt-PT já correta."""
    from jellyfix.core.renamer import Renamer
    from jellyfix.core.scanner import scan_library

    root = tmp_path / "Filmes"
    movie_dir = root / "Matrix (1999)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Matrix (1999) - 1080p.mkv").write_bytes(b"x" * 10)
    (movie_dir / "Matrix (1999) - 1080p.pt-PT.srt").write_text(PT_BODY)

    _config.work_dir = root
    _config.kept_languages = ["por", "por-pt", "eng"]

    ops = Renamer().plan_operations(root, scan_library(root))
    sub_ops = [op for op in ops if op.source.suffix == ".srt"]

    # Nada a fazer: nem renomear, nem apagar
    assert sub_ops == []


@pytest.mark.parametrize("filename,expected", [
    ("Movie.eng.cc.srt", "eng"),
    ("Movie.en.sdh.srt", "eng"),
    ("Movie.pt-BR.srt", "por"),
    ("The.Great.Flood.srt", None),
    ("Movie.mkv", None),
])
def test_has_language_code(filename, expected):
    assert has_language_code(filename) == expected


def test_legenda_com_flag_nao_e_apagada_como_estrangeira(tmp_path, _config):
    """Regressão: .eng.cc/.eng.hi/.en.sdh eram lidos como idioma e DELETADOS."""
    from jellyfix.core.renamer import Renamer
    from jellyfix.core.scanner import scan_library

    movie_dir = tmp_path / "Filmes" / "Best_Movie_Ever (2019)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Best_Movie_Ever (2019).mp4").write_bytes(b"x" * 10)
    for name in ("eng.cc", "en.sdh", "eng.hi", "eng"):
        (movie_dir / f"Best_Movie_Ever (2019).{name}.srt").write_text(EN_BODY)
    (movie_dir / "Best_Movie_Ever (2019).fre.srt").write_text(EN_BODY)

    _config.work_dir = tmp_path / "Filmes"
    scan = scan_library(_config.work_dir)
    ops = Renamer().plan_operations(_config.work_dir, scan)

    deleted = {op.source.name for op in ops if op.operation_type == "delete"}
    assert "Best_Movie_Ever (2019).eng.cc.srt" not in deleted
    assert "Best_Movie_Ever (2019).en.sdh.srt" not in deleted
    assert "Best_Movie_Ever (2019).eng.hi.srt" not in deleted
    # Idioma realmente estrangeiro continua sendo removido
    assert "Best_Movie_Ever (2019).fre.srt" in deleted


# ---------------------------------------------------------------------------
# Extras — _video-external-extras.md
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("relative", [
    "Best_Movie_Ever (2019)/trailer.mp4",
    "Best_Movie_Ever (2019)/sample.mp4",
    "Best_Movie_Ever (2019)/Preview Trailer.trailer.mp4",
    "Best_Movie_Ever (2019)/Making of The Best Movie Ever-behindthescenes.mp4",
    "Best_Movie_Ever (2019)/behind the scenes/Finding the right score.mp4",
    "Best_Movie_Ever (2019)/extras/Home recreation.mp4",
    "Awesome TV Show (2024)/Season 1/trailers/trailer1.mp4",
    "Awesome TV Show (2024)/theme-music/Series Opening.wav",
])
def test_extras_sao_reconhecidos(relative):
    assert is_extras_path(Path(relative)) is True


def test_midia_principal_nao_e_extra():
    assert is_extras_path(Path("Best_Movie_Ever (2019)/Best_Movie_Ever (2019).mp4")) is False
    assert is_extras_path(Path("Series/Season 1/Series S01E01.mkv")) is False


def test_extras_nao_viram_filmes(tmp_path, _config):
    """Regressão: trailer.mp4 e bastidores eram renomeados como filmes."""
    from jellyfix.core.renamer import Renamer
    from jellyfix.core.scanner import scan_library

    root = tmp_path / "Filmes"
    movie_dir = root / "Best_Movie_Ever (2019)"
    (movie_dir / "behind the scenes").mkdir(parents=True)
    (movie_dir / "Best_Movie_Ever (2019).mp4").write_bytes(b"x" * 10)
    (movie_dir / "trailer.mp4").write_bytes(b"x" * 10)
    (movie_dir / "behind the scenes" / "Finding the right score.mp4").write_bytes(b"x" * 10)

    _config.work_dir = root
    scan = scan_library(root)

    assert [p.name for p in scan.video_files] == ["Best_Movie_Ever (2019).mp4"]
    assert len(scan.extras_files) == 2

    # Extras podem ser MOVIDOS junto com o filme, mas nunca renomeados como se
    # fossem um filme (que era o bug: viravam "Filmes/trailer/trailer.mp4").
    for op in Renamer().plan_operations(root, scan):
        if op.source.name in ("trailer.mp4", "Finding the right score.mp4"):
            assert op.operation_type == "move", "extra foi tratado como filme"
            assert op.destination.name == op.source.name, "extra foi renomeado"


# ---------------------------------------------------------------------------
# Artes — _metadata-images.md
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "cover.jpg", "folder.jpg", "poster.png", "backdrop.webp", "logo.png",
    "banner.jpg", "thumb.jpg", "clearlogo.png", "landscape.jpg", "disc.png",
    "backdrop-1.jpg", "backdrop2.jpg", "movie-logo.png",
    "S01E01 Some Episode-thumb.jpg",
])
def test_artes_reconhecidas_pelo_jellyfin(name):
    assert is_jellyfin_image(Path(name)) is True


@pytest.mark.parametrize("name", ["IMG_2043.jpg", "random-screenshot.jpg"])
def test_imagem_aleatoria_nao_e_arte(name):
    assert is_jellyfin_image(Path(name)) is False


def test_artes_do_jellyfin_nao_sao_marcadas_como_indesejadas(tmp_path, _config):
    """cover.jpg/folder.jpg eram classificados como imagem indesejada.

    (``remove_non_media`` continua podendo apagá-las: é uma opção explícita,
    desligada por padrão. O que se corrige aqui é a CLASSIFICAÇÃO.)
    """
    from jellyfix.core.scanner import scan_library

    root = tmp_path / "Filmes"
    movie_dir = root / "Movie (2035)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Movie (2035).mp4").write_bytes(b"x" * 10)
    for name in ("cover.jpg", "backdrop.webp", "logo.png", "folder.jpg"):
        (movie_dir / name).write_bytes(b"x" * 10)
    (movie_dir / "IMG_2043.jpg").write_bytes(b"x" * 10)

    _config.work_dir = root
    scan = scan_library(root)

    unwanted = {p.name for p in scan.unwanted_images}
    assert unwanted == {"IMG_2043.jpg"}


# ---------------------------------------------------------------------------
# Estrutura de saída — movies.md / shows.md
# ---------------------------------------------------------------------------

def test_filme_segue_o_padrao_da_doc(tmp_path, _config):
    from jellyfix.core.renamer import Renamer
    from jellyfix.core.scanner import scan_library

    root = tmp_path / "Filmes"
    root.mkdir(parents=True)
    (root / "Spider-Man.2002.1080p.BluRay.x264-RARBG.mkv").write_bytes(b"x" * 10)

    _config.work_dir = root
    ops = Renamer().plan_operations(root, scan_library(root))
    dest = next(op.destination for op in ops if op.source.suffix == ".mkv")

    # "Movie Name (year)" na pasta e no arquivo, com rótulo de versão " - 1080p"
    assert dest.parent.name == "Spider-Man (2002)"
    assert dest.name == "Spider-Man (2002) - 1080p.mkv"


def test_serie_usa_pasta_season_com_zero_a_esquerda(tmp_path, _config):
    """A doc proíbe abreviar (S01/SE01) e recomenda zero-padding."""
    from jellyfix.core.renamer import Renamer
    from jellyfix.core.scanner import scan_library

    root = tmp_path / "Series"
    show = root / "Breaking Bad"
    show.mkdir(parents=True)
    (show / "Breaking.Bad.S01E01.720p.mkv").write_bytes(b"x" * 10)

    _config.work_dir = root
    ops = Renamer().plan_operations(root, scan_library(root))
    dest = next(op.destination for op in ops if op.source.suffix == ".mkv")

    assert dest.parent.name == "Season 01"
    assert dest.name == "Breaking Bad - S01E01.mkv"


def test_legenda_acompanha_o_video_com_codigo_de_3_letras(tmp_path, _config):
    from jellyfix.core.renamer import Renamer
    from jellyfix.core.scanner import scan_library

    root = tmp_path / "Filmes"
    root.mkdir(parents=True)
    (root / "Matrix.1999.1080p.mkv").write_bytes(b"x" * 10)
    (root / "Matrix.1999.1080p.por.srt").write_text(PT_BODY)

    _config.work_dir = root
    ops = Renamer().plan_operations(root, scan_library(root))
    video = next(op for op in ops if op.source.suffix == ".mkv")
    sub = next(op for op in ops if op.source.suffix == ".srt")

    assert sub.destination.name == "Matrix (1999) - 1080p.por.srt"
    # A legenda tem que ir para a MESMA pasta do vídeo
    assert sub.destination.parent == video.destination.parent


def test_variante_nao_fica_orfa_ao_mover_o_video(tmp_path, _config):
    """Com remove_language_variants=False (padrão), .por2 não podia ser esquecida."""
    from jellyfix.core.renamer import Renamer
    from jellyfix.core.scanner import scan_library

    root = tmp_path / "Filmes"
    root.mkdir(parents=True)
    (root / "Matrix.1999.1080p.mkv").write_bytes(b"x" * 10)
    (root / "Matrix.1999.1080p.por.srt").write_text(PT_BODY)
    (root / "Matrix.1999.1080p.por2.srt").write_text(PT_BODY * 2)

    _config.work_dir = root
    _config.remove_language_variants = False
    ops = Renamer().plan_operations(root, scan_library(root))

    sources = {op.source.name for op in ops}
    assert "Matrix.1999.1080p.por2.srt" in sources, "variante ficou órfã na pasta antiga"


def test_limpeza_de_pastas_nunca_sobe_acima_do_workdir(tmp_path, _config):
    """A limpeza subia até len(parts)<=2 e podia remover /mnt/media."""
    from jellyfix.core.renamer import Renamer

    outer = tmp_path / "biblioteca"
    work = outer / "Filmes"
    source = work / "Sub"
    source.mkdir(parents=True)

    renamer = Renamer()
    renamer.operations = []
    renamer.work_dir = work
    renamer.execute_operations(dry_run=False)

    assert outer.exists()
    assert work.exists()


def test_pasta_de_origem_vazia_e_removida_quando_e_o_proprio_workdir(tmp_path, _config):
    """Regressão: apontar o jellyfix para a PRÓPRIA pasta da mídia.

    Os arquivos vão para uma pasta irmã e a original fica vazia. Exigir que a
    pasta estivesse "estritamente dentro" do work_dir deixava justamente esse
    caso de fora, e a pasta vazia ficava para trás como lixo.
    """
    from jellyfix.core.metadata import Metadata
    from jellyfix.core.renamer import Renamer

    container = tmp_path / "Filmes"
    work = container / "The.Death.of.Robin.Hood.2026.1080p.AMZN.WEB-DL-SCOPE"
    work.mkdir(parents=True)
    video = work / "The.Death.of.Robin.Hood.2026.1080p.mp4"
    video.write_bytes(b"x" * 10)

    _config.work_dir = work

    renamer = Renamer()
    renamer.replan_for_video_with_metadata(
        video,
        Metadata(
            title="A Morte de Robin Hood",
            year=2026,
            tmdb_id=1284465,
            original_title="The Death of Robin Hood",
            media_type="movie",
        ),
    )
    stats = renamer.execute_operations(dry_run=False)

    destino = container / "A Morte de Robin Hood (2026) [tmdbid-1284465]"
    assert (destino / "A Morte de Robin Hood (2026) - 1080p.mp4").exists()
    assert not work.exists(), "pasta de origem vazia ficou para trás"
    assert stats["cleaned"] >= 1
    # E o container acima do work_dir continua intocado
    assert container.exists()


def test_extras_acompanham_o_video_preservando_subpasta(tmp_path, _config):
    """Extras pertencem à pasta da mídia e devem migrar com ela.

    Protegê-los de virar filme não basta: se ficarem para trás, a pasta antiga
    sobrevive como lixo e o Jellyfin perde os extras.
    """
    from jellyfix.core.metadata import Metadata
    from jellyfix.core.renamer import Renamer

    root = tmp_path / "Filmes"
    release = root / "Interstellar.2014.1080p.BluRay.x264-SPARKS"
    (release / "behind the scenes").mkdir(parents=True)
    video = release / "Interstellar.2014.1080p.BluRay.x264-SPARKS.mkv"
    video.write_bytes(b"x" * 10)
    (release / "trailer.mp4").write_bytes(b"x" * 10)
    (release / "behind the scenes" / "Making of.mp4").write_bytes(b"x" * 10)

    _config.work_dir = root
    renamer = Renamer()
    renamer.replan_for_video_with_metadata(
        video,
        Metadata(title="Interestelar", year=2014, tmdb_id=157336,
                 original_title="Interstellar", media_type="movie"),
    )
    renamer.execute_operations(dry_run=False)

    destino = root / "Interestelar (2014) [tmdbid-157336]"
    assert (destino / "trailer.mp4").exists()
    assert (destino / "behind the scenes" / "Making of.mp4").exists()
    assert not release.exists(), "pasta de release ficou para trás"


def test_extras_nao_vazam_entre_filmes_soltos(tmp_path, _config):
    """Com vídeos SOLTOS na raiz, a 'pasta de origem' é o próprio work_dir.

    Varrê-lo recursivamente arrastava os extras de um filme para dentro da
    pasta de outro.
    """
    from jellyfix.core.renamer import Renamer
    from jellyfix.core.scanner import scan_library

    root = tmp_path / "Filmes"
    outro = root / "Outro.Filme.2020.1080p-GRP"
    outro.mkdir(parents=True)
    (outro / "Outro.Filme.2020.1080p-GRP.mkv").write_bytes(b"x" * 10)
    (outro / "trailer.mp4").write_bytes(b"x" * 10)
    # vídeo solto na raiz, sem pasta própria
    (root / "Matrix.1999.1080p-RARBG.mkv").write_bytes(b"x" * 10)

    _config.work_dir = root
    ops = Renamer().plan_operations(root, scan_library(root))

    trailer_ops = [op for op in ops if op.source.name == "trailer.mp4"]
    for op in trailer_ops:
        assert "Matrix" not in str(op.destination), "extra vazou para outro filme"


def test_container_do_workdir_nunca_e_removido(tmp_path, _config):
    """Mesmo esvaziando tudo, nada acima do work_dir pode ser apagado."""
    from jellyfix.core.renamer import Renamer

    outer = tmp_path / "biblioteca"
    work = outer / "Filmes"
    source = work / "Release"
    source.mkdir(parents=True)
    origem = source / "a.txt"
    origem.write_text("x")
    destino = tmp_path / "fora" / "a.txt"

    renamer = Renamer()
    renamer.work_dir = work
    renamer.operations = [
        RenameOperation(source=origem, destination=destino, operation_type="move", reason="teste")
    ]
    renamer.execute_operations(dry_run=False)

    assert not source.exists()  # esvaziada -> removida
    assert outer.exists()       # acima do work_dir: NUNCA é tocado
    assert tmp_path.exists()
