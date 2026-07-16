# BT Record Milestone 1 Plan: Startup Boundary And Import Safety

## Summary

This milestone makes `bt_record` safe to import, testable from a CLI boundary,
and able to report expected startup failures with clean messages and named exit
codes.

Milestone 1 does not add YAML config, new pipeline builders, or new runtime HTTP
behavior.

## Key Changes

- Add `bt_record.errors`:
  - `RecordExitCode(IntEnum)` with `SUCCESS=0`, `STARTUP_ERROR=1`, `CLI_USAGE_ERROR=2`, `DEVICE_NOT_FOUND=3`, `GSTREAMER_DEPENDENCY_MISSING=4`.
  - `RecordStartupError(message, exit_code=RecordExitCode.STARTUP_ERROR)`.
- Add `bt_record.cli`:
  - Parse current supported runtime options only: `--stream-ip`, `--device`, `--record-format`.
  - Keep current defaults for Milestone 1: `DEFAULT_STREAM_IP` from current code, `/dev/video0`, and `mp4`.
  - Return a typed options object instead of starting the app.
- Add `bt_record.main`:
  - Expose `main(args=None, standalone_mode=True)`.
  - Configure logging.
  - Convert `RecordStartupError` into `SystemExit(int(exit_code))` in normal mode.
  - In `standalone_mode=False`, raise `RuntimeError(message)` for expected startup failures.
  - Dispatch the `run` behavior currently in `record_app.main()`.
- Update package entrypoint:
  - Change `bt-gst-record` in `pyproject.toml` from `bt_record.record_app:main` to `bt_record.main:main`.
- Make imports safe:
  - Remove `app = create_app(RecordingController())` from `record_app.py`.
  - Keep `create_app(recorder)` as the app factory.
  - Provide no module-level construction that validates hardware, creates GStreamer pipelines, starts threads, or exits.
- Remove library `SystemExit`:
  - Replace `SystemExit` from missing `gi` in `record_controller.py` with `RecordStartupError(..., GSTREAMER_DEPENDENCY_MISSING)`.
  - Ensure missing camera device is reported as `RecordStartupError(..., DEVICE_NOT_FOUND)` before Uvicorn starts.

## Out Of Scope

- No YAML config loading.
- No `dump_config`, `dump_pipe`, `version`, or `test` commands yet.
- No pipeline builder extraction.
- No change to HTTP route URLs or response bodies.
- No stream port refactor.
- No change to recording file behavior.

## Test Plan

- Add startup boundary tests:
  - Missing camera device exits with `RecordExitCode.DEVICE_NOT_FOUND` in standalone mode.
  - Missing camera device raises `RuntimeError("Camera device not found: ...")` in `standalone_mode=False`.
  - Bad `--stream-ip` is rejected before service startup with CLI usage failure.
  - Bad `--record-format` is rejected before service startup.
  - Missing GStreamer/PyGObject dependency is converted to `RecordStartupError` and does not call `SystemExit` from a library module.
- Add import-safety tests:
  - Importing `bt_record.record_app` does not instantiate `RecordingController`.
  - Importing `bt_record.record_app` does not start recorder threads.
  - `create_app(fake_recorder)` succeeds without real camera hardware.
- Run focused tests:

```bash
uv run --project bt_record pytest bt_record/tests -q
```

## Acceptance Criteria

- `bt-gst-record` still starts the recorder service with the current supported CLI options.
- Wrong camera device fails with one clear error line and exit code `3`.
- Missing GStreamer dependency fails with one clear error line and exit code `4`.
- Tests can call `main([...], standalone_mode=False)` without the process exiting.
- Importing `bt_record.record_app` is safe in tests and does not touch hardware.
- Existing FastAPI routes remain available through `create_app(recorder)`.

## Assumptions

- Milestone 1 keeps the current CLI behavior minimal and does not introduce subcommands yet.
- The current console script name remains `bt-gst-record`.
- `RecordingController` remains the owner of recorder thread lifecycle.
