from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml


@dataclass
class AppConfig:
    host: str
    port: int
    snapshot_path: str
    stream_fps: int
    jpeg_quality: int


@dataclass
class LoggingConfig:
    level: str
    file: str


@dataclass
class CameraConfig:
    source: Any
    width: int
    height: int
    fps: int
    warmup_seconds: int


@dataclass
class SiteConfig:
    device_id: str
    door_name: str
    site_name: str
    timezone: str


@dataclass
class CountingConfig:
    mode: str
    line_position: float
    min_confidence: float
    min_box_area_ratio: float
    min_stable_hits: int
    max_missing_frames: int
    min_crossing_delta_ratio: float
    class_name: str
    direction_names: dict[str, str]


@dataclass
class BackendConfig:
    provider: str
    use_hailo_unique_id: bool


@dataclass
class ServerConfig:
    enabled: bool
    base_url: str
    ingest_path: str
    health_path: str
    api_token: str
    sync_interval_seconds: int
    heartbeat_interval_seconds: int
    timeout_seconds: int
    verify_ssl: bool


@dataclass
class SecurityConfig:
    admin_token: str


@dataclass
class StorageConfig:
    db_path: str
    keep_events_days: int


@dataclass
class DeviceConfig:
    app: AppConfig
    logging: LoggingConfig
    camera: CameraConfig
    site: SiteConfig
    counting: CountingConfig
    backend: BackendConfig
    server: ServerConfig
    security: SecurityConfig
    storage: StorageConfig
    root_dir: Path


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Configuration introuvable: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_config(path_str: str) -> DeviceConfig:
    path = Path(path_str).resolve()
    raw = _load_yaml(path)
    root_dir = path.parent
    return DeviceConfig(
        app=AppConfig(**raw["app"]),
        logging=LoggingConfig(**raw["logging"]),
        camera=CameraConfig(**raw["camera"]),
        site=SiteConfig(**raw["site"]),
        counting=CountingConfig(**raw["counting"]),
        backend=BackendConfig(**raw["backend"]),
        server=ServerConfig(**raw["server"]),
        security=SecurityConfig(**raw["security"]),
        storage=StorageConfig(**raw["storage"]),
        root_dir=root_dir,
    )
