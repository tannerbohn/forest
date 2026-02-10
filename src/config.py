"""Configuration management for Forest."""

import json
import logging
import os

DEFAULT_CONFIG = {
    "sound_effects_enabled": True,
    "default_theme": "forest",
    "log_level": "INFO",
    "undo_depth": 50,
    "auto_save": True,
    "auto_save_interval": 5,
}


class Config:
    """Manages application configuration from config.json."""

    def __init__(self, config_path=None):
        if config_path is None:
            # Default to config.json in project root
            config_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "config.json")
            )

        self.config_path = config_path
        self.data = self._load_config()

    def _load_config(self):
        """Load config from file, falling back to defaults."""
        if not os.path.exists(self.config_path):
            logging.info(f"No config file found at {self.config_path}, using defaults")
            return DEFAULT_CONFIG.copy()

        try:
            with open(self.config_path, "r") as f:
                user_config = json.load(f)

            # Merge with defaults (user config overrides defaults)
            config = DEFAULT_CONFIG.copy()
            config.update(user_config)

            logging.info(f"Loaded config from {self.config_path}")
            return config
        except Exception as e:
            logging.warning(f"Error loading config: {e}, using defaults")
            return DEFAULT_CONFIG.copy()

    def get(self, key, default=None):
        """Get a config value."""
        return self.data.get(key, default)

    def save(self):
        """Save current config to file."""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w") as f:
                json.dump(self.data, f, indent=4)
            logging.info(f"Saved config to {self.config_path}")
        except Exception as e:
            logging.error(f"Error saving config: {e}")

    @property
    def sound_effects_enabled(self):
        return self.get("sound_effects_enabled", True)

    @property
    def default_theme(self):
        return self.get("default_theme", "forest")

    @property
    def log_level(self):
        return self.get("log_level", "INFO")

    @property
    def location(self):
        return self.get("location", None)

    @property
    def undo_depth(self):
        return self.get("undo_depth", 50)

    @property
    def auto_save(self):
        return self.get("auto_save", True)

    @property
    def auto_save_interval(self):
        return self.get("auto_save_interval", 5)
