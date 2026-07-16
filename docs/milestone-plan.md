# BT Record Milestone Plan

## Summary

This plan breaks the `bt_record/docs/requirements.md` work into implementation
milestones. The first milestones focus on safe startup and testability before
adding broader CLI/config features.

## Milestone 1: Startup Boundary And Import Safety

- Add `bt_record.errors` with:
  - `RecordExitCode`: `SUCCESS=0`, `STARTUP_ERROR=1`, `CLI_USAGE_ERROR=2`, `DEVICE_NOT_FOUND=3`, `GSTREAMER_DEPENDENCY_MISSING=4`.
  - `RecordStartupError(message, exit_code=RecordExitCode.STARTUP_ERROR)`.
- Split CLI/app startup:
  - Add `bt_record.cli` to parse command options into a typed options object.
  - Add `bt_record.main` with `main(args=None, standalone_mode=True)`.
  - Update `pyproject.toml` script to point to `bt_record.main:main`.
- Remove process exits from library modules:
  - `record_controller.py` must not raise `SystemExit` on missing `gi`.
  - Convert missing GStreamer/PyGObject dependency into `RecordStartupError`.
- Remove import-time hardware startup:
  - Replace `app = create_app(RecordingController())` with an import-safe factory pattern.
  - Importing `record_app.py` must not validate camera hardware, create GStreamer pipelines, start threads, or exit.

## Milestone 2: Config Object And CLI Commands

- Add a recorder config dataclass with defaults:
  - `stream_ip="127.0.0.1"`
  - `stream_ip_port=5600`
  - `device="/dev/video0"`
  - `width=640`
  - `height=512`
  - `fps=30`
  - `record_format="mp4"`
  - `http_server_port=8001`
  - `target_folder="./output"`
- Add CLI commands:
  - `run`: validate config, create `RecordingController`, create FastAPI app, run Uvicorn.
  - `version`: print package version.
  - `dump_config`: print effective config.
  - `dump_pipe`: print the GStreamer pipeline generated from config.
  - `test`: run a test pipeline using `videotestsrc` with configured width, height, and fps.
- Add optional YAML config loading:
  - Start with dataclass defaults.
  - Merge YAML if config path exists and is supplied.
  - Merge CLI overrides last.
  - If explicit config path is missing or invalid, fail with a clean startup error.

## Milestone 3: Pipeline Builder And Controller Wiring

- Extract GStreamer pipeline description construction into reusable functions or a small builder:
  - live camera pipeline from config
  - `videotestsrc` test pipeline from config
  - recording branch for `mp4` and `raw`
- Replace hardcoded values in `CameraRecorder`:
  - device
  - width
  - height
  - fps
  - record format
  - stream IP
  - stream UDP port
- Keep `RecordingController` responsible for thread and command lifecycle.
- Keep `create_app(recorder)` independent from config parsing and hardware construction.

## Milestone 4: HTTP Behavior And File Safety

- Keep required endpoints:
  - `GET /`
  - `GET /status`
  - `POST /start`
  - `POST /stop`
  - `GET /files`
  - `GET /files/{filename}`
  - `DELETE /files`
- Preserve command timeout behavior as `504`.
- Map expected runtime conflicts to `409` where practical, especially delete while recording or stopping.
- Keep path traversal protection for downloads.
- Ensure file listing includes name, size, modified time, and download URL sorted newest first.
- Ensure delete-all requires explicit confirmation and does not run while recording or stopping.

## Milestone 5: Tests And Acceptance

- Add startup boundary tests:
  - missing camera device exits with `DEVICE_NOT_FOUND`.
  - missing GStreamer dependency exits with `GSTREAMER_DEPENDENCY_MISSING`.
  - bad stream IP exits with `CLI_USAGE_ERROR`.
  - bad record format is rejected before service startup.
  - `main(..., standalone_mode=False)` raises `RuntimeError`, not `SystemExit`.
- Add import and app factory tests:
  - importing `bt_record.record_app` does not start threads or touch hardware.
  - `create_app(fake_recorder)` works without a real camera.
- Add HTTP route tests:
  - download rejects path traversal.
  - delete-all requires confirmation.
  - delete-all returns conflict while recording or stopping.
  - file listing sorts newest first.
- Add CLI behavior tests:
  - `version` prints package version.
  - `dump_config` prints effective config.
  - `dump_pipe` contains configured width, height, fps, stream IP, and port.
  - `test` builds or runs the `videotestsrc` pipeline path without camera hardware.

## Assumptions

- UDP stream port is standardized on `5600` because the current working GStreamer pipeline already uses `udpsink port=5600`.
- `mp4` and `raw` remain the only supported recording formats.
- FastAPI lifespan remains responsible for `recorder.start()` and `recorder.stop()`.
- Route URLs do not change during this refactor.
- `requirements.md` should be updated later if the documented default stream port still differs from this plan.
