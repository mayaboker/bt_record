import pytest
import sys
import types

from bt_record.config import RecorderConfig
from bt_record.pipeline import (
    build_live_pipeline,
    build_receiver_command,
    build_receiver_pipeline,
    build_recording_branch,
    build_test_pipeline,
    run_test_pipeline,
)


def test_live_pipeline_uses_camera_and_config_values():
    config = RecorderConfig(
        stream_ip="127.0.0.9",
        stream_ip_port=5609,
        width=800,
        height=600,
        fps=25,
    )

    pipeline = build_live_pipeline(config)

    assert "v4l2src name=camera" in pipeline
    assert "width=800" in pipeline
    assert "height=600" in pipeline
    assert "framerate=25/1" in pipeline
    assert "host=127.0.0.9" in pipeline
    assert "port=5609" in pipeline


def test_test_pipeline_uses_videotestsrc_not_camera():
    config = RecorderConfig(width=320, height=240, fps=15)

    pipeline = build_test_pipeline(config)

    assert "videotestsrc is-live=true" in pipeline
    assert "v4l2src" not in pipeline
    assert "width=320" in pipeline
    assert "height=240" in pipeline
    assert "framerate=15/1" in pipeline


def test_mp4_recording_branch_uses_mp4_muxer_and_sink():
    branch = build_recording_branch("mp4", 30)

    assert "mp4mux" in branch
    assert "x264enc" in branch
    assert "key-int-max=30" in branch
    assert "filesink name=record-sink" in branch


def test_raw_recording_branch_uses_i420_sink_without_mp4_muxer():
    branch = build_recording_branch("raw", 30)

    assert "video/x-raw,format=I420,framerate=30/1" in branch
    assert "filesink name=record-sink" in branch
    assert "mp4mux" not in branch


def test_recording_branch_rejects_unknown_format():
    with pytest.raises(ValueError):
        build_recording_branch("avi", 30)


def test_receiver_pipeline_uses_udp_h264_caps_and_fps_display():
    config = RecorderConfig(stream_ip_port=5601)

    pipeline = build_receiver_pipeline(config)

    assert "udpsrc port=5601" in pipeline
    assert 'caps="application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000"' in pipeline
    assert "rtph264depay" in pipeline
    assert "h264parse" in pipeline
    assert "avdec_h264" in pipeline
    assert "videoconvert" in pipeline
    assert pipeline.strip().endswith(
        "fpsdisplaysink video-sink=autovideosink sync=false text-overlay=true"
    )


def test_receiver_command_is_runnable_gst_launch_command():
    command = build_receiver_command(RecorderConfig(stream_ip_port=5602))

    assert command.startswith("gst-launch-1.0 -v ")
    assert "udpsrc port=5602" in command
    assert "fpsdisplaysink" in command


def test_run_test_pipeline_keeps_playing_until_loop_returns(monkeypatch):
    states = []

    class FakePipeline:
        def get_bus(self):
            return FakeBus()

        def set_state(self, state):
            states.append(state)
            return FakeGst.StateChangeReturn.SUCCESS

    class FakeBus:
        def add_signal_watch(self):
            return None

        def connect(self, *_args):
            return None

        def remove_signal_watch(self):
            return None

    class FakeLoop:
        def run(self):
            assert states == [FakeGst.State.PLAYING]

        def quit(self):
            return None

    class FakeGst:
        State = types.SimpleNamespace(PLAYING="PLAYING", NULL="NULL")
        StateChangeReturn = types.SimpleNamespace(SUCCESS="SUCCESS", FAILURE="FAILURE")
        MessageType = types.SimpleNamespace(ERROR="ERROR", EOS="EOS")

        @staticmethod
        def init(_args):
            return None

        @staticmethod
        def parse_launch(_pipeline):
            return FakePipeline()

    fake_gi = types.ModuleType("gi")
    fake_gi.require_version = lambda *_args: None
    fake_repository = types.ModuleType("gi.repository")
    fake_repository.Gst = FakeGst
    fake_repository.GLib = types.SimpleNamespace(MainLoop=FakeLoop)

    monkeypatch.setitem(sys.modules, "gi", fake_gi)
    monkeypatch.setitem(sys.modules, "gi.repository", fake_repository)

    run_test_pipeline(RecorderConfig())

    assert states == [FakeGst.State.PLAYING, FakeGst.State.NULL]
