"""Application configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AppConfig:
    """Runtime configuration for the wrapper."""

    executable: str = "fs-uae"
    fsuae_args: list[str] = field(default_factory=list)
    prefix: str = ":"
    auto_resume: bool = True
    verbose: bool = False
