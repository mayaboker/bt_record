# BT Record Milestone 2 Plan: Config Object And CLI Commands

## Summary

Milestone 2 introduces a single recorder configuration object and expands the
CLI from the current minimal startup path into command-based behavior. It builds
on Milestone 1, so startup errors, import safety, and `main(args=None,
standalone_mode=True)` are assumed to already exist.

This milestone does not refactor GStreamer pipeline construction deeply; it only
threads configuration values through the existing startup path and adds command
surfaces needed by later milestones.

## Key Changes

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
- Extend CLI parsing to command-based behavior:
  - `run`: validate config, create `RecordingController`, create FastAPI app, run Uvicorn.
  - `version`: print installed package version.
  - `dump_config`: print effective config as YAML.
  - `dump_pipe`: print the GStreamer pipeline generated from the effective config.
  - `test`: run a `videotestsrc` pipeline using configured width, height, fps, stream IP, and stream port.
- Add config merge flow:
  - Start with dataclass defaults.
  - Load YAML only when an explicit config path is supplied.
  - Merge YAML values into the config object.
  - Merge CLI overrides last.
  - Fail with `RecordStartupError` if an explicit config path is missing, unreadable, invalid YAML, or not a mapping.
- Validate effective config before service startup:
  - stream IP is valid
  - stream port and HTTP port are valid TCP/UDP port integers
  - width, height, and fps are positive integers
  - record format is one of `mp4` or `raw`
  - target folder can be created or written
  - camera device exists for `run`, but not for `dump_config`, `dump_pipe`, or `test`

## CLI Interface

- Keep the console script name `bt-gst-record`.
- Use subcommands:

```bash
bt-gst-record run [options]
bt-gst-record version
bt-gst-record dump_config [options]
bt-gst-record dump_pipe [options]
bt-gst-record test [options]
```

- Shared config options:
  - `-c, --config PATH`
  - `--stream-ip IP`
  - `--stream-ip-port PORT`
  - `--device PATH`
  - `--width WIDTH`
  - `--height HEIGHT`
  - `--fps FPS`
  - `--record-format {mp4,raw}`
  - `--http-server-port PORT`
  - `--target-folder PATH`
- `run` passes config into `RecordingController` and starts Uvicorn on `0.0.0.0:<http_server_port>`.
- `dump_config` prints the final config after defaults, YAML, and CLI overrides.
- `dump_pipe` may use the current pipeline string logic initially, even if the builder is still extracted in Milestone 3.
- `test` uses `videotestsrc`; it must not require a real camera device.

## Out Of Scope

- No deep pipeline builder extraction beyond the minimum needed for `dump_pipe` and `test`.
- No HTTP route changes.
- No recording file behavior changes.
- No changes to `create_app(recorder)` semantics.
- No new recording formats.

## Test Plan

- Add config tests:
  - defaults produce the expected config object.
  - YAML values override defaults.
  - CLI values override YAML.
  - missing explicit config path fails cleanly.
  - invalid YAML fails cleanly.
  - non-mapping YAML fails cleanly.
- Add CLI command tests:
  - `version` prints package version.
  - `dump_config` includes all config fields and resolved overrides.
  - `dump_pipe` output contains configured width, height, fps, stream IP, and stream port.
  - `test` uses `videotestsrc` and does not validate the camera device path.
  - `run` validates the camera device before starting Uvicorn.
- Add validation tests:
  - invalid stream IP fails with CLI usage or startup error before service startup.
  - invalid ports fail before service startup.
  - invalid width, height, or fps fail before service startup.
  - invalid record format fails before service startup.

Run focused tests:

```bash
uv run --project bt_record pytest bt_record/tests -q
```

## Acceptance Criteria

- `bt-gst-record run` still starts the recorder service with default config when hardware is available.
- CLI subcommands are available and testable without starting hardware unless the command is `run`.
- Effective config is deterministic: defaults, then YAML, then CLI overrides.
- `dump_config` and `dump_pipe` are safe diagnostic commands and do not start Uvicorn.
- `test` runs the synthetic source path and does not require `/dev/video0`.
- Existing FastAPI routes remain unchanged.

## Assumptions

- Milestone 1 is complete before this milestone starts.
- UDP stream port is standardized on `5600` to match the current GStreamer pipeline behavior.
- Config-file support is optional per invocation: no config path means defaults plus CLI overrides.
- `dump_pipe` can be implemented with a small interim helper and refined in Milestone 3.
