"""Application configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

from .scenarios import ScenarioCatalog


@dataclass
class AppConfig:
    """Runtime configuration for the wrapper."""

    executable: str = "fs-uae"
    fsuae_args: list[str] = field(default_factory=list)
    prefix: str = ":"
    verbose: bool = False
    start_debug: bool = False
    scenarios: ScenarioCatalog = field(default_factory=ScenarioCatalog.empty)
    config_path: str | None = None
