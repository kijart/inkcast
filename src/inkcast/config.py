"""TOML configuration: which URL each display shows and how."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROTATIONS = (0, 90, 180, 270)
FITS = ("contain", "cover", "stretch")


@dataclass(frozen=True)
class DeviceConfig:
    url: str
    name: str = ""
    rotate: int = 0
    sleep_minutes: int = 0
    fit: str = "contain"
    touch: bool = False
    refresh_seconds: int | None = None  # None: use the global refresh_seconds

    def __post_init__(self) -> None:
        if self.rotate not in ROTATIONS:
            raise ValueError(f"rotate must be one of 0, 90, 180, 270, got {self.rotate}")
        if self.fit not in FITS:
            raise ValueError(f"fit must be one of contain, cover, stretch, got {self.fit!r}")


@dataclass(frozen=True)
class Config:
    default_url: str
    host: str = "0.0.0.0"
    port: int = 11113
    refresh_seconds: int = 300
    settle_seconds: float = 2.0
    status_port: int | None = None
    devices: dict[str, DeviceConfig] = field(default_factory=dict)

    def device(self, uuid: str) -> DeviceConfig:
        """Settings for *uuid*, falling back to the default URL for unknown displays."""
        return self.devices.get(uuid.lower(), DeviceConfig(url=self.default_url))

    def refresh_seconds_for(self, uuid: str) -> int:
        """How often *uuid* is re-rendered while connected: its own setting or the global one."""
        own = self.device(uuid).refresh_seconds
        return self.refresh_seconds if own is None else own


def load_config(path: Path) -> Config:
    raw = tomllib.loads(path.read_text())
    default_url = raw.pop("default_url")
    devices = {
        uuid.lower(): DeviceConfig(**{"url": default_url, **settings})
        for uuid, settings in raw.pop("devices", {}).items()
    }
    return Config(default_url=default_url, devices=devices, **raw)
