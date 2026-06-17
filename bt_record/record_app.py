import asyncio
from urllib.parse import quote
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from bt_record.record_controller import (
    CMD_START,
    CMD_STATUS,
    CMD_STOP,
    RecordingController,
)


STATIC_DIR = Path(__file__).with_name("static")

app = FastAPI()
recorder = RecordingController()


class StartRecordingRequest(BaseModel):
    name: str | None = None


class DeleteFilesRequest(BaseModel):
    confirm: bool = False


@app.on_event("startup")
def startup():
    recorder.start()


@app.on_event("shutdown")
def shutdown():
    recorder.stop()


async def await_record_command(name: str, args: dict | None = None):
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


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "record.html")


@app.get("/status")
async def status():
    return await await_record_command(CMD_STATUS)


def list_recording_files():
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


@app.get("/files")
async def files():
    return {
        "ok": True,
        "files": list_recording_files(),
    }


@app.delete("/files")
async def delete_files(req: DeleteFilesRequest):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Delete confirmation is required")

    status = await await_record_command(CMD_STATUS)
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
        "files": list_recording_files(),
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
        CMD_START,
        {"name": req.name if req is not None else None},
    )


@app.post("/stop")
async def stop_recording():
    return await await_record_command(CMD_STOP)


def main() -> None:
    uvicorn.run("bt_record.record_app:app", host="0.0.0.0", port=8001)
