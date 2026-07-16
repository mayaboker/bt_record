from __future__ import annotations

import shutil
import subprocess

from bt_record.config import RecorderConfig
from bt_record.errors import RecordStartupError


def dump_device_formats(config: RecorderConfig) -> str:
    if shutil.which("v4l2-ctl") is None:
        raise RecordStartupError("v4l2-ctl not found. Install v4l-utils.")

    result = subprocess.run(
        ["v4l2-ctl", "-d", config.device, "--list-formats-ext"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        suffix = f": {details}" if details else ""
        raise RecordStartupError(f"v4l2-ctl failed for {config.device}{suffix}")
    return result.stdout
