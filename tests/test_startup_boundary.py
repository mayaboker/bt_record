import builtins
import importlib
import sys
import threading

import pytest

from bt_record.errors import RecordExitCode, RecordStartupError
from bt_record.main import main


def test_missing_camera_device_exits_three_in_standalone_mode(tmp_path):
    missing_device = tmp_path / "missing-video0"

    with pytest.raises(SystemExit) as exc_info:
        main(["run", "--device", str(missing_device)], standalone_mode=True)

    assert exc_info.value.code == RecordExitCode.DEVICE_NOT_FOUND


def test_missing_camera_device_raises_runtime_error_non_standalone(tmp_path):
    missing_device = tmp_path / "missing-video0"

    with pytest.raises(RuntimeError) as exc_info:
        main(["run", "--device", str(missing_device)], standalone_mode=False)

    assert str(exc_info.value) == f"Camera device not found: {missing_device}"


def test_bad_stream_ip_is_rejected_before_startup():
    with pytest.raises(RuntimeError, match="Invalid stream IP"):
        main(["run", "--stream-ip", "not-an-ip"], standalone_mode=False)


def test_bad_record_format_is_rejected_before_startup():
    with pytest.raises(RuntimeError, match="invalid choice"):
        main(["run", "--record-format", "avi"], standalone_mode=False)


def test_missing_gstreamer_dependency_uses_startup_error(monkeypatch, tmp_path):
    device = tmp_path / "video0"
    device.touch()

    sys.modules.pop("bt_record.record_controller", None)
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "gi":
            raise ImportError("missing gi")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError) as exc_info:
        main(["run", "--device", str(device)], standalone_mode=False)

    assert str(exc_info.value) == "Missing PyGObject/GStreamer Python dependencies"

    with pytest.raises(RecordStartupError) as startup_exc:
        importlib.import_module("bt_record.record_controller")

    assert startup_exc.value.exit_code == RecordExitCode.GSTREAMER_DEPENDENCY_MISSING


def test_import_record_app_does_not_import_record_controller():
    sys.modules.pop("bt_record.record_app", None)
    sys.modules.pop("bt_record.record_controller", None)

    importlib.import_module("bt_record.record_app")

    assert "bt_record.record_controller" not in sys.modules


def test_import_record_app_does_not_start_threads():
    sys.modules.pop("bt_record.record_app", None)
    before = {thread.ident for thread in threading.enumerate()}

    importlib.import_module("bt_record.record_app")

    after = {thread.ident for thread in threading.enumerate()}
    assert after == before


def test_create_app_accepts_fake_recorder_without_camera_hardware():
    from bt_record.record_app import create_app

    class FakeRecorder:
        target_folder = None

        def start(self):
            return None

        def stop(self):
            return None

        def submit(self, name, args=None):
            raise AssertionError("submit should not be called while creating app")

    app = create_app(FakeRecorder())

    assert app is not None
