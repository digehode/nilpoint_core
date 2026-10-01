class NilpointException(Exception):
    """Base exception for the Nilpoint engine."""

    pass


class NilpointMissingSlugException(NilpointException):
    pass


class UnresolvableInteraction(NilpointException):
    """Raised when a stored interaction cannot be turned into a usable class.

    Covers both a dotted path that will not import and a holder type that
    cannot be matched to a model, so that games fail with a message naming
    the offending asset rather than with an import error from a template.
    """

    pass


class InvalidReleaseStateError(NilpointException, ValueError):
    """Raised when an update step is invoked on a game with an incorrect release version."""

    pass


class MigrationFailedError(NilpointException, RuntimeError):
    """Raised when an update step fails to return True or encounters an execution error."""

    pass
