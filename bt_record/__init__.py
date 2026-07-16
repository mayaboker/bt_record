from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("bt-record")
except PackageNotFoundError:
    __version__ = "0.0.0"


DEST_STREAM_IP = "127.0.0.1"
