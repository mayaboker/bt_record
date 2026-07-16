# BT Record Milestone 3 Plan: Pipeline Builder And Controller Wiring

## Summary

Milestone 3 removes duplicated and hardcoded GStreamer pipeline strings from the
controller and centralizes pipeline construction in `bt_record.pipeline`.

Milestone 2 already added `RecorderConfig`, `dump_pipe`, `test`, and initial
pipeline helpers. This milestone finishes that refactor by making the runtime
camera pipeline and recording branches use the same builder path.

## Key Changes

- Expand `bt_record.pipeline` into the single place that builds pipeline text:
  - live camera pipeline from `RecorderConfig`
  - `videotestsrc` pipeline from `RecorderConfig`
  - `mp4` recording branch
  - `raw` recording branch
- Add a small config adapter for runtime controller wiring:
  - `RecordingController` should accept either explicit constructor values or a `RecorderConfig`.
  - `CameraRecorder` should receive the values it needs from the effective config.
- Remove pipeline string duplication from `CameraRecorder`:
  - replace inline live pipeline string with `build_live_pipeline(config)`.
  - replace inline recording branch strings with builder helpers.
- Keep GStreamer ownership unchanged:
  - `RecordingController` still owns thread and command lifecycle.
  - `CameraRecorder` still owns the active GStreamer pipeline object and bus callbacks.
  - `record_app.create_app(recorder)` stays independent from config parsing and hardware construction.

## Builder Interface

Use these public helpers in `bt_record.pipeline`:

```python
build_live_pipeline(config: RecorderConfig) -> str
build_test_pipeline(config: RecorderConfig) -> str
build_recording_branch(record_format: str, fps: int) -> str
run_test_pipeline(config: RecorderConfig) -> None
```

Behavior:

- `build_live_pipeline` uses `v4l2src name=camera`, configured resolution, fps,
  stream IP, and stream port.
- `build_test_pipeline` uses `videotestsrc is-live=true` and does not reference
  the camera device.
- `build_recording_branch("mp4", fps)` returns the current MP4 branch with
  `x264enc`, `h264parse`, `mp4mux`, and `filesink name=record-sink`.
- `build_recording_branch("raw", fps)` returns the current raw I420 branch with
  `filesink name=record-sink`.
- Unsupported formats raise `ValueError`.

## Out Of Scope

- No HTTP route changes.
- No new recording formats.
- No changes to file naming or dedupe logic.
- No changes to start/stop/EOS behavior.
- No changes to CLI command names or config merge order.
- No changes to Uvicorn startup behavior.

## Test Plan

- Add pipeline builder tests:
  - live pipeline includes `v4l2src name=camera`.
  - live pipeline includes configured width, height, fps, stream IP, and stream port.
  - test pipeline includes `videotestsrc is-live=true`.
  - test pipeline does not include `v4l2src`.
  - MP4 branch includes `mp4mux` and `filesink name=record-sink`.
  - raw branch does not include `mp4mux` and includes `filesink name=record-sink`.
  - unsupported recording format raises `ValueError`.
- Add controller wiring tests:
  - `RecordingController` passes effective config values into `CameraRecorder`.
  - `CameraRecorder` calls `Gst.parse_launch` with the live pipeline builder output.
  - `_create_record_bin()` calls `Gst.parse_bin_from_description` with the recording branch builder output.
- Keep existing Milestone 1 and 2 tests passing:

```bash
uv run --with pytest python -m pytest tests -q
uv run --project bt_record --with pytest python -m pytest bt_record/tests -q
```

## Acceptance Criteria

- `dump_pipe` and runtime `CameraRecorder` use the same live pipeline builder.
- `test` continues to use `videotestsrc` and does not require camera hardware.
- Runtime recording behavior remains unchanged for both `mp4` and `raw`.
- `RecordingController` remains the command/thread lifecycle boundary.
- The app factory remains hardware-independent.

## Assumptions

- Milestone 1 and Milestone 2 are complete before this starts.
- The stream UDP default remains `5600`.
- GStreamer object creation remains in `record_controller.py`; `pipeline.py`
  only builds text and runs the synthetic test pipeline command.
