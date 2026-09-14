class NilpointException(Exception):
    """Base exception for the Nilpoint engine."""

    pass


class NilpointMissingSlugException(NilpointException):
    pass


class InvalidReleaseStateError(NilpointException, ValueError):
    """Raised when an update step is invoked on a game with an incorrect release version."""

    pass


class MigrationFailedError(NilpointException, RuntimeError):
    """Raised when an update step fails to return True or encounters an execution error."""

    pass
