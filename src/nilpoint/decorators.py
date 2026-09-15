# nilpoint/decorators.py

import functools
from nilpoint.exceptions import InvalidReleaseStateError, MigrationFailedError


def release_step(target_release: int):
    """
    Decorator for game update methods.

    Usage:
        @release_step(2)
        def add_inventory_system(self):
            ...
            return True
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            expected_current_release = target_release - 1

            # State check
            if self.release != expected_current_release:
                raise InvalidReleaseStateError(
                    f"Cannot execute '{func.__name__}'. {self.__class__.__name__} item '{self}' is at release {self.release}, "
                    f"but this step requires release {expected_current_release}."
                )

            # Execution & Error handling
            try:
                result = func(self, *args, **kwargs)
            except Exception as exc:
                raise MigrationFailedError(
                    f"Migration step '{func.__name__}' (v{target_release}) on '{self}' "
                    f"raised an exception: {exc}"
                ) from exc

            if result is not True:
                raise MigrationFailedError(
                    f"Migration step '{func.__name__}' (v{target_release}) on '{self}' failed. "
                    f"Expected 'True', received '{result!r}'."
                )

            # Save state
            self.release = target_release
            self.save()
            return True

        # Store the target version on the wrapper function for lookup
        wrapper._target_release = target_release
        return wrapper

    return decorator
