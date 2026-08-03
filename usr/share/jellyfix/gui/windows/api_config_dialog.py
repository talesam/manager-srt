#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui/windows/api_config_dialog.py - API Configuration dialog
#

"""
API Configuration dialog for TMDB key management.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw

from ...utils.logger import get_logger
from ...utils.i18n import _
from ...utils.config_manager import ConfigManager


class APIConfigDialog(Adw.Window):
    """API Configuration dialog"""

    def __init__(self, parent):
        """
        Initialize API configuration dialog.

        Args:
            parent: Parent window
        """
        super().__init__(transient_for=parent, modal=True)

        self.logger = get_logger()
        self.config_manager = ConfigManager()

        # Window properties
        self.set_title(_("API Configuration"))
        self.set_default_size(660, 680)

        # Build UI
        self._build_ui()

    def _build_ui(self):
        """Build dialog UI"""
        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header bar
        header = Adw.HeaderBar()
        main_box.append(header)

        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # Preferences page
        self.prefs_page = Adw.PreferencesPage()

        # TMDB Configuration group
        tmdb_group = Adw.PreferencesGroup(
            title=_("TMDB Configuration"),
            description=_("Configure The Movie Database API key")
        )

        # Current status row
        tmdb_key = self.config_manager.get_tmdb_api_key()
        status_text = _("✓ Configured") if tmdb_key else _("✗ Not configured")
        self.status_row = Adw.ActionRow(
            title=_("TMDB API Key"),
            subtitle=status_text
        )
        tmdb_group.add(self.status_row)

        # Config file path row
        config_path = str(self.config_manager.get_config_path())
        config_row = Adw.ActionRow(
            title=_("Config file"),
            subtitle=config_path
        )
        tmdb_group.add(config_row)

        self.prefs_page.add(tmdb_group)

        # OpenSubtitles Configuration group
        os_group = Adw.PreferencesGroup(
            title=_("OpenSubtitles Login"),
            description=_("A free opensubtitles.com account is required to "
                         "download subtitles (searching works without it)")
        )

        os_accounts = self.config_manager.get_opensubtitles_accounts()
        os_status = self._opensubtitles_status(os_accounts)
        self.os_status_row = Adw.ActionRow(
            title=_("Accounts"),
            subtitle=os_status
        )
        os_group.add(self.os_status_row)

        # Configure login button
        os_configure_row = Adw.ActionRow(
            title=_("Add OpenSubtitles Account"),
            subtitle=_("Accounts rotate automatically when a daily limit is reached")
        )
        os_configure_button = Gtk.Button(label=_("Configure"), valign=Gtk.Align.CENTER)
        os_configure_button.add_css_class("suggested-action")
        os_configure_button.connect("clicked", self._on_configure_opensubtitles)
        os_configure_row.add_suffix(os_configure_button)
        os_group.add(os_configure_row)

        # Test login button
        os_test_row = Adw.ActionRow(
            title=_("Test OpenSubtitles Accounts"),
            subtitle=_("Verify all configured credentials")
        )
        os_test_button = Gtk.Button(label=_("Test"), valign=Gtk.Align.CENTER)
        os_test_button.connect("clicked", self._on_test_opensubtitles)
        os_test_row.add_suffix(os_test_button)
        os_group.add(os_test_row)

        # Remove login button
        os_remove_row = Adw.ActionRow(
            title=_("Remove OpenSubtitles Accounts"),
            subtitle=_("Delete all stored credentials")
        )
        os_remove_button = Gtk.Button(label=_("Remove"), valign=Gtk.Align.CENTER)
        os_remove_button.add_css_class("destructive-action")
        os_remove_button.connect("clicked", self._on_remove_opensubtitles)
        os_remove_row.add_suffix(os_remove_button)
        os_group.add(os_remove_row)

        # Create account help
        os_help_row = Adw.ActionRow(
            title=_("Create a free account"),
            subtitle="https://www.opensubtitles.com/newuser"
        )
        os_help_button = Gtk.Button(label=_("Open"), valign=Gtk.Align.CENTER)
        os_help_button.connect("clicked", self._on_opensubtitles_signup)
        os_help_row.add_suffix(os_help_button)
        os_group.add(os_help_row)

        self.prefs_page.add(os_group)

        # Actions group
        actions_group = Adw.PreferencesGroup(
            title=_("Actions")
        )

        # Configure key button
        configure_row = Adw.ActionRow(
            title=_("Configure TMDB API Key"),
            subtitle=_("Enter your TMDB API key")
        )
        configure_button = Gtk.Button(
            label=_("Configure"),
            valign=Gtk.Align.CENTER
        )
        configure_button.add_css_class("suggested-action")
        configure_button.connect("clicked", self._on_configure_clicked)
        configure_row.add_suffix(configure_button)
        actions_group.add(configure_row)

        # View key button
        view_row = Adw.ActionRow(
            title=_("View Current Key"),
            subtitle=_("Show masked API key")
        )
        view_button = Gtk.Button(
            label=_("View"),
            valign=Gtk.Align.CENTER
        )
        view_button.connect("clicked", self._on_view_clicked)
        view_row.add_suffix(view_button)
        actions_group.add(view_row)

        # Test connection button
        test_row = Adw.ActionRow(
            title=_("Test TMDB Connection"),
            subtitle=_("Verify API key is working")
        )
        test_button = Gtk.Button(
            label=_("Test"),
            valign=Gtk.Align.CENTER
        )
        test_button.connect("clicked", self._on_test_clicked)
        test_row.add_suffix(test_button)
        actions_group.add(test_row)

        # Remove key button
        remove_row = Adw.ActionRow(
            title=_("Remove TMDB Key"),
            subtitle=_("Delete stored API key")
        )
        remove_button = Gtk.Button(
            label=_("Remove"),
            valign=Gtk.Align.CENTER
        )
        remove_button.add_css_class("destructive-action")
        remove_button.connect("clicked", self._on_remove_clicked)
        remove_row.add_suffix(remove_button)
        actions_group.add(remove_row)

        self.prefs_page.add(actions_group)

        # Help group
        help_group = Adw.PreferencesGroup(
            title=_("Help")
        )

        # How to get key button
        help_row = Adw.ActionRow(
            title=_("How to Get TMDB API Key"),
            subtitle=_("Step-by-step tutorial")
        )
        help_button = Gtk.Button(
            label=_("Tutorial"),
            valign=Gtk.Align.CENTER
        )
        help_button.connect("clicked", self._on_help_clicked)
        help_row.add_suffix(help_button)
        help_group.add(help_row)

        self.prefs_page.add(help_group)

        # Add to scrolled window
        scrolled.set_child(self.prefs_page)
        main_box.append(scrolled)

        # Wrap in a ToastOverlay so feedback shows INSIDE this modal dialog,
        # not behind it on the main window (where the user can't see it).
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(main_box)

        # Set content
        self.set_content(self.toast_overlay)

    def _toast(self, message: str):
        """Show a toast inside this dialog."""
        self.toast_overlay.add_toast(Adw.Toast(title=message))

    @staticmethod
    def _opensubtitles_status(accounts):
        """Build a compact account summary without exposing passwords."""
        if not accounts:
            return _("✗ Not configured")
        usernames = ", ".join(account['username'] for account in accounts)
        return _("✓ OpenSubtitles accounts: %(users)s") % {'users': usernames}

    def _on_configure_clicked(self, button):
        """Handle configure button click"""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("Configure TMDB API Key"),
            body=_("Enter your TMDB API key below")
        )

        # Add entry row
        entry = Gtk.Entry()
        entry.set_placeholder_text(_("Paste API key here"))
        entry.set_visibility(True)

        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("save", _("Save"))
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        def on_response(dialog, response):
            if response == "save":
                api_key = entry.get_text().strip()
                if api_key:
                    self.config_manager.set_tmdb_api_key(api_key)
                    self.logger.success("TMDB key saved")

                    # IMPORTANT: Update the config singleton in memory
                    from ...utils.config import get_config
                    config = get_config()
                    config.tmdb_api_key = api_key

                    # Update status
                    self.status_row.set_subtitle(_("✓ Configured"))

                    # Show toast
                    self._toast(_("API key saved successfully"))

        dialog.connect("response", on_response)
        dialog.present()

    def _on_configure_opensubtitles(self, button):
        """Handle OpenSubtitles login configuration"""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("Add OpenSubtitles Account"),
            body=_("Enter an opensubtitles.com username and password.\n"
                   "⚠ Use your USERNAME, not your e-mail address.")
        )

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        user_entry = Gtk.Entry()
        user_entry.set_placeholder_text(_("Username (not e-mail)"))
        box.append(user_entry)

        pass_entry = Gtk.Entry()
        pass_entry.set_placeholder_text(_("Password"))
        pass_entry.set_visibility(False)
        pass_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        box.append(pass_entry)

        # Toggle password visibility
        show_check = Gtk.CheckButton(label=_("Show password"))
        show_check.connect("toggled", lambda c: pass_entry.set_visibility(c.get_active()))
        box.append(show_check)

        dialog.set_extra_child(box)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("save", _("Save"))
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        def on_response(dialog, response):
            if response == "save":
                username = user_entry.get_text().strip()
                password = pass_entry.get_text()
                if username and password:
                    self.config_manager.set_opensubtitles_credentials(username, password)

                    # Update the in-memory config singleton
                    from ...utils.config import get_config
                    config = get_config()
                    accounts = self.config_manager.get_opensubtitles_accounts()
                    config.opensubtitles_accounts = accounts
                    config.opensubtitles_username = accounts[0]['username']
                    config.opensubtitles_password = accounts[0]['password']

                    self.os_status_row.set_subtitle(self._opensubtitles_status(accounts))
                    self._toast(_("OpenSubtitles account saved"))
                else:
                    self._toast(_("Username and password are both required"))

        dialog.connect("response", on_response)
        dialog.present()

    def _on_remove_opensubtitles(self, button):
        """Handle OpenSubtitles login removal"""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("Remove All OpenSubtitles Accounts?"),
            body=_("This will delete all stored credentials. You will not be "
                   "able to download from opensubtitles.com until you configure it again.")
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(dialog, response):
            if response == "remove":
                self.config_manager.remove_opensubtitles_credentials()

                from ...utils.config import get_config
                config = get_config()
                config.opensubtitles_accounts = []
                config.opensubtitles_username = ""
                config.opensubtitles_password = ""

                self.os_status_row.set_subtitle(_("✗ Not configured"))
                self._toast(_("OpenSubtitles accounts removed"))

        dialog.connect("response", on_response)
        dialog.present()

    def _on_opensubtitles_signup(self, button):
        """Open the opensubtitles.com signup page in the browser"""
        Gtk.show_uri(self, "https://www.opensubtitles.com/newuser", 0)

    def _on_test_opensubtitles(self, button):
        """Log in to every opensubtitles.com account to verify it."""
        accounts = self.config_manager.get_opensubtitles_accounts()
        if not accounts:
            self._toast(_("Add an account first"))
            return

        self._toast(_("Testing accounts…"))

        from ...core.subtitle_manager import SubtitleManager
        manager = SubtitleManager()
        failures = []
        for account in accounts:
            ok, message = manager.test_opensubtitles_login(
                account['username'], account['password']
            )
            if not ok:
                failures.append(f"{account['username']}: {message}")

        if not failures:
            self.os_status_row.set_subtitle(self._opensubtitles_status(accounts))
            self._toast(_("✓ All OpenSubtitles accounts are valid"))
        else:
            message = "; ".join(failures)
            self.logger.error(f"OpenSubtitles account test failed: {message}")
            self._toast("✗ " + (_("Account test failed: %s") % message))

    def _on_view_clicked(self, button):
        """Handle view button click"""
        key = self.config_manager.get_tmdb_api_key()

        if key:
            # Mask key
            masked_key = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "***"

            dialog = Adw.MessageDialog(
                transient_for=self,
                heading=_("Current TMDB API Key"),
                body=f"{_('Masked key')}: {masked_key}\n\n{_('Full key stored in')}: {self.config_manager.get_config_path()}"
            )
        else:
            dialog = Adw.MessageDialog(
                transient_for=self,
                heading=_("No API Key"),
                body=_("No TMDB API key configured yet")
            )

        dialog.add_response("ok", _("OK"))
        dialog.present()

    def _on_test_clicked(self, button):
        """Handle test button click"""
        from ...core.metadata import MetadataFetcher

        key = self.config_manager.get_tmdb_api_key()
        if not key:
            dialog = Adw.MessageDialog(
                transient_for=self,
                heading=_("No API Key"),
                body=_("Please configure TMDB API key first")
            )
            dialog.add_response("ok", _("OK"))
            dialog.present()
            return

        # Test connection
        try:
            fetcher = MetadataFetcher()
            result = fetcher.search_movie("The Matrix", 1999)

            if result:
                dialog = Adw.MessageDialog(
                    transient_for=self,
                    heading=_("✓ Connection Successful"),
                    # O placeholder fica FORA da string traduzível: o fluxo de
                    # tradução automática descartava o "{}" no msgstr e o
                    # msgfmt rejeitava o arquivo inteiro ("a format
                    # specification for argument '0' doesn't exist in
                    # 'msgstr'"), invalidando o .mo de 18 idiomas.
                    body=(
                        _("TMDB API key is working correctly!")
                        + "\n\n"
                        + _("Test search returned:")
                        + f" {result.title}"
                    ),
                )
            else:
                dialog = Adw.MessageDialog(
                    transient_for=self,
                    heading=_("⚠ Connection Failed"),
                    body=_("Could not fetch data from TMDB. Please check your API key.")
                )
        except Exception as e:
            dialog = Adw.MessageDialog(
                transient_for=self,
                heading=_("✗ Connection Error"),
                body=_("Error testing connection: {}").format(str(e))
            )

        dialog.add_response("ok", _("OK"))
        dialog.present()

    def _on_remove_clicked(self, button):
        """Handle remove button click"""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("Remove API Key?"),
            body=_("This will delete your stored TMDB API key. You will need to configure it again.")
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(dialog, response):
            if response == "remove":
                self.config_manager.remove_tmdb_api_key()

                # IMPORTANT: Update the config singleton in memory
                from ...utils.config import get_config
                config = get_config()
                config.tmdb_api_key = ""

                self.status_row.set_subtitle(_("✗ Not configured"))
                self.logger.info("TMDB key removed")

                # Show toast
                self._toast(_("API key removed"))

        dialog.connect("response", on_response)
        dialog.present()

    def _on_help_clicked(self, button):
        """Handle help button click"""
        help_text = _("""How to Get TMDB API Key:

1. Go to https://www.themoviedb.org/signup
2. Create a free account
3. Go to Settings → API
4. Request an API key (choose "Developer" option)
5. Fill in the required information
6. Copy the API Key (v3 auth)
7. Paste it in Jellyfix

The API key is free and allows you to:
• Fetch movie and TV show metadata
• Download posters and backdrops
• Get accurate titles and release dates
• Organize your library with TMDB IDs""")

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("How to Get TMDB API Key"),
            body=help_text
        )
        dialog.add_response("ok", _("OK"))
        dialog.present()
