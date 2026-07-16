import types

import pytest

from bt_record.config import RecorderConfig
from bt_record.errors import RecordStartupError
from bt_record.pipeline import build_live_pipeline, build_recording_branch


try:
    import bt_record.record_controller as record_controller
except RecordStartupError as exc:
    pytest.skip(str(exc), allow_module_level=True)


class FakeElement:
    def __init__(self):
        self.properties = {}

    def set_property(self, name, value):
        self.properties[name] = value

    def add_probe(self, *_args):
        return 1


class FakeBus:
    def add_signal_watch(self):
        return None

    def connect(self, *_args):
        return None


class FakePipeline:
    def __init__(self):
        self.elements = {
            "camera": FakeElement(),
            "tee": FakeElement(),
            "live-queue": FakeElement(),
            "live-convert": FakeElement(),
        }
        self.properties = {}

    def set_name(self, name):
        self.name = name

    def get_by_name(self, name):
        return self.elements.get(name)

    def set_property(self, name, value):
        self.properties[name] = value

    def get_bus(self):
        return FakeBus()


class FakeRecordBin:
    def __init__(self):
        self.sink_pad = FakeElement()
        self.record_sink = FakeElement()

    def set_name(self, name):
        self.name = name

    def set_property(self, name, value):
        self.message_forward = value

    def get_static_pad(self, name):
        if name == "sink":
            return self.sink_pad
        return None

    def get_by_name(self, name):
        if name == "record-sink":
            return self.record_sink
        return None


def test_camera_recorder_uses_live_pipeline_builder(monkeypatch, tmp_path):
    captured = {}
    config = RecorderConfig(
        device=str(tmp_path / "video0"),
        stream_ip="127.0.0.9",
        stream_ip_port=5609,
        width=800,
        height=600,
        fps=25,
    )

    def fake_parse_launch(pipeline_desc):
        captured["pipeline_desc"] = pipeline_desc
        return FakePipeline()

    fake_gst = types.SimpleNamespace(
        parse_launch=fake_parse_launch,
    )
    monkeypatch.setattr(record_controller, "Gst", fake_gst)
    monkeypatch.setattr(record_controller, "validate_camera_device", lambda _device: None)

    recorder = record_controller.CameraRecorder(context=object(), config=config)

    assert captured["pipeline_desc"] == build_live_pipeline(config)
    assert recorder.src.properties["device"] == config.device


def test_create_record_bin_uses_recording_branch_builder(monkeypatch, tmp_path):
    captured = {}
    config = RecorderConfig(
        device=str(tmp_path / "video0"),
        record_format="mp4",
        fps=24,
    )

    def fake_parse_bin_from_description(record_desc, ghost_unlinked_pads):
        captured["record_desc"] = record_desc
        captured["ghost_unlinked_pads"] = ghost_unlinked_pads
        return FakeRecordBin()

    fake_gst = types.SimpleNamespace(
        parse_launch=lambda _pipeline_desc: FakePipeline(),
        parse_bin_from_description=fake_parse_bin_from_description,
        PadProbeType=types.SimpleNamespace(BUFFER="buffer"),
    )
    monkeypatch.setattr(record_controller, "Gst", fake_gst)
    monkeypatch.setattr(record_controller, "validate_camera_device", lambda _device: None)

    recorder = record_controller.CameraRecorder(context=object(), config=config)
    record_bin = recorder._create_record_bin(str(tmp_path / "out.mp4"))

    assert record_bin is not None
    assert captured["record_desc"] == build_recording_branch("mp4", 24)
    assert captured["ghost_unlinked_pads"] is True
    assert record_bin.record_sink.properties["location"] == str(tmp_path / "out.mp4")


def test_recording_controller_passes_config_to_camera_recorder(monkeypatch, tmp_path):
    captured = {}
    config = RecorderConfig(
        device=str(tmp_path / "video0"),
        target_folder=str(tmp_path / "out"),
        stream_ip="127.0.0.8",
        stream_ip_port=5608,
        width=800,
        height=600,
        fps=25,
        record_format="raw",
    )

    class FakeCameraRecorder:
        def __init__(self, context, config):
            captured["context"] = context
            captured["config"] = config

        def start(self):
            return None

        def status(self):
            return {"started": True, "recording": False, "stopping": False}

    monkeypatch.setattr(record_controller, "CameraRecorder", FakeCameraRecorder)

    controller = record_controller.RecordingController(config=config)
    result = controller._init_pipeline()

    assert result["ok"] is True
    assert captured["config"] == config
