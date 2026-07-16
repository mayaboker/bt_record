from enum import IntEnum


class RecordExitCode(IntEnum):
    SUCCESS = 0
    STARTUP_ERROR = 1
    CLI_USAGE_ERROR = 2
    DEVICE_NOT_FOUND = 3
    GSTREAMER_DEPENDENCY_MISSING = 4


class RecordStartupError(RuntimeError):
    def __init__(
        self,
        message: str,
        exit_code: RecordExitCode = RecordExitCode.STARTUP_ERROR,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
