# Agent Notes For `bt_record`

This file is for stable engineering guidance. Do not use it as the product
requirements document. Put recorder behavior, API contracts, deployment details,
and changing application requirements under `docs/`.

## Design Principles

Prefer SOLID-style boundaries:

- Single Responsibility: CLI parsing, app startup, FastAPI routes, and GStreamer control should live in separate modules/classes.
- Open/Closed: add new recorder backends or output formats through small strategy classes instead of editing route handlers.
- Liskov Substitution: fake recorders used in tests should satisfy the same interface as the real recorder.
- Interface Segregation: route handlers should depend on a small recorder protocol, not the full concrete controller.
- Dependency Inversion: app factories should receive dependencies such as recorder/controller objects instead of constructing hardware-facing objects internally.

## Architecture

Follow the `bt_app` entrypoint shape:

- `cli.py`: parse command-line arguments into a small options object.
- `main.py`: configure logging, build config, handle expected startup errors,
  and dispatch commands.
- `errors.py`: define process exit codes and expected startup exceptions.
- `record_app.py`: define the FastAPI app factory and routes.
- `record_controller.py`: own GStreamer pipeline and recording behavior.

Keep parsing, validation, web routes, and GStreamer control separated. This keeps
startup failures clean and makes route tests possible without real hardware.

## Error Boundary

Use a project-specific startup exception for expected startup failures. `main.py`
should be the only place that turns those failures into `SystemExit`.

Library modules should not call `SystemExit`. They should raise typed exceptions
with enough context for `main.py` to log one clear line.

Centralize process exit codes in one enum. Do not scatter raw numeric exit codes
through the codebase.

## Import Safety

Importing `bt_record.record_app` should not:

- validate camera hardware
- start recorder threads
- allocate GStreamer pipelines
- start Uvicorn
- exit the process

Construct hardware-facing objects after CLI/config validation.

## FastAPI Pattern

Keep `create_app(recorder)` as a pure app factory:

- receive a recorder/controller object
- define routes
- start and stop the recorder in lifespan
- avoid CLI parsing and config selection

This allows tests to use fake recorders:

```python
app = create_app(fake_recorder)
```

## Testing Guidance

Add tests at the process boundary and the app factory boundary:

- CLI parse errors do not start services.
- Expected startup failures are clean in `standalone_mode=False`.
- `create_app(fake_recorder)` does not touch real camera hardware.
- Importing modules does not start recorder work.

For behavior requirements, read `docs/requirements.md`.
