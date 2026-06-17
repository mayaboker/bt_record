import queue
import threading
from dataclasses import dataclass
from concurrent.futures import Future
from typing import Any

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gst, GLib


Gst.init(None)


PENDING = object()

CMD_INIT = "init"
CMD_SHUTDOWN = "shutdown"
CMD_SET_TEXT = "set_text"
CMD_STATUS = "status"


@dataclass
class Command:
    name: str
    args: dict[str, Any]
    future: Future


class GstController:
    def __init__(self):
        self.commands: queue.Queue[Command] = queue.Queue()

        self.context = GLib.MainContext()
        self.loop = GLib.MainLoop.new(self.context, False)
        self.thread = threading.Thread(target=self._thread_main, daemon=True)

        self.pipeline = None
        self.overlay = None

        self.started = False

    # ---------- public API called from FastAPI thread ----------

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

        # Wake the GLib/GStreamer thread.
        self._invoke(self._process_commands)

        return future

    def call_sync(self, name: str, args: dict | None = None, timeout: float = 2):
        future = self.submit(name, args)
        return future.result(timeout=timeout)

    def _invoke(self, callback):
        self.context.invoke_full(GLib.PRIORITY_DEFAULT, callback)

    # ---------- GStreamer thread ----------

    def _thread_main(self):
        # Make this context thread-default while the loop runs so sources and
        # async callbacks created on this thread attach to the GStreamer loop,
        # not to another thread's default context.
        self.context.push_thread_default()
        try:
            self.loop.run()
        finally:
            self.context.pop_thread_default()

    def _process_commands(self):
        """
        Runs on the GStreamer thread.
        """
        while True:
            try:
                cmd = self.commands.get_nowait()
            except queue.Empty:
                break

            try:
                result = self._handle_command(cmd)

                if result is not PENDING:
                    cmd.future.set_result(result)

            except Exception as exc:
                cmd.future.set_exception(exc)

        return False

    def _handle_command(self, cmd: Command):
        """
        Run on the GStreamer thread. Returns PENDING if the command is still in progress.
        """
        name = cmd.name
        args = cmd.args

        if name == CMD_INIT:
            return self._init_pipeline()

        if name == CMD_SHUTDOWN:
            return self._shutdown_pipeline()

        if name == CMD_SET_TEXT:
            return self._set_text(args["text"])

        if name == CMD_STATUS:
            return self._status()

        raise RuntimeError(f"Unknown command: {name}")

    # ---------- actual GStreamer logic; only called on GStreamer thread ----------

    def _init_pipeline(self):
        if self.started:
            return {"ok": True, "already_started": True}

        self.pipeline = Gst.parse_launch(
            "videotestsrc is-live=true pattern=ball "
            "! videoconvert "
            "! textoverlay name=overlay "
            "text='Initial text' "
            "valignment=top "
            "halignment=center "
            "font-desc='Sans, 32' "
            "! videoconvert "
            "! autovideosink"
        )

        self.overlay = self.pipeline.get_by_name("overlay")

        if self.overlay is None:
            raise RuntimeError("Could not find textoverlay element")

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

        ret = self.pipeline.set_state(Gst.State.PLAYING)

        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Failed to start GStreamer pipeline")

        self.started = True

        return {
            "ok": True,
            "pipeline": "started",
        }

    def _shutdown_pipeline(self):
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
            self.overlay = None

        self.started = False

        return {
            "ok": True,
            "pipeline": "stopped",
        }

    def _set_text(self, text: str):
        if self.overlay is None:
            raise RuntimeError("Pipeline is not running")

        self.overlay.set_property("text", text)

        return {
            "ok": True,
            "text": text,
        }

    def _status(self):
        return {
            "ok": True,
            "started": self.started,
            "has_pipeline": self.pipeline is not None,
            "has_overlay": self.overlay is not None,
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
