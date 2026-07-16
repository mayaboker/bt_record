from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import yaml

from bt_record.constants import (
    DEFAULT_CAMERA_DEVICE,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_HTTP_PORT,
    DEFAULT_RECORD_FORMAT,
    DEFAULT_STREAM_IP,
    DEFAULT_STREAM_IP_PORT,
    DEFAULT_TARGET_FOLDER,
    DEFAULT_WIDTH,
    VALID_RECORD_FORMATS,
)
from bt_record.errors import RecordExitCode, RecordStartupError


@dataclass
class RecorderConfig:
    stream_ip: str = DEFAULT_STREAM_IP
    stream_ip_port: int = DEFAULT_STREAM_IP_PORT
    device: str = DEFAULT_CAMERA_DEVICE
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: int = DEFAULT_FPS
    record_format: str = DEFAULT_RECORD_FORMAT
    http_server_port: int = DEFAULT_HTTP_PORT
    target_folder: str = DEFAULT_TARGET_FOLDER

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CONFIG_FIELD_NAMES = {field.name for field in fields(RecorderConfig)}


def load_config_yaml(path: str | Path) -> dict[str, Any]:
    yaml_path = Path(path)
    if not yaml_path.exists():
        raise RecordStartupError(f"Config file not found: {yaml_path}")

    try:
        with yaml_path.open("r", encoding="utf-8") as config_file:
            config_data = yaml.safe_load(config_file) or {}
    except Exception as exc:
        raise RecordStartupError(
            f"Failed to load config from {yaml_path}: {exc}"
        ) from exc

    if not isinstance(config_data, dict):
        raise RecordStartupError(
            f"Failed to load config from {yaml_path}: expected YAML mapping"
        )
    return config_data


def merge_config_values(config: RecorderConfig, values: dict[str, Any]) -> None:
    for key, value in values.items():
        if key in CONFIG_FIELD_NAMES:
            setattr(config, key, value)


def validate_config(config: RecorderConfig, *, require_device: bool) -> None:
    try:
        ip_address(config.stream_ip)
    except ValueError as exc:
        raise RecordStartupError(f"Invalid stream IP: {config.stream_ip!r}") from exc

    config.stream_ip_port = _validate_port(config.stream_ip_port, "stream_ip_port")
    config.http_server_port = _validate_port(
        config.http_server_port,
        "http_server_port",
    )
    config.width = _validate_positive_int(config.width, "width")
    config.height = _validate_positive_int(config.height, "height")
    config.fps = _validate_positive_int(config.fps, "fps")

    if config.record_format not in VALID_RECORD_FORMATS:
        raise RecordStartupError(
            f"Invalid record format: {config.record_format!r}",
            exit_code=RecordExitCode.CLI_USAGE_ERROR,
        )

    target_folder = Path(config.target_folder)
    try:
        target_folder.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise RecordStartupError(
            f"Target folder is not writable: {target_folder}"
        ) from exc

    if require_device:
        device_path = Path(config.device)
        if not device_path.exists():
            raise RecordStartupError(
                f"Camera device not found: {device_path}",
                exit_code=RecordExitCode.DEVICE_NOT_FOUND,
            )


def _validate_port(value: Any, name: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise RecordStartupError(f"Invalid {name}: {value!r}") from exc
    if port < 1 or port > 65535:
        raise RecordStartupError(f"Invalid {name}: {value!r}")
    return port


def _validate_positive_int(value: Any, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise RecordStartupError(f"Invalid {name}: {value!r}") from exc
    if number <= 0:
        raise RecordStartupError(f"Invalid {name}: {value!r}")
    return number
