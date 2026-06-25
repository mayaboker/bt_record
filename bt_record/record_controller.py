import os
import queue
import re
import sys
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import gi
except ImportError as exc:
    raise SystemExit(
        """Missing PyGObject/GStreamer Python dependencies.\n"
        On Ubuntu/Debian install:
        sudo apt update
        sudo apt install -y \
        python3-gi \
        python3-gst-1.0 \
        gir1.2-gstreamer-1.0 \
        gir1.2-gst-plugins-base-1.0 \
        gstreamer1.0-tools \
        gstreamer1.0-plugins-base \
        gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad \
        gstreamer1.0-plugins-ugly \
        pkg-config \
        libcairo2-dev \
        libgirepository-2.0-dev \
        gobject-introspection \
        python3-dev \
        build-essential
        """
    ) from exc

from loguru import logger

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gst, GLib

Gst.init(None)

logger.remove()
logger.add(
    sys.stderr,
    colorize=True,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    ),
)


CMD_INIT = "init"
CMD_SHUTDOWN = "shutdown"
CMD_START = "start"
CMD_STOP = "stop"
CMD_STATUS = "status"

VALID_RECORDING_NAME_RE = re.compile(r"^[A-Za-z0-9 _.-]+$")
VALID_RECORD_FORMATS = {"mp4", "raw"}
DEFAULT_STREAM_IP = "10.0.0.17"


@dataclass
class Command:
    name: str
    args: dict[str, Any]
    future: Future


def get_element_or_raise(pipeline, name):
    elem = pipeline.get_by_name(name)
    if elem is None:
        raise RuntimeError(f"Could not find GStreamer element named {name!r}")
    return elem


def validate_camera_device(device):
    if not os.path.exists(device):
        raise FileNotFoundError(f"Camera device does not exist: {device}")


def validate_record_format(record_format):
    if record_format not in VALID_RECORD_FORMATS:
        raise ValueError("record_format must be 'mp4' or 'raw'")
    return record_format


class CameraRecorder:
    def __init__(
        self,
        context,
        device="/dev/video0",
        width=640,
        height=512,
        fps=30,
        record_format="mp4",
        stream_ip=DEFAULT_STREAM_IP,
    ):
        validate_record_format(record_format)

        validate_camera_device(device)

        self.context = context
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.record_format = record_format
        self.stream_ip = stream_ip
        self.record_filename = None
        self.last_finalized_filename = None
        self.pipeline_error = None

        pipeline_desc = f"""
            v4l2src name=camera
                ! video/x-raw,format=YUY2,width={self.width},height={self.height},framerate={self.fps}/1
                ! videoconvert
                ! video/x-raw,format=I420
                ! tee name=tee

            tee.
                ! queue name=live-queue
                ! videoconvert name=live-convert
                ! x264enc name=encoder 
                     bitrate=300 speed-preset=ultrafast tune=zerolatency 
                     key-int-max=30 vbv-buf-capacity=1000 
                     bframes=0 byte-stream=true 
                ! h264parse config-interval=1 
                ! rtph264pay pt=96 mtu=1400 config-interval=1 
                ! udpsink host={self.stream_ip} port=5600 sync=false async=false
        """

        logger.info("--------- pipeline description ---------")
        logger.info(pipeline_desc)
        logger.info("--------- pipeline description ---------")

        self.pipeline = Gst.parse_launch(pipeline_desc)
        self.pipeline.set_name("camera-pipeline")

        self.src = get_element_or_raise(self.pipeline, "camera")
        self.tee = get_element_or_raise(self.pipeline, "tee")
        self.live_queue = get_element_or_raise(self.pipeline, "live-queue")
        self.live_convert = get_element_or_raise(self.pipeline, "live-convert")
        # self.live_sink = get_element_or_raise(self.pipeline, "live-sink")
        self.src.set_property("device", self.device)

        self.record_bin = None
        self.record_tee_pad = None
        self.record_block_probe_id = None
        self.record_stop_timeout_source = None
        self.record_eos_sent = False
        self.record_first_pts = None
        self.record_first_dts = None
        self.recording = False
        self.stopping = False
        self.started = False

        self.pipeline.set_property("message-forward", True)
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect("message", self._on_bus_message)

    def start(self):
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Failed to start camera pipeline")
        self.started = True

    def shutdown(self):
        if self.recording:
            self.stop_recording()
            if self.record_bin is not None:
                self._finish_stop_recording()

        self.pipeline.set_state(Gst.State.NULL)
        self.started = False

    def start_recording(self, filename):
        if self.stopping:
            raise RuntimeError("Recording is still stopping")
        if self.recording:
            raise RuntimeError("Already recording")
        if not self.started:
            raise RuntimeError("Camera pipeline is not running")

        self.record_bin = self._create_record_bin(filename)
        self.record_filename = filename
        self.pipeline.add(self.record_bin)

        self.record_tee_pad = self.tee.request_pad_simple("src_%u")
        record_sink_pad = self.record_bin.get_static_pad("sink")

        if self.record_tee_pad.link(record_sink_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError("Failed to link tee to recording branch")

        self.record_bin.sync_state_with_parent()

        self.recording = True
        self.stopping = False
        self.record_block_probe_id = None
        self.record_stop_timeout_source = None
        self.record_eos_sent = False
        self.record_first_pts = None
        self.record_first_dts = None

        logger.info(f"Recording started: {filename} ({self.record_format})")

    def stop_recording(self):
        if not self.recording or not self.record_bin:
            return
        if self.stopping:
            return

        logger.info("Stopping recording...")

        self.stopping = True

        record_sink_pad = self.record_bin.get_static_pad("sink")
        if record_sink_pad is None:
            raise RuntimeError("Recording branch has no sink pad")

        if self.record_tee_pad is None:
            raise RuntimeError("Recording branch has no tee pad")

        def block_cb(pad, info):
            if not self.record_eos_sent:
                self.record_eos_sent = True
                self.record_block_probe_id = None
                pad.unlink(record_sink_pad)
                self.tee.release_request_pad(pad)
                self.record_tee_pad = None
                logger.info("Recording branch detached from tee")
                self.context.invoke_full(GLib.PRIORITY_DEFAULT, self._send_recording_eos)
                return Gst.PadProbeReturn.REMOVE
            return Gst.PadProbeReturn.OK

        self.record_block_probe_id = self.record_tee_pad.add_probe(
            Gst.PadProbeType.BLOCK_DOWNSTREAM,
            block_cb,
        )

    def _send_recording_eos(self):
        if not self.stopping or not self.record_bin:
            return False

        record_sink_pad = self.record_bin.get_static_pad("sink")
        if record_sink_pad is None:
            logger.warning("Recording branch has no sink pad for EOS")
            return False

        if not record_sink_pad.send_event(Gst.Event.new_eos()):
            logger.warning("Failed to send EOS to recording branch")

        timeout_source = GLib.timeout_source_new_seconds(5)
        timeout_source.set_callback(self._finish_stop_recording_after_timeout)
        timeout_source.attach(self.context)
        self.record_stop_timeout_source = timeout_source
        return False

    def _finish_stop_recording_after_timeout(self):
        self.record_stop_timeout_source = None
        if self.stopping and self.record_bin:
            logger.warning("Recording stop timed out waiting for EOS; cleaning up branch")
            self._finish_stop_recording()
        return False

    def _finish_stop_recording(self):
        if not self.record_bin:
            return False

        finalized_filename = self.record_filename

        if self.record_stop_timeout_source is not None:
            self.record_stop_timeout_source.destroy()
            self.record_stop_timeout_source = None

        if self.record_tee_pad is not None:
            record_sink_pad = self.record_bin.get_static_pad("sink")
            if self.record_block_probe_id is not None:
                self.record_tee_pad.remove_probe(self.record_block_probe_id)
                self.record_block_probe_id = None
            if record_sink_pad is not None:
                self.record_tee_pad.unlink(record_sink_pad)
            self.tee.release_request_pad(self.record_tee_pad)
            self.record_tee_pad = None

        self.record_bin.set_state(Gst.State.NULL)
        self.pipeline.remove(self.record_bin)

        self._print_recording_summary()

        self.record_bin = None
        self.record_filename = None
        self.last_finalized_filename = finalized_filename
        self.recording = False
        self.stopping = False
        self.record_eos_sent = False
        self.record_first_pts = None
        self.record_first_dts = None

        logger.info("Recording stopped and file finalized")
        return False

    def _print_recording_summary(self):
        if self.record_format != "raw" or not self.record_filename:
            return

        try:
            file_size = os.path.getsize(self.record_filename)
        except OSError as exc:
            logger.warning(f"Could not stat raw recording {self.record_filename}: {exc}")
            return

        frame_size = self.width * self.height * 3 // 2
        if frame_size <= 0:
            return

        frames = file_size / frame_size
        duration = frames / self.fps
        logger.info(
            f"Raw recording size={file_size} bytes, "
            f"frames={frames:.1f}, duration_at_{self.fps}fps={duration:.2f}s"
        )

    def _rebase_recording_timestamps(self, pad, info):
        buf = info.get_buffer()
        if buf is None:
            return Gst.PadProbeReturn.OK

        if self.record_first_pts is None and buf.pts != Gst.CLOCK_TIME_NONE:
            self.record_first_pts = buf.pts

        if self.record_first_dts is None and buf.dts != Gst.CLOCK_TIME_NONE:
            self.record_first_dts = buf.dts

        if self.record_first_pts is not None and buf.pts != Gst.CLOCK_TIME_NONE:
            buf.pts = max(0, buf.pts - self.record_first_pts)

        if self.record_first_dts is not None and buf.dts != Gst.CLOCK_TIME_NONE:
            buf.dts = max(0, buf.dts - self.record_first_dts)

        return Gst.PadProbeReturn.OK

    def _create_record_bin(self, filename):
        if self.record_format == "mp4":
            record_desc = f"""
            queue name=record-queue flush-on-eos=true
                ! videoconvert name=record-convert
                ! videorate name=record-rate drop-only=true
                ! video/x-raw,format=I420,framerate={self.fps}/1
                ! x264enc name=record-encoder
                          tune=zerolatency
                          speed-preset=veryfast
                          key-int-max={self.fps}
                ! h264parse name=record-parser
                ! mp4mux name=record-muxer
                ! filesink name=record-sink sync=false
        """
        else:
            print("Recording raw I420 video")
            print(filename)
            record_desc = f"""
            queue name=record-queue flush-on-eos=true
                ! videoconvert name=record-convert
                ! videorate name=record-rate drop-only=true
                ! video/x-raw,format=I420,framerate={self.fps}/1
                ! filesink name=record-sink sync=false
        """

        record_bin = Gst.parse_bin_from_description(record_desc, True)
        record_bin.set_name("record-bin")
        record_bin.set_property("message-forward", True)

        if record_bin.get_static_pad("sink") is None:
            raise RuntimeError("Recording bin did not expose a sink ghost pad")

        record_sink_pad = record_bin.get_static_pad("sink")
        record_sink_pad.add_probe(
            Gst.PadProbeType.BUFFER,
            self._rebase_recording_timestamps,
        )

        record_sink = record_bin.get_by_name("record-sink")
        if record_sink is None:
            raise RuntimeError("Recording bin did not create a filesink")
        record_sink.set_property("location", filename)

        return record_bin

    def status(self):
        return {
            "started": self.started,
            "recording": self.recording,
            "stopping": self.stopping,
            "format": self.record_format,
            "filename": self.record_filename,
            "last_finalized_filename": self.last_finalized_filename,
            "device": self.device,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "stream_ip": self.stream_ip,
            "error": self.pipeline_error,
        }

    def _on_bus_message(self, bus, message):
        msg_type = message.type

        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            self.pipeline_error = str(err)
            logger.error(f"GStreamer ERROR: {err}")
            if debug:
                logger.debug(f"Debug: {debug}")

        elif msg_type == Gst.MessageType.EOS:
            if self.stopping:
                self._finish_stop_recording()
            else:
                logger.info("Pipeline EOS")
                self.started = False

        elif msg_type == Gst.MessageType.ELEMENT:
            structure = message.get_structure()
            if structure is None or structure.get_name() != "GstBinForwarded":
                return

            forwarded = structure.get_value("message")
            if forwarded and forwarded.type == Gst.MessageType.EOS and self.stopping:
                source_name = forwarded.src.get_name() if forwarded.src else "unknown"
                logger.info(f"Recording branch EOS forwarded from {source_name}")
                self._finish_stop_recording()


class RecordingController:
    def __init__(
        self,
        device="/dev/video0",
        width=640,
        height=512,
        fps=30,
        record_format="mp4",
        target_folder="./output",
        stream_ip=DEFAULT_STREAM_IP,
    ):
        validate_record_format(record_format)

        self.commands: queue.Queue[Command] = queue.Queue()
        self.context = GLib.MainContext()
        self.loop = GLib.MainLoop.new(self.context, False)
        self.thread = threading.Thread(target=self._thread_main, daemon=True)

        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.record_format = record_format
        self.target_folder = Path(target_folder)
        self.stream_ip = stream_ip
        self.recorder = None
        self.last_error = None

    def start(self):
        self.thread.start()
        return self.call_sync(CMD_INIT, timeout=5)

    def stop(self):
        try:
            self.call_sync(CMD_SHUTDOWN, timeout=5)
        finally:
            self._invoke(lambda: self.loop.quit() or False)
            self.thread.join(timeout=2)

    def submit(self, name: str, args: dict | None = None) -> Future:
        future = Future()
        cmd = Command(name=name, args=args or {}, future=future)
        self.commands.put(cmd)
        self._invoke(self._process_commands)
        return future

    def call_sync(self, name: str, args: dict | None = None, timeout: float = 2):
        future = self.submit(name, args)
        return future.result(timeout=timeout)

    def _invoke(self, callback):
        self.context.invoke_full(GLib.PRIORITY_DEFAULT, callback)

    def _thread_main(self):
        self.context.push_thread_default()
        try:
            self.loop.run()
        finally:
            self.context.pop_thread_default()

    def _process_commands(self):
        while True:
            try:
                cmd = self.commands.get_nowait()
            except queue.Empty:
                break

            try:
                result = self._handle_command(cmd)
                cmd.future.set_result(result)
            except Exception as exc:
                cmd.future.set_exception(exc)

        return False

    def _handle_command(self, cmd: Command):
        name = cmd.name
        args = cmd.args

        if name == CMD_INIT:
            return self._init_pipeline()
        if name == CMD_SHUTDOWN:
            return self._shutdown_pipeline()
        if name == CMD_START:
            return self._start_recording(args.get("name"))
        if name == CMD_STOP:
            return self._stop_recording()
        if name == CMD_STATUS:
            return self._status()

        raise RuntimeError(f"Unknown command: {name}")

    def _init_pipeline(self):
        if self.recorder is not None:
            return {"ok": True, **self.recorder.status()}

        try:
            self.target_folder.mkdir(parents=True, exist_ok=True)
            recorder = CameraRecorder(
                context=self.context,
                device=self.device,
                width=self.width,
                height=self.height,
                fps=self.fps,
                record_format=self.record_format,
                stream_ip=self.stream_ip,
            )
            recorder.start()
        except Exception as exc:
            self.last_error = str(exc)
            logger.error("Failed to initialize camera pipeline")
            try:
                if "recorder" in locals():
                    recorder.shutdown()
            except Exception:
                logger.error("Failed to clean up partially initialized pipeline")
            self.recorder = None
            return {
                "ok": False,
                "started": False,
                "recording": False,
                "stopping": False,
                "format": self.record_format,
                "filename": None,
                "last_finalized_filename": None,
                "device": self.device,
                "width": self.width,
                "height": self.height,
                "fps": self.fps,
                "stream_ip": self.stream_ip,
                "error": self.last_error,
            }

        self.recorder = recorder
        self.last_error = None
        return {"ok": True, **self.recorder.status()}

    def _shutdown_pipeline(self):
        if self.recorder is not None:
            self.recorder.shutdown()
            status = self.recorder.status()
            self.recorder = None
            return {"ok": True, **status}
        return {"ok": True, "started": False, "recording": False, "stopping": False}

    def _start_recording(self, name: str | None = None):
        recorder = self._require_recorder()
        if recorder.stopping:
            raise RuntimeError("Recording is still stopping")
        if recorder.recording:
            raise RuntimeError("Already recording")
        if not recorder.started:
            raise RuntimeError("Camera pipeline is not running")
        filename = str(self._recording_path_for_name(name))
        recorder.start_recording(filename)
        return {"ok": True, **recorder.status()}

    def _stop_recording(self):
        recorder = self._require_recorder()
        recorder.stop_recording()
        return {"ok": True, **recorder.status()}

    def _status(self):
        if self.recorder is None:
            return {
                "ok": True,
                "started": False,
                "recording": False,
                "stopping": False,
                "format": self.record_format,
                "filename": None,
                "last_finalized_filename": None,
                "device": self.device,
                "width": self.width,
                "height": self.height,
                "fps": self.fps,
                "stream_ip": self.stream_ip,
                "error": self.last_error,
            }
        return {"ok": True, **self.recorder.status()}

    def _require_recorder(self):
        if self.recorder is None:
            raise RuntimeError("Camera pipeline is not running")
        return self.recorder

    def _next_recording_path(self):
        extension = "mp4" if self.record_format == "mp4" else "i420"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.target_folder / f"recording-{timestamp}.{extension}"
        return self._dedupe_recording_path(path)

    def _recording_path_for_name(self, name: str | None):
        if name is None or not name.strip():
            return self._next_recording_path()

        stem = name.strip()
        if "/" in stem or "\\" in stem:
            raise ValueError("Recording name must not contain path separators")
        if not VALID_RECORDING_NAME_RE.fullmatch(stem):
            raise ValueError(
                "Recording name may contain only letters, numbers, spaces, '.', '_', and '-'"
            )

        extension = "mp4" if self.record_format == "mp4" else "i420"
        for suffix in (".mp4", ".i420"):
            if stem.lower().endswith(suffix):
                stem = stem[: -len(suffix)].rstrip()
                break

        if not stem:
            return self._next_recording_path()

        path = self.target_folder / f"{stem}.{extension}"
        return self._dedupe_recording_path(path)

    def _dedupe_recording_path(self, path: Path):
        original_stem = path.stem
        extension = path.suffix
        index = 1
        while path.exists():
            path = self.target_folder / f"{original_stem}-{index}{extension}"
            index += 1
        return path
