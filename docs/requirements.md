# BT Record Requirements

This document describes application behavior for `bt_record`. Engineering
patterns and agent guidance belong in `agent.md`.

## Purpose

`bt_record` provides a FastAPI HTTP service for managing GStreamer-based camera
recording and live UDP streaming.

The service should:

- start a recorder pipeline
- stream live video to a configured UDP destination
- start and stop recording on request
- expose recording status
- list, download, and delete recorded files

## Commands

The package entrypoint should support:

- `run`: start the recorder HTTP service.
- `version`: print the installed package version.
- `dump_config`: print effective configuration if config-file support is added.
- `dump_pipe`: dump pipe use config object to build the correct pipe
- `dump_receiver_pipe`: print runnable receiver pipeline using `fpsdisplaysink`
- `dump_device_formats`: print camera formats using `v4l2-ctl --list-formats-ext`
- `test`: run the gstreamer pipe with `videtestsrc` read all width, height and fps from the configuration

`main(args=None, standalone_mode=True)` should be callable from tests.

In `standalone_mode=False`, expected startup failures should raise
`RuntimeError(message)` instead of exiting the process.

## Startup Requirements

Before starting Uvicorn or any recorder worker thread, validate:

- camera device exists, for example `/dev/video0`
- record format is supported
- stream IP is valid
- target recording directory can be created and written
- GStreamer/PyGObject dependencies are available
- `v4l2-ctl` is available for `dump_device_formats`

Expected startup failures should produce one clear log line and a named exit
code. They should not print a Python traceback.

Recommended exit-code meanings:

```text
SUCCESS = 0
STARTUP_ERROR = 1
CLI_USAGE_ERROR = 2
DEVICE_NOT_FOUND = 3
GSTREAMER_DEPENDENCY_MISSING = 4
```

Missing camera device behavior:

```text
ERROR | Camera device not found: /dev/video0
```

Exit code: `DEVICE_NOT_FOUND`.

Missing GStreamer/PyGObject dependency behavior:

```text
ERROR | Missing PyGObject/GStreamer Python dependencies
```

Exit code: `GSTREAMER_DEPENDENCY_MISSING`.

## Runtime Requirements

The recorder service must expose:

- `GET /`: serve the web UI
- `GET /status`: return current recording status and server version
- `POST /start`: start recording, optionally using a requested name
- `POST /stop`: stop active recording
- `GET /files`: list recorded files with metadata
- `GET /files/{filename}`: download one recording file
- `DELETE /files`: delete all recording files when explicitly confirmed

Recording commands should be submitted through `RecordingController`.

HTTP error mapping:

- command timeout: `504`
- invalid user request: `400`
- recording conflict, such as active recording during delete: `409`
- unexpected controller failure: `500`

Startup validation failures should happen before the HTTP service starts, not as
HTTP `500` responses.

## Recording Files

Recorded file listing should include:

- file name
- file size
- modification time
- download URL

Files should be sorted newest first.

Download paths must reject path traversal. Filenames containing `/` or `\`
should return `404`.

Delete-all must require explicit confirmation and must not run while recording
is active or stopping.

## Configuration Requirements

Current CLI-level settings:

| arg  | description  | default   |
|---|---|
| --stream-ip  | video stream udp destination ip address   | 127.0.0.1 |
| --stream-ip-port  | video stream udp destination ip port   | 5600 |
| --device | camera device path | /dev/video0 |
| --width | camera width | 640 |
| --height | camera height | 512 |
| --fps | camera fps | 30 |
| --record-format | how to save the file mp4, raw | default mp4 |
| --http-server-port | http server port | 8001 |
| --target-folder | recording output folder | ./output |


If config-file support is added later, CLI overrides should win over YAML
values.

## Lifecycle Requirements

Startup sequence:

```text
create config object with default
load yaml config file if exists
merge values to config object
parse args
merge values to config object
configure logging
validate config and device paths
construct RecordingController
construct FastAPI app
run uvicorn
```

FastAPI lifespan should own recorder runtime:

```text
recorder.start()
yield
recorder.stop()
```

Shutdown should stop active recording cleanly when possible and release the
GStreamer pipeline.

## Test Requirements

Add focused tests for:

- wrong `--device` exits with `DEVICE_NOT_FOUND`
- bad `--stream-ip` exits with `CLI_USAGE_ERROR`
- bad `--record-format` is rejected before service startup
- `main(..., standalone_mode=False)` raises `RuntimeError`, not `SystemExit`
- `create_app(fake_recorder)` does not touch real camera hardware
- importing `bt_record.record_app` does not start recorder threads
- `GET /files/{filename}` rejects path traversal
- delete-all requires confirmation
- delete-all fails while recording is active or stopping
