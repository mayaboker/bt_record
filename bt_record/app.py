import asyncio
import uvicorn
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from bt_record.gst_controller import GstController


STATIC_DIR = Path(__file__).with_name("static")

app = FastAPI()
gst = GstController()


class TextRequest(BaseModel):
    text: str


@app.on_event("startup")
def startup():
    gst.start()


@app.on_event("shutdown")
def shutdown():
    gst.stop()


async def await_gst_command(name: str, args: dict | None = None):
    try:
        future = gst.submit(name, args)
        return await asyncio.wait_for(
            asyncio.wrap_future(future),
            timeout=3,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"GStreamer command timed out: {name}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/status")
async def status():
    return await await_gst_command("status")


@app.post("/text")
async def set_text(req: TextRequest):
    return await await_gst_command(
        "set_text",
        {"text": req.text},
    )



def main() -> None:
    uvicorn.run("bt_record.app:app", host="0.0.0.0", port=8000)
