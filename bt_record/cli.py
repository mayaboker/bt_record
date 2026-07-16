from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from bt_record.constants import VALID_RECORD_FORMATS
from bt_record.errors import RecordExitCode


class CommandName:
    RUN = "run"
    VERSION = "version"
    DUMP_CONFIG = "dump_config"
    DUMP_PIPE = "dump_pipe"
    DUMP_RECEIVER_PIPE = "dump_receiver_pipe"
    TEST = "test"


@dataclass(frozen=True)
class CliOptions:
    command: str
    config_path: Path | None = None
    overrides: dict[str, Any] | None = None


class CliParseExit(Exception):
    def __init__(self, exit_code: int = RecordExitCode.SUCCESS) -> None:
        super().__init__(exit_code)
        self.exit_code = exit_code


class CliParseError(Exception):
    def __init__(
        self,
        message: str,
        exit_code: int = RecordExitCode.CLI_USAGE_ERROR,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliParseError(f"{self.prog}: error: {message}")

    def exit(self, status: int = 0, message: str | None = None) -> None:
        if status == 0:
            raise CliParseExit(status)
        raise CliParseError(message.strip() if message else f"exit status {status}", status)


def parse_cli_args(args: Sequence[str] | None = None) -> CliOptions:
    parser = _ArgumentParser(description="Run the BT GStreamer recorder API.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    _add_config_command(subparsers, CommandName.RUN, "Run the recorder HTTP service.")
    subparsers.add_parser(CommandName.VERSION, help="Print the package version.")
    _add_config_command(subparsers, CommandName.DUMP_CONFIG, "Print effective config.")
    _add_config_command(subparsers, CommandName.DUMP_PIPE, "Print GStreamer pipeline.")
    _add_config_command(
        subparsers,
        CommandName.DUMP_RECEIVER_PIPE,
        "Print receiver GStreamer pipeline.",
    )
    _add_config_command(subparsers, CommandName.TEST, "Run videotestsrc pipeline.")

    parsed = parser.parse_args(args)
    overrides = {
        key: value
        for key, value in {
            "stream_ip": getattr(parsed, "stream_ip", None),
            "stream_ip_port": getattr(parsed, "stream_ip_port", None),
            "device": getattr(parsed, "device", None),
            "width": getattr(parsed, "width", None),
            "height": getattr(parsed, "height", None),
            "fps": getattr(parsed, "fps", None),
            "record_format": getattr(parsed, "record_format", None),
            "http_server_port": getattr(parsed, "http_server_port", None),
            "target_folder": getattr(parsed, "target_folder", None),
        }.items()
        if value is not None
    }
    return CliOptions(
        command=parsed.command,
        config_path=getattr(parsed, "config_path", None),
        overrides=overrides,
    )


def _add_config_command(
    subparsers: argparse._SubParsersAction,
    name: str,
    help_text: str,
) -> None:
    parser = subparsers.add_parser(name, help=help_text)
    parser.add_argument(
        "-c",
        "--config",
        dest="config_path",
        type=Path,
        help="Path to recorder YAML config.",
    )
    parser.add_argument("--stream-ip", help="UDP stream destination IP address.")
    parser.add_argument("--stream-ip-port", type=int, help="UDP stream destination port.")
    parser.add_argument("--device", help="Camera device path.")
    parser.add_argument("--width", type=int, help="Camera width.")
    parser.add_argument("--height", type=int, help="Camera height.")
    parser.add_argument("--fps", type=int, help="Camera frames per second.")
    parser.add_argument(
        "--record-format",
        choices=sorted(VALID_RECORD_FORMATS),
        help="Recording output format.",
    )
    parser.add_argument("--http-server-port", type=int, help="HTTP server port.")
    parser.add_argument("--target-folder", help="Recording output folder.")
