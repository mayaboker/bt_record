import asyncio
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from bt_record.encoder_controller import (
    CMD_SET_ENCODER,
    CMD_STATUS,
    EncoderController,
)


STATIC_DIR = Path(__file__).with_name("static")

app = FastAPI()
encoder_controller = EncoderController()


class EncoderRequest(BaseModel):
    bitrate_kbps: int
    speed_preset: str
    key_int_max: int
    tune: str


@app.on_event("startup")
def startup():
    encoder_controller.start()


@app.on_event("shutdown")
def shutdown():
    encoder_controller.stop()


async def await_encoder_command(name: str, args: dict | None = None):
    try:
        future = encoder_controller.submit(name, args)
        return await asyncio.wait_for(
            asyncio.wrap_future(future),
            timeout=3,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"GStreamer encoder command timed out: {name}",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "encoder.html")


@app.get("/status")
async def status():
    return await await_encoder_command(CMD_STATUS)


@app.post("/encoder")
async def set_encoder(req: EncoderRequest):
    return await await_encoder_command(
        CMD_SET_ENCODER,
        {
            "bitrate_kbps": req.bitrate_kbps,
            "speed_preset": req.speed_preset,
            "key_int_max": req.key_int_max,
            "tune": req.tune,
        },
    )


def main() -> None:
    uvicorn.run("bt_record.encoder_app:app", host="0.0.0.0", port=8003)
