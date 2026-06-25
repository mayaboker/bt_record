import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gst, GLib


Gst.init(None)


CMD_INIT = "init"
CMD_SHUTDOWN = "shutdown"
CMD_SET_ENCODER = "set_encoder"
CMD_STATUS = "status"

MIN_BITRATE_KBPS = 100
MAX_BITRATE_KBPS = 10000
DEFAULT_BITRATE_KBPS = 2500

MIN_KEY_INT_MAX = 1
MAX_KEY_INT_MAX = 300
DEFAULT_KEY_INT_MAX = 30

SUPPORTED_SPEED_PRESETS = (
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
)
DEFAULT_SPEED_PRESET = "veryfast"

SUPPORTED_TUNES = ("zerolatency", "none")
DEFAULT_TUNE = "zerolatency"
MEASUREMENT_WINDOW_SECONDS = 1.0


@dataclass
class Command:
    name: str
    args: dict[str, Any]
    future: Future


class EncoderController:
    def __init__(self):
        self.commands: queue.Queue[Command] = queue.Queue()

        self.context = GLib.MainContext()
        self.loop = GLib.MainLoop.new(self.context, False)
        self.thread = threading.Thread(target=self._thread_main, daemon=True)

        self.pipeline = None
        self.encoder = None
        self.encoded_tap = None
        self.started = False

        self.bitrate_kbps = DEFAULT_BITRATE_KBPS
        self.speed_preset = DEFAULT_SPEED_PRESET
        self.key_int_max = DEFAULT_KEY_INT_MAX
        self.tune = DEFAULT_TUNE
        self.measured_bitrate_kbps = 0.0
        self.encoded_bytes_in_window = 0
        self.measurement_window_started_at = None

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
        if name == CMD_SET_ENCODER:
            return self._set_encoder(
                bitrate_kbps=args["bitrate_kbps"],
                speed_preset=args["speed_preset"],
                key_int_max=args["key_int_max"],
                tune=args["tune"],
            )
        if name == CMD_STATUS:
            return self._status()

        raise RuntimeError(f"Unknown command: {name}")

    def _init_pipeline(self):
        if self.started:
            return {"ok": True, "already_started": True, **self._status_fields()}

        self.pipeline = Gst.parse_launch(
            "v4l2src device=/dev/video0 "
            "! video/x-raw,format=YUY2,width=640,height=512,framerate=30/1 "
            "! videoconvert "
            "! video/x-raw,format=I420 "
            "! x264enc name=encoder "
            "bframes=0 "
            "byte-stream=true "
            "! h264parse "
            "! queue name=encoded_tap "
            "! avdec_h264 "
            "! videoconvert "
            "! fpsdisplaysink sync=false"
        )

        self.encoder = self.pipeline.get_by_name("encoder")
        if self.encoder is None:
            raise RuntimeError("Could not find x264 encoder")

        self.encoded_tap = self.pipeline.get_by_name("encoded_tap")
        if self.encoded_tap is None:
            raise RuntimeError("Could not find encoded bandwidth tap")

        self._reset_bandwidth_measurement()
        tap_src_pad = self.encoded_tap.get_static_pad("src")
        if tap_src_pad is None:
            raise RuntimeError("Encoded bandwidth tap has no src pad")
        tap_src_pad.add_probe(
            Gst.PadProbeType.BUFFER,
            self._measure_encoded_buffer,
        )

        self._apply_encoder_settings(
            bitrate_kbps=self.bitrate_kbps,
            speed_preset=self.speed_preset,
            key_int_max=self.key_int_max,
            tune=self.tune,
        )

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Failed to start encoder demo pipeline")

        self.started = True
        return {"ok": True, **self._status_fields()}

    def _shutdown_pipeline(self):
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
            self.encoder = None
            self.encoded_tap = None

        self.started = False
        self._reset_bandwidth_measurement()
        return {"ok": True, **self._status_fields()}

    def _set_encoder(
        self,
        *,
        bitrate_kbps: int,
        speed_preset: str,
        key_int_max: int,
        tune: str,
    ):
        bitrate_kbps = self._validate_bitrate_kbps(bitrate_kbps)
        speed_preset = self._validate_speed_preset(speed_preset)
        key_int_max = self._validate_key_int_max(key_int_max)
        tune = self._validate_tune(tune)

        if self.encoder is None:
            raise RuntimeError("Pipeline is not running")

        self._apply_encoder_settings(
            bitrate_kbps=bitrate_kbps,
            speed_preset=speed_preset,
            key_int_max=key_int_max,
            tune=tune,
        )

        self.bitrate_kbps = bitrate_kbps
        self.speed_preset = speed_preset
        self.key_int_max = key_int_max
        self.tune = tune

        return {"ok": True, **self._status_fields()}

    def _apply_encoder_settings(
        self,
        *,
        bitrate_kbps: int,
        speed_preset: str,
        key_int_max: int,
        tune: str,
    ):
        self.encoder.set_property("bitrate", bitrate_kbps)
        self.encoder.set_property("speed-preset", speed_preset)
        self.encoder.set_property("key-int-max", key_int_max)
        self.encoder.set_property("tune", tune)

    def _validate_bitrate_kbps(self, bitrate_kbps: int):
        if not MIN_BITRATE_KBPS <= bitrate_kbps <= MAX_BITRATE_KBPS:
            raise ValueError(
                f"bitrate_kbps must be between {MIN_BITRATE_KBPS} and {MAX_BITRATE_KBPS}"
            )
        return bitrate_kbps

    def _validate_speed_preset(self, speed_preset: str):
        if speed_preset not in SUPPORTED_SPEED_PRESETS:
            raise ValueError(
                "speed_preset must be one of: "
                f"{', '.join(SUPPORTED_SPEED_PRESETS)}"
            )
        return speed_preset

    def _validate_key_int_max(self, key_int_max: int):
        if not MIN_KEY_INT_MAX <= key_int_max <= MAX_KEY_INT_MAX:
            raise ValueError(
                f"key_int_max must be between {MIN_KEY_INT_MAX} and {MAX_KEY_INT_MAX}"
            )
        return key_int_max

    def _validate_tune(self, tune: str):
        if tune not in SUPPORTED_TUNES:
            raise ValueError(f"tune must be one of: {', '.join(SUPPORTED_TUNES)}")
        return tune

    def _reset_bandwidth_measurement(self):
        self.measured_bitrate_kbps = 0.0
        self.encoded_bytes_in_window = 0
        self.measurement_window_started_at = time.monotonic()

    def _calculate_bitrate_kbps(self, byte_count: int, elapsed_seconds: float):
        if elapsed_seconds <= 0:
            return 0.0
        return byte_count * 8.0 / elapsed_seconds / 1000.0

    def _measure_encoded_buffer(self, pad, info):
        buffer = info.get_buffer()
        if buffer is None:
            return Gst.PadProbeReturn.OK

        now = time.monotonic()
        if self.measurement_window_started_at is None:
            self.measurement_window_started_at = now

        self.encoded_bytes_in_window += buffer.get_size()
        elapsed = now - self.measurement_window_started_at

        if elapsed >= MEASUREMENT_WINDOW_SECONDS:
            self.measured_bitrate_kbps = self._calculate_bitrate_kbps(
                self.encoded_bytes_in_window,
                elapsed,
            )
            self.encoded_bytes_in_window = 0
            self.measurement_window_started_at = now

        return Gst.PadProbeReturn.OK

    def _status(self):
        return {"ok": True, **self._status_fields()}

    def _status_fields(self):
        return {
            "started": self.started,
            "has_pipeline": self.pipeline is not None,
            "has_encoder": self.encoder is not None,
            "has_encoded_tap": self.encoded_tap is not None,
            "bitrate_kbps": self.bitrate_kbps,
            "measured_bitrate_kbps": self.measured_bitrate_kbps,
            "measured_window_seconds": MEASUREMENT_WINDOW_SECONDS,
            "encoded_bytes_in_window": self.encoded_bytes_in_window,
            "speed_preset": self.speed_preset,
            "key_int_max": self.key_int_max,
            "tune": self.tune,
            "supported_speed_presets": list(SUPPORTED_SPEED_PRESETS),
            "supported_tunes": list(SUPPORTED_TUNES),
            "min_bitrate_kbps": MIN_BITRATE_KBPS,
            "max_bitrate_kbps": MAX_BITRATE_KBPS,
            "min_key_int_max": MIN_KEY_INT_MAX,
            "max_key_int_max": MAX_KEY_INT_MAX,
        }

    def _on_bus_message(self, bus, message):
        msg_type = message.type

        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"GStreamer error: {err}")
            if debug:
                print(f"GStreamer debug: {debug}")

        elif msg_type == Gst.MessageType.EOS:
            print("GStreamer EOS")
