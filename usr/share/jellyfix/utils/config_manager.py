"""Gerenciador de configuração persistente em JSON"""

import json
import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Any

from .logger import get_logger


class ConfigManager:
    """Gerencia configurações persistentes em arquivo JSON"""

    def __init__(self):
        self.config_dir = Path.home() / '.jellyfix'
        self.config_file = self.config_dir / 'config.json'
        self._ensure_config_dir()

    def _ensure_config_dir(self):
        """Garante que o diretório de configuração existe"""
        self.config_dir.mkdir(exist_ok=True)

    def load(self) -> Dict[str, Any]:
        """
        Carrega configurações do arquivo JSON.

        Returns:
            Dicionário com configurações ou dict vazio se arquivo não existir
        """
        if not self.config_file.exists():
            return {}

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            get_logger().warning(f"Config file corrupted ({self.config_file}): {e} — using defaults")
            return {}
        except OSError as e:
            get_logger().warning(f"Config file unreadable ({self.config_file}): {e} — using defaults")
            return {}

    def save(self, config: Dict[str, Any]):
        """
        Salva configurações no arquivo JSON.

        Args:
            config: Dicionário com configurações
        """
        tmp_file = self.config_file.with_suffix('.tmp')
        try:
            # Backup existing config before overwriting
            if self.config_file.exists():
                shutil.copy2(self.config_file, self.config_file.with_suffix('.bak'))
            # Write to temp file first, then atomically replace
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            os.replace(tmp_file, self.config_file)
        except OSError as e:
            tmp_file.unlink(missing_ok=True)
            raise OSError(f"Failed to save config: {e}") from e

    def get(self, key: str, default: Any = None) -> Any:
        """
        Obtém valor de configuração.

        Args:
            key: Chave da configuração
            default: Valor padrão se não existir

        Returns:
            Valor da configuração ou default
        """
        config = self.load()
        return config.get(key, default)

    def set(self, key: str, value: Any):
        """
        Define valor de configuração.

        Args:
            key: Chave da configuração
            value: Valor a definir
        """
        config = self.load()
        config[key] = value
        self.save(config)

    def remove(self, key: str):
        """
        Remove uma chave de configuração.

        Args:
            key: Chave da configuração a remover
        """
        config = self.load()
        if key in config:
            del config[key]
            self.save(config)

    def get_tmdb_api_key(self) -> Optional[str]:
        """Obtém chave da API TMDB"""
        return self.get('tmdb_api_key')

    def set_tmdb_api_key(self, key: str):
        """Define chave da API TMDB"""
        self.set('tmdb_api_key', key)

    def remove_tmdb_api_key(self):
        """Remove chave da API TMDB"""
        self.remove('tmdb_api_key')

    def get_tvdb_api_key(self) -> Optional[str]:
        """Obtém chave da API TVDB"""
        return self.get('tvdb_api_key')

    def set_tvdb_api_key(self, key: str):
        """Define chave da API TVDB"""
        self.set('tvdb_api_key', key)

    def remove_tvdb_api_key(self):
        """Remove chave da API TVDB"""
        self.remove('tvdb_api_key')

    def get_opensubtitles_credentials(self) -> tuple:
        """Return the first configured opensubtitles.com account."""
        accounts = self.get_opensubtitles_accounts()
        if accounts:
            return accounts[0]['username'], accounts[0]['password']
        return '', ''

    def get_opensubtitles_accounts(self) -> list:
        """Return normalized accounts, migrating the legacy single login."""
        config = self.load()
        accounts = []
        seen = set()
        for account in config.get('opensubtitles_accounts') or []:
            if not isinstance(account, dict):
                continue
            username = str(account.get('username') or '').strip()
            password = str(account.get('password') or '')
            if not (username and password) or username.casefold() in seen:
                continue
            normalized = {'username': username, 'password': password}
            apikey = str(account.get('apikey') or '').strip()
            if apikey:
                normalized['apikey'] = apikey
            accounts.append(normalized)
            seen.add(username.casefold())

        legacy_user = str(config.get('opensubtitles_username') or '').strip()
        legacy_password = str(config.get('opensubtitles_password') or '')
        if legacy_user and legacy_password and legacy_user.casefold() not in seen:
            accounts.insert(0, {
                'username': legacy_user,
                'password': legacy_password,
            })
        return accounts

    def set_opensubtitles_credentials(self, username: str, password: str):
        """Add or update an opensubtitles.com account."""
        username = username.strip()
        config = self.load()
        accounts = self.get_opensubtitles_accounts()
        replacement = {'username': username, 'password': password}
        for index, account in enumerate(accounts):
            if account['username'].casefold() == username.casefold():
                accounts[index] = replacement
                break
        else:
            accounts.append(replacement)

        config['opensubtitles_accounts'] = accounts
        # Keep legacy keys for older Jellyfix versions and external tooling.
        config['opensubtitles_username'] = accounts[0]['username']
        config['opensubtitles_password'] = accounts[0]['password']
        self.save(config)

    def remove_opensubtitles_credentials(self):
        """Delete all stored opensubtitles.com accounts."""
        config = self.load()
        config.pop('opensubtitles_accounts', None)
        config.pop('opensubtitles_username', None)
        config.pop('opensubtitles_password', None)
        self.save(config)

    def get_min_pt_words(self) -> int:
        """Obtém número mínimo de palavras portuguesas"""
        return self.get('min_pt_words', 5)

    def set_min_pt_words(self, value: int):
        """Define número mínimo de palavras portuguesas"""
        self.set('min_pt_words', value)

    def export_config(self) -> str:
        """
        Exporta configuração atual como JSON formatado.

        Returns:
            String JSON formatada
        """
        config = self.load()
        return json.dumps(config, indent=4, ensure_ascii=False)

    def import_config(self, json_str: str):
        """
        Importa configuração de string JSON.

        Args:
            json_str: String JSON com configurações
        """
        try:
            config = json.loads(json_str)
            self.save(config)
        except json.JSONDecodeError as e:
            raise Exception(f"JSON inválido: {e}")

    def reset(self):
        """Remove arquivo de configuração (reset para padrões)"""
        if self.config_file.exists():
            self.config_file.unlink()

    def get_config_path(self) -> str:
        """Return config file path"""
        return str(self.config_file)

    def get_recent_libraries(self, max_count: int = 5) -> list:
        """
        Get list of recently scanned libraries.

        Args:
            max_count: Maximum number of libraries to return

        Returns:
            List of dicts with 'path' and 'timestamp' keys
        """
        libraries = self.get('recent_libraries', [])
        return libraries[:max_count]

    def add_recent_library(self, path: str):
        """
        Add a library to recent libraries list.

        Args:
            path: Path to the library directory
        """
        from datetime import datetime

        libraries = self.get('recent_libraries', [])

        # Remove if already exists
        libraries = [lib for lib in libraries if lib.get('path') != path]

        # Add to beginning
        libraries.insert(0, {
            'path': path,
            'timestamp': datetime.now().isoformat()
        })

        # Keep only last 10
        libraries = libraries[:10]

        self.set('recent_libraries', libraries)

    def clear_recent_libraries(self):
        """Clear all recent libraries"""
        self.set('recent_libraries', [])

    def get_keep_recent_libraries(self) -> bool:
        """Get whether to keep recent libraries across sessions (default: False)."""
        config = self.load()
        if 'keep_recent_libraries' in config:
            return bool(config['keep_recent_libraries'])
        # Migration from legacy inverse key
        if 'clear_recent_on_start' in config:
            return not bool(config['clear_recent_on_start'])
        return False

    def set_keep_recent_libraries(self, value: bool):
        """Set whether to keep recent libraries across sessions."""
        config = self.load()
        config['keep_recent_libraries'] = bool(value)
        # Drop legacy inverse key if present
        config.pop('clear_recent_on_start', None)
        self.save(config)

    def get_last_directory(self) -> Optional[str]:
        """Get last opened directory for file chooser"""
        return self.get('last_directory')

    def set_last_directory(self, path: str):
        """Set last opened directory for file chooser"""
        self.set('last_directory', path)

