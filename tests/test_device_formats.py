import subprocess

import pytest

import bt_record.device_formats as device_formats
import bt_record.main as main_module
from bt_record.config import RecorderConfig
from bt_record.errors import RecordStartupError
from bt_record.main import main


def test_dump_device_formats_runs_v4l2_ctl(monkeypatch):
    calls = []

    def fake_run(command, capture_output, text, check):
        calls.append(
            {
                "command": command,
                "capture_output": capture_output,
                "text": text,
                "check": check,
            }
        )
        return subprocess.CompletedProcess(command, 0, stdout="formats\n", stderr="")

    monkeypatch.setattr(device_formats.shutil, "which", lambda name: "/usr/bin/v4l2-ctl")
    monkeypatch.setattr(device_formats.subprocess, "run", fake_run)

    output = device_formats.dump_device_formats(RecorderConfig(device="/dev/video2"))

    assert output == "formats\n"
    assert calls == [
        {
            "command": ["v4l2-ctl", "-d", "/dev/video2", "--list-formats-ext"],
            "capture_output": True,
            "text": True,
            "check": False,
        }
    ]


def test_dump_device_formats_missing_v4l2_ctl(monkeypatch):
    monkeypatch.setattr(device_formats.shutil, "which", lambda name: None)

    with pytest.raises(RecordStartupError, match="v4l2-ctl not found"):
        device_formats.dump_device_formats(RecorderConfig())


def test_dump_device_formats_failed_command(monkeypatch):
    def fake_run(command, capture_output, text, check):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="bad device")

    monkeypatch.setattr(device_formats.shutil, "which", lambda name: "/usr/bin/v4l2-ctl")
    monkeypatch.setattr(device_formats.subprocess, "run", fake_run)

    with pytest.raises(RecordStartupError, match="v4l2-ctl failed for /dev/video0"):
        device_formats.dump_device_formats(RecorderConfig())


def test_dump_device_formats_command_prints_output(monkeypatch, tmp_path, capsys):
    device = tmp_path / "video0"
    device.touch()

    def fake_dump_device_formats(config):
        assert config.device == str(device)
        return "device formats\n"

    monkeypatch.setattr(main_module, "dump_device_formats", fake_dump_device_formats)

    main(["dump_device_formats", "--device", str(device)], standalone_mode=False)

    assert capsys.readouterr().out == "device formats\n"


def test_dump_device_formats_missing_device_fails_before_subprocess(tmp_path):
    missing_device = tmp_path / "missing-video0"

    with pytest.raises(RuntimeError, match="Camera device not found"):
        main(["dump_device_formats", "--device", str(missing_device)], standalone_mode=False)
