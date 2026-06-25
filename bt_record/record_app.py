"""
GStreamer Recording Management API

A FastAPI-based HTTP service that provides REST API endpoints for managing
GStreamer-based media recordings. The service handles starting/stopping recordings,
monitoring recording status, and managing recorded files (download/delete).

Interface (API Endpoints):
    GET  /              - Serve the web UI (record.html)
    GET  /status        - Get current recording status
    POST /start         - Start a new recording session
    POST /stop          - Stop the current recording
    GET  /files         - List all recorded files with metadata
    GET  /files/{name}  - Download a specific recording file
    DELETE /files       - Delete all recorded files (with confirmation)

Usage:
    1. Start the server: python -m bt_record.record_app
    2. Access web UI: http://localhost:8001
    3. Control via API:
       - Start recording: POST /start with optional {"name": "custom_name"}
       - Check status: GET /status
       - Stop recording: POST /stop
       - List files: GET /files
       - Download: GET /files/{filename}
       - Delete all: DELETE /files with {"confirm": true}

The service runs a background RecordingController that manages GStreamer
processes asynchronously, with timeout handling for all operations (3s default).
"""

import argparse
import asyncio
from ipaddress import ip_address
from contextlib import asynccontextmanager
from urllib.parse import quote
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel

from bt_record import __version__
from bt_record.record_controller import (
    CMD_START,
    CMD_STATUS,
    CMD_STOP,
    DEFAULT_STREAM_IP,
    RecordingController,
    VALID_RECORD_FORMATS,
)


STATIC_DIR = Path(__file__).with_name("static")


class StartRecordingRequest(BaseModel):
    name: str | None = None


class DeleteFilesRequest(BaseModel):
    confirm: bool = False


async def await_record_command(
    recorder: RecordingController,
    name: str,
    args: dict | None = None,
):
    try:
        future = recorder.submit(name, args)
        return await asyncio.wait_for(
            asyncio.wrap_future(future),
            timeout=3,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"GStreamer recording command timed out: {name}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


def list_recording_files(recorder: RecordingController):
    target_folder = recorder.target_folder
    if not target_folder.exists():
        return []

    files = []
    for path in target_folder.iterdir():
        if not path.is_file():
            continue
        stat = path.stat()
        files.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "download_url": f"/files/{quote(path.name)}",
            }
        )

    files.sort(key=lambda item: item["modified"], reverse=True)
    return files


def create_app(recorder: RecordingController) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(f"BT GStreamer Recorder v{__version__} starting")
        recorder.start()
        yield
        recorder.stop()

    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "record.html")

    @app.get("/status")
    async def status():
        return await await_record_command(recorder, CMD_STATUS)

    @app.get("/files")
    async def files():
        return {
            "ok": True,
            "files": list_recording_files(recorder),
        }

    @app.delete("/files")
    async def delete_files(req: DeleteFilesRequest):
        if not req.confirm:
            raise HTTPException(status_code=400, detail="Delete confirmation is required")

        status = await await_record_command(recorder, CMD_STATUS)
        if status.get("recording") or status.get("stopping"):
            raise HTTPException(
                status_code=409,
                detail="Cannot delete files while recording is active or stopping",
            )

        deleted = []
        target_folder = recorder.target_folder
        if target_folder.exists():
            for path in target_folder.iterdir():
                if not path.is_file():
                    continue
                path.unlink()
                deleted.append(path.name)

        deleted.sort()
        return {
            "ok": True,
            "deleted": deleted,
            "files": list_recording_files(recorder),
        }

    @app.get("/files/{filename}")
    async def download_file(filename: str):
        if "/" in filename or "\\" in filename:
            raise HTTPException(status_code=404, detail="Recording file not found")

        path = recorder.target_folder / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Recording file not found")

        return FileResponse(path, filename=filename)

    @app.post("/start")
    async def start_recording(req: StartRecordingRequest | None = None):
        return await await_record_command(
            recorder,
            CMD_START,
            {
                "name": req.name if req is not None else None,
            },
        )

    @app.post("/stop")
    async def stop_recording():
        return await await_record_command(recorder, CMD_STOP)

    return app


app = create_app(RecordingController())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the BT GStreamer recorder API.")
    parser.add_argument(
        "--stream-ip",
        default=DEFAULT_STREAM_IP,
        help=f"UDP stream destination IP address. Default: {DEFAULT_STREAM_IP}",
    )
    parser.add_argument(
        "--record-format",
        choices=sorted(VALID_RECORD_FORMATS),
        default="mp4",
        help="Recording output format. Default: mp4",
    )
    args = parser.parse_args()

    try:
        ip_address(args.stream_ip)
    except ValueError:
        parser.error(f"invalid --stream-ip value: {args.stream_ip!r}")

    return args


def main() -> None:
    args = parse_args()
    configured_recorder = RecordingController(
        record_format=args.record_format,
        stream_ip=args.stream_ip,
    )
    configured_app = create_app(configured_recorder)
    uvicorn.run(configured_app, host="0.0.0.0", port=8001)
