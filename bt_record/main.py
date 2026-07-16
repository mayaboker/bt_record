from __future__ import annotations

from collections.abc import Sequence
import logging
import sys

import uvicorn
import yaml

try:
    from loguru import logger
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal envs
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger(__name__)

from bt_record import __version__
from bt_record.cli import (
    CliOptions,
    CliParseError,
    CliParseExit,
    CommandName,
    parse_cli_args,
)
from bt_record.config import (
    RecorderConfig,
    load_config_yaml,
    merge_config_values,
    validate_config,
)
from bt_record.constants import DEFAULT_HTTP_HOST
from bt_record.device_formats import dump_device_formats
from bt_record.errors import RecordExitCode, RecordStartupError
from bt_record.pipeline import (
    build_live_pipeline,
    build_receiver_command,
    run_test_pipeline,
)


def main(args: Sequence[str] | None = None, standalone_mode: bool = True) -> None:
    try:
        options = parse_cli_args(args)
    except CliParseExit as exc:
        _handle_exit(exc.exit_code, standalone_mode)
        return
    except CliParseError as exc:
        _configure_logging()
        _handle_error(exc.message, exc.exit_code, standalone_mode)
        return

    _configure_logging()
    try:
        dispatch_command(options)
    except RecordStartupError as exc:
        _handle_error(str(exc), exc.exit_code, standalone_mode)


def dispatch_command(options: CliOptions) -> None:
    if options.command == CommandName.VERSION:
        print(__version__)
        return

    config = build_config(options)

    if options.command == CommandName.DUMP_CONFIG:
        validate_config(config, require_device=False)
        print(yaml.safe_dump(config.to_dict(), sort_keys=False), end="")
        return

    if options.command == CommandName.DUMP_PIPE:
        validate_config(config, require_device=False)
        print(build_live_pipeline(config).strip())
        return

    if options.command == CommandName.DUMP_RECEIVER_PIPE:
        validate_config(config, require_device=False)
        print(build_receiver_command(config))
        return

    if options.command == CommandName.DUMP_DEVICE_FORMATS:
        validate_config(config, require_device=True)
        print(dump_device_formats(config), end="")
        return

    if options.command == CommandName.TEST:
        validate_config(config, require_device=False)
        run_test_pipeline(config)
        return

    if options.command == CommandName.RUN:
        run(config)
        return

    raise RuntimeError(f"unknown command: {options.command}")


def build_config(options: CliOptions) -> RecorderConfig:
    config = RecorderConfig()
    if options.config_path is not None:
        merge_config_values(config, load_config_yaml(options.config_path))
    if options.overrides:
        merge_config_values(config, options.overrides)
    return config


def run(config: RecorderConfig) -> None:
    validate_config(config, require_device=True)

    try:
        from bt_record.record_app import create_app
        from bt_record.record_controller import RecordingController
    except RecordStartupError:
        raise

    recorder = RecordingController(config=config)
    app = create_app(recorder)
    uvicorn.run(app, host=DEFAULT_HTTP_HOST, port=config.http_server_port)


def _configure_logging() -> None:
    if hasattr(logger, "remove") and hasattr(logger, "add"):
        logger.remove()
        logger.add(
            sys.stderr,
            level="INFO",
            format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level:<8}</level> | {module}:{line} | {message}",
        )
        return
    logger.setLevel(logging.INFO)


def _handle_error(
    message: str,
    exit_code: int | RecordExitCode,
    standalone_mode: bool,
) -> None:
    if not standalone_mode:
        raise RuntimeError(message)
    logger.error(message)
    raise SystemExit(int(exit_code))


def _handle_exit(exit_code: int | RecordExitCode, standalone_mode: bool) -> None:
    if not standalone_mode:
        raise CliParseExit(int(exit_code))
    raise SystemExit(int(exit_code))


if __name__ == "__main__":
    main()
