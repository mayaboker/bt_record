import yaml

import bt_record.main as main_module
from bt_record.config import RecorderConfig
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
)
from bt_record.errors import RecordExitCode
from bt_record.main import build_config, main
from bt_record.cli import parse_cli_args


def test_recorder_config_defaults():
    config = RecorderConfig()

    assert config.stream_ip == DEFAULT_STREAM_IP
    assert config.stream_ip_port == DEFAULT_STREAM_IP_PORT
    assert config.device == DEFAULT_CAMERA_DEVICE
    assert config.width == DEFAULT_WIDTH
    assert config.height == DEFAULT_HEIGHT
    assert config.fps == DEFAULT_FPS
    assert config.record_format == DEFAULT_RECORD_FORMAT
    assert config.http_server_port == DEFAULT_HTTP_PORT
    assert config.target_folder == DEFAULT_TARGET_FOLDER


def test_yaml_values_override_defaults(tmp_path):
    config_path = tmp_path / "record.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "stream_ip": "192.168.1.20",
                "width": 800,
                "height": 600,
                "fps": 25,
            }
        ),
        encoding="utf-8",
    )

    config = build_config(parse_cli_args(["dump_config", "-c", str(config_path)]))

    assert config.stream_ip == "192.168.1.20"
    assert config.width == 800
    assert config.height == 600
    assert config.fps == 25


def test_cli_values_override_yaml(tmp_path):
    config_path = tmp_path / "record.yaml"
    config_path.write_text(
        yaml.safe_dump({"stream_ip": "192.168.1.20", "width": 800}),
        encoding="utf-8",
    )

    config = build_config(
        parse_cli_args(
            [
                "dump_config",
                "-c",
                str(config_path),
                "--stream-ip",
                "127.0.0.2",
                "--width",
                "1024",
            ]
        )
    )

    assert config.stream_ip == "127.0.0.2"
    assert config.width == 1024


def test_missing_explicit_config_path_fails_cleanly(tmp_path):
    config_path = tmp_path / "missing.yaml"

    with pytest_raises_runtime_error("Config file not found"):
        main(["dump_config", "-c", str(config_path)], standalone_mode=False)


def test_invalid_yaml_fails_cleanly(tmp_path):
    config_path = tmp_path / "record.yaml"
    config_path.write_text("stream_ip: [\n", encoding="utf-8")

    with pytest_raises_runtime_error("Failed to load config from"):
        main(["dump_config", "-c", str(config_path)], standalone_mode=False)


def test_non_mapping_yaml_fails_cleanly(tmp_path):
    config_path = tmp_path / "record.yaml"
    config_path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest_raises_runtime_error("expected YAML mapping"):
        main(["dump_config", "-c", str(config_path)], standalone_mode=False)


def test_version_prints_package_version(capsys):
    main(["version"], standalone_mode=False)

    assert capsys.readouterr().out.strip()


def test_dump_config_prints_effective_config(tmp_path, capsys):
    target_folder = tmp_path / "out"

    main(
        [
            "dump_config",
            "--stream-ip",
            "127.0.0.2",
            "--width",
            "800",
            "--target-folder",
            str(target_folder),
        ],
        standalone_mode=False,
    )

    config = yaml.safe_load(capsys.readouterr().out)
    assert config["stream_ip"] == "127.0.0.2"
    assert config["width"] == 800
    assert config["target_folder"] == str(target_folder)


def test_dump_pipe_uses_effective_config(tmp_path, capsys):
    main(
        [
            "dump_pipe",
            "--stream-ip",
            "127.0.0.3",
            "--stream-ip-port",
            "5601",
            "--width",
            "800",
            "--height",
            "600",
            "--fps",
            "25",
            "--target-folder",
            str(tmp_path / "out"),
        ],
        standalone_mode=False,
    )

    output = capsys.readouterr().out
    assert "width=800" in output
    assert "height=600" in output
    assert "framerate=25/1" in output
    assert "host=127.0.0.3" in output
    assert "port=5601" in output


def test_dump_receiver_pipe_prints_runnable_command_without_camera(tmp_path, capsys):
    main(
        [
            "dump_receiver_pipe",
            "--device",
            str(tmp_path / "missing-video0"),
            "--stream-ip-port",
            "5601",
            "--target-folder",
            str(tmp_path / "out"),
        ],
        standalone_mode=False,
    )

    output = capsys.readouterr().out
    assert output.startswith("gst-launch-1.0 -v ")
    assert "udpsrc port=5601" in output
    assert "fpsdisplaysink video-sink=autovideosink" in output


def test_dump_receiver_pipe_uses_yaml_then_cli_override(tmp_path, capsys):
    config_path = tmp_path / "record.yaml"
    config_path.write_text(
        yaml.safe_dump({"stream_ip_port": 5601}),
        encoding="utf-8",
    )

    main(
        [
            "dump_receiver_pipe",
            "-c",
            str(config_path),
            "--stream-ip-port",
            "5602",
            "--target-folder",
            str(tmp_path / "out"),
        ],
        standalone_mode=False,
    )

    output = capsys.readouterr().out
    assert "udpsrc port=5602" in output


def test_test_command_uses_videotestsrc_without_camera_device(monkeypatch, tmp_path):
    calls = []

    def fake_run_test_pipeline(config):
        calls.append(config)

    monkeypatch.setattr(main_module, "run_test_pipeline", fake_run_test_pipeline)

    main(
        [
            "test",
            "--device",
            str(tmp_path / "missing-video0"),
            "--target-folder",
            str(tmp_path / "out"),
        ],
        standalone_mode=False,
    )

    assert calls


def test_run_validates_camera_device_before_uvicorn(tmp_path):
    missing_device = tmp_path / "missing-video0"

    with pytest_raises_runtime_error("Camera device not found"):
        main(["run", "--device", str(missing_device)], standalone_mode=False)


def test_invalid_port_fails_before_startup(tmp_path):
    with pytest_raises_runtime_error("Invalid stream_ip_port"):
        main(["dump_config", "--stream-ip-port", "70000"], standalone_mode=False)


def test_invalid_dimensions_fail_before_startup(tmp_path):
    with pytest_raises_runtime_error("Invalid width"):
        main(["dump_config", "--width", "0"], standalone_mode=False)


def test_bad_record_format_exits_with_usage_code():
    try:
        main(["dump_config", "--record-format", "avi"], standalone_mode=True)
    except SystemExit as exc:
        assert exc.code == RecordExitCode.CLI_USAGE_ERROR
    else:
        raise AssertionError("SystemExit was not raised")


class pytest_raises_runtime_error:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        import pytest

        self._ctx = pytest.raises(RuntimeError, match=self.message)
        return self._ctx.__enter__()

    def __exit__(self, *args):
        return self._ctx.__exit__(*args)
