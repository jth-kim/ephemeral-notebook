from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "popup-notebook"


@dataclass(frozen=True)
class PopupConfig:
    width: str = "92%"
    height: str = "92%"
    x: str = "C"
    y: str = "C"


@dataclass(frozen=True)
class UIConfig:
    show_footer: bool = True
    status_verbosity: str = "minimal"
    markdown_center: bool = False
    output_max_lines: int = 12
    code_theme: str = "monokai"


@dataclass(frozen=True)
class AppConfig:
    popup: PopupConfig
    ui: UIConfig


DEFAULT_CONFIG = AppConfig(
    popup=PopupConfig(),
    ui=UIConfig(),
)


def config_dir() -> Path:
    """Return the app-managed config directory."""
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def config_path() -> Path:
    """Return the global config path."""
    return config_dir() / "config.toml"


def load_app_config() -> AppConfig:
    """Load global app config from TOML, falling back to opinionated defaults."""
    path = config_path()
    if not path.exists():
        return DEFAULT_CONFIG

    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return DEFAULT_CONFIG

    popup = payload.get("popup", {})
    ui = payload.get("ui", {})
    if not isinstance(popup, dict):
        popup = {}
    if not isinstance(ui, dict):
        ui = {}

    popup_config = PopupConfig(
        width=_string_value(popup.get("width"), DEFAULT_CONFIG.popup.width),
        height=_string_value(popup.get("height"), DEFAULT_CONFIG.popup.height),
        x=_string_value(popup.get("x"), DEFAULT_CONFIG.popup.x),
        y=_string_value(popup.get("y"), DEFAULT_CONFIG.popup.y),
    )

    status_verbosity = _string_value(ui.get("status_verbosity"), DEFAULT_CONFIG.ui.status_verbosity)
    if status_verbosity not in {"minimal", "full"}:
        status_verbosity = DEFAULT_CONFIG.ui.status_verbosity

    ui_config = UIConfig(
        show_footer=_bool_value(ui.get("show_footer"), DEFAULT_CONFIG.ui.show_footer),
        status_verbosity=status_verbosity,
        markdown_center=_bool_value(
            ui.get("markdown_center"),
            DEFAULT_CONFIG.ui.markdown_center,
        ),
        output_max_lines=_int_value(
            ui.get("output_max_lines"),
            DEFAULT_CONFIG.ui.output_max_lines,
            minimum=3,
        ),
        code_theme=_string_value(ui.get("code_theme"), DEFAULT_CONFIG.ui.code_theme),
    )

    return AppConfig(popup=popup_config, ui=ui_config)


def state_dir() -> Path:
    """Return the app-managed state directory outside the project tree."""
    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        path = Path(xdg_state_home) / APP_NAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    primary = Path.home() / ".local" / "state" / APP_NAME
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except OSError:
        fallback = Path("/tmp") / APP_NAME
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _string_value(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _bool_value(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _int_value(value: object, default: int, *, minimum: int) -> int:
    if isinstance(value, int) and value >= minimum:
        return value
    return default
