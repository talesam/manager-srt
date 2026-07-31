#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/windows/simulation_window.py - Pré-visualização detalhada (dry-run)
#

"""
Janela de simulação: mostra, arquivo por arquivo, exatamente o que será feito.

O resumo em caixinha de diálogo ("99 operações") não respondia a pergunta que
importa antes de apertar Aplicar: *o que vai acontecer com CADA arquivo?*.
Aqui a informação aparece com o mesmo vocabulário visual do modo CLI —
uma etiqueta colorida por tipo de operação, o nome que sai e o nome que entra.
"""

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, Pango  # noqa: E402

from ...utils.i18n import _  # noqa: E402


def _escape(value) -> str:
    """Escapa texto para uso em markup do Pango."""
    from html import escape
    return escape(str(value))


# Mesmo esquema do CLI (cli/non_interactive.py), para quem usa os dois modos
# reconhecer na hora: renomear = accent, mover = sucesso, excluir = erro.
OPERATION_STYLES = {
    'rename': ('✏️', _("RENAME"), 'sim-rename'),
    'move': ('📦', _("MOVE"), 'sim-move'),
    'move_rename': ('📦✏️', _("MOVE+RENAME"), 'sim-move-rename'),
    'delete': ('🗑️', _("DELETE"), 'sim-delete'),
}


class SimulationWindow(Adw.Window):
    """Pré-visualização detalhada das operações planejadas."""

    def __init__(self, parent, operations, work_dir=None):
        super().__init__(transient_for=parent, modal=True)

        self.operations = list(operations or [])
        self.work_dir = work_dir

        self.set_title(_("Simulation — nothing will be changed"))
        self.set_default_size(980, 720)

        toolbar = Adw.ToolbarView()

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(
            title=_("Simulation"),
            subtitle=_("Preview only — no file is touched"),
        ))
        toolbar.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(self._build_summary())

        # Filtro por tipo, para inspecionar só as exclusões, por exemplo
        self._filter = 'all'
        content.append(self._build_filter_bar())

        self._scrolled = Gtk.ScrolledWindow()
        self._scrolled.set_vexpand(True)
        self._scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self._list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._list_box.set_margin_top(6)
        self._list_box.set_margin_bottom(12)
        self._list_box.set_margin_start(12)
        self._list_box.set_margin_end(12)
        self._scrolled.set_child(self._list_box)
        content.append(self._scrolled)

        toolbar.set_content(content)

        # Rodapé
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        footer.set_margin_top(8)
        footer.set_margin_bottom(8)
        footer.set_margin_start(12)
        footer.set_margin_end(12)

        aviso = Gtk.Label()
        aviso.set_markup(
            f"<b>{_escape(_('Nothing was changed on disk.'))}</b> "
            + _escape(_("Turn off Simulation to apply for real."))
        )
        aviso.set_halign(Gtk.Align.START)
        aviso.set_hexpand(True)
        aviso.set_wrap(True)
        footer.append(aviso)

        fechar = Gtk.Button(label=_("Close"))
        fechar.connect("clicked", lambda *_a: self.close())
        footer.append(fechar)

        toolbar.add_bottom_bar(footer)
        self.set_content(toolbar)

        self._render()

    # ------------------------------------------------------------------
    # Cabeçalho com a contagem por tipo
    # ------------------------------------------------------------------

    def _counts(self) -> dict:
        counts = {}
        for op in self.operations:
            counts[op.operation_type] = counts.get(op.operation_type, 0) + 1
        return counts

    def _build_summary(self) -> Gtk.Widget:
        counts = self._counts()

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)

        total = Gtk.Label()
        total.set_markup(
            f"<span size='large' weight='bold'>{len(self.operations)}</span> "
            + _escape(_("operations"))
        )
        total.set_halign(Gtk.Align.START)
        box.append(total)

        espacador = Gtk.Box()
        espacador.set_hexpand(True)
        box.append(espacador)

        for tipo, (emoji, rotulo, css) in OPERATION_STYLES.items():
            quantidade = counts.get(tipo, 0)
            if not quantidade:
                continue
            chip = Gtk.Label(label=f"{emoji} {rotulo}: {quantidade}")
            chip.add_css_class("sim-chip")
            chip.add_css_class(css)
            box.append(chip)

        return box

    def _build_filter_bar(self) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.set_margin_start(12)
        bar.set_margin_end(12)
        bar.set_margin_bottom(6)

        counts = self._counts()
        opcoes = [('all', _("All"), len(self.operations))]
        for tipo, (_emoji, rotulo, _css) in OPERATION_STYLES.items():
            if counts.get(tipo):
                opcoes.append((tipo, rotulo, counts[tipo]))

        primeiro = None
        for tipo, rotulo, quantidade in opcoes:
            botao = Gtk.ToggleButton(label=f"{rotulo} ({quantidade})")
            botao.add_css_class("flat")
            if primeiro is None:
                primeiro = botao
                botao.set_active(True)
            else:
                botao.set_group(primeiro)
            botao.connect("toggled", self._on_filter_toggled, tipo)
            bar.append(botao)

        return bar

    def _on_filter_toggled(self, button, tipo):
        if button.get_active():
            self._filter = tipo
            self._render()

    # ------------------------------------------------------------------
    # Lista de operações
    # ------------------------------------------------------------------

    def _relative(self, path) -> str:
        """Caminho relativo à pasta de trabalho, quando possível."""
        if not self.work_dir:
            return str(path)
        try:
            from pathlib import Path
            return str(Path(path).relative_to(self.work_dir))
        except (ValueError, TypeError):
            return str(path)

    def _render(self):
        child = self._list_box.get_first_child()
        while child:
            proximo = child.get_next_sibling()
            self._list_box.remove(child)
            child = proximo

        visiveis = [
            op for op in self.operations
            if self._filter == 'all' or op.operation_type == self._filter
        ]

        if not visiveis:
            self._list_box.append(Adw.StatusPage(
                icon_name="emblem-ok-symbolic",
                title=_("Nothing in this category"),
            ))
            return

        for indice, op in enumerate(visiveis, 1):
            self._list_box.append(self._build_row(indice, op))

    def _build_row(self, indice: int, op) -> Gtk.Widget:
        emoji, rotulo, css = OPERATION_STYLES.get(
            op.operation_type, ('•', op.operation_type.upper(), 'sim-rename')
        )
        excluir = op.operation_type == 'delete'

        linha = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        linha.add_css_class("sim-row")
        linha.add_css_class(css)

        numero = Gtk.Label(label=f"{indice}")
        numero.add_css_class("dim-label")
        numero.set_width_chars(4)
        numero.set_xalign(1.0)
        numero.set_valign(Gtk.Align.START)
        linha.append(numero)

        etiqueta = Gtk.Label(label=f"{emoji} {rotulo}")
        etiqueta.add_css_class("sim-tag")
        etiqueta.add_css_class(css)
        etiqueta.set_valign(Gtk.Align.START)
        etiqueta.set_width_chars(16)
        linha.append(etiqueta)

        textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        textos.set_hexpand(True)

        # O que SAI
        origem = Gtk.Label()
        origem.set_markup(f"<tt>{_escape(self._relative(op.source))}</tt>")
        origem.set_halign(Gtk.Align.START)
        origem.set_wrap(True)
        origem.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        origem.set_selectable(True)
        origem.add_css_class("sim-source-deleted" if excluir else "sim-source")
        textos.append(origem)

        if excluir:
            # Exclusão não tem destino: o que importa é o alerta
            aviso = Gtk.Label(label="⚠ " + _("This file will be permanently deleted"))
            aviso.set_halign(Gtk.Align.START)
            aviso.add_css_class("sim-delete-warning")
            textos.append(aviso)
        else:
            # O que ENTRA
            destino = Gtk.Label()
            destino.set_markup(f"<tt>→ {_escape(self._relative(op.destination))}</tt>")
            destino.set_halign(Gtk.Align.START)
            destino.set_wrap(True)
            destino.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            destino.set_selectable(True)
            destino.add_css_class("sim-destination")
            textos.append(destino)

        motivo = getattr(op, 'reason', '')
        if motivo:
            rotulo_motivo = Gtk.Label(label=motivo)
            rotulo_motivo.set_halign(Gtk.Align.START)
            rotulo_motivo.set_wrap(True)
            rotulo_motivo.add_css_class("dim-label")
            rotulo_motivo.add_css_class("caption")
            textos.append(rotulo_motivo)

        linha.append(textos)
        return linha
