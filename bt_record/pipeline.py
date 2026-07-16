from __future__ import annotations

from bt_record.config import RecorderConfig
from bt_record.errors import RecordExitCode, RecordStartupError


def build_live_pipeline(config: RecorderConfig) -> str:
    return f"""
        v4l2src name=camera
            ! video/x-raw,format=YUY2,width={config.width},height={config.height},framerate={config.fps}/1
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
            ! udpsink host={config.stream_ip} port={config.stream_ip_port} sync=false async=false
    """


def build_test_pipeline(config: RecorderConfig) -> str:
    return f"""
        videotestsrc is-live=true
            ! video/x-raw,format=YUY2,width={config.width},height={config.height},framerate={config.fps}/1
            ! videoconvert
            ! video/x-raw,format=I420
            ! x264enc name=encoder
                 bitrate=300 speed-preset=ultrafast tune=zerolatency
                 key-int-max=30 vbv-buf-capacity=1000
                 bframes=0 byte-stream=true
            ! h264parse config-interval=1
            ! rtph264pay pt=96 mtu=1400 config-interval=1
            ! udpsink host={config.stream_ip} port={config.stream_ip_port} sync=false async=false
    """


def build_recording_branch(record_format: str, fps: int) -> str:
    if record_format == "mp4":
        return f"""
            queue name=record-queue flush-on-eos=true
                ! videoconvert name=record-convert
                ! videorate name=record-rate drop-only=true
                ! video/x-raw,format=I420,framerate={fps}/1
                ! x264enc name=record-encoder
                          tune=zerolatency
                          speed-preset=veryfast
                          key-int-max={fps}
                ! h264parse name=record-parser
                ! mp4mux name=record-muxer
                ! filesink name=record-sink sync=false
        """
    if record_format == "raw":
        return f"""
            queue name=record-queue flush-on-eos=true
                ! videoconvert name=record-convert
                ! videorate name=record-rate drop-only=true
                ! video/x-raw,format=I420,framerate={fps}/1
                ! filesink name=record-sink sync=false
        """
    raise ValueError("record_format must be 'mp4' or 'raw'")


def build_receiver_pipeline(config: RecorderConfig) -> str:
    return f"""
        udpsrc port={config.stream_ip_port} caps="application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000"
            ! rtph264depay
            ! h264parse
            ! avdec_h264
            ! videoconvert
            ! fpsdisplaysink video-sink=autovideosink sync=false text-overlay=true
    """


def build_receiver_command(config: RecorderConfig) -> str:
    return f"gst-launch-1.0 -v {build_receiver_pipeline(config).strip()}"


def run_test_pipeline(config: RecorderConfig) -> None:
    try:
        import gi
    except ImportError as exc:
        raise RecordStartupError(
            "Missing PyGObject/GStreamer Python dependencies",
            exit_code=RecordExitCode.GSTREAMER_DEPENDENCY_MISSING,
        ) from exc

    gi.require_version("Gst", "1.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gst, GLib

    Gst.init(None)
    pipeline = Gst.parse_launch(build_test_pipeline(config))
    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    error: RuntimeError | None = None

    def on_message(_bus, message):
        nonlocal error
        if message.type == Gst.MessageType.ERROR:
            gst_error, debug = message.parse_error()
            detail = f": {debug}" if debug else ""
            error = RuntimeError(f"GStreamer test pipeline error: {gst_error}{detail}")
            loop.quit()
        elif message.type == Gst.MessageType.EOS:
            loop.quit()

    bus.connect("message", on_message)
    try:
        ret = pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Failed to start GStreamer test pipeline")
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.set_state(Gst.State.NULL)
        bus.remove_signal_watch()

    if error is not None:
        raise error
