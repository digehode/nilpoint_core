# nilpoint/decorators.py
"""Custom decorators for Nilpoint

This module provides decorators used to manage stateful lifecycle updates and
incremental release migrations across Nilpoint model classes (e.g., Game, PlayerCharacter),
as well as decorators for view handlers.

Decorators:
    release_step(target_release):
        Marks a method as an incremental migration step to reach `target_release`.
        Enforces preconditions on the instance's current release version, inspects
        return values, handles migration exceptions, updates the instance's release
        version, and saves changes to the database upon successful execution.

        use like `@release_step(3)` to label a method as the update
        required from release 2 to 3

    require_http_methods(*methods):
        Decorator for view handlers that enforces allowed HTTP methods at runtime
        and records them on the function for template tag introspection.

        Usage:
            @require_http_methods("GET")
            def handle_panel(self, request): ...

            @require_http_methods("POST")
            def handle_take(self, request): ...

            @require_http_methods("GET", "POST")
            def handle_form(self, request): ...

"""

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

            if result is not True and result is not None:
                raise MigrationFailedError(
                    f"Migration step '{func.__name__}' (v{target_release}) on '{self}' failed. "
                    f"Expected 'True' or 'None', received '{result!r}'."
                )

            # Save state
            self.release = target_release
            self.save()
            return True

        # Store the target version on the wrapper function for lookup
        wrapper._target_release = target_release
        return wrapper

    return decorator


def require_http_methods(*methods):
    """Decorator to enforce HTTP method on view handlers and record allowed methods.

    Stores allowed methods on the function as `_nilpoint_allowed_methods`
    for use by template tags (e.g., `nilpoint_action_method`).

    Usage:
        @require_http_methods("GET")
        def handle_panel(self, request): ...

        @require_http_methods("POST")
        def handle_take(self, request): ...

        @require_http_methods("GET", "POST")
        def handle_form(self, request): ...

    Args:
        *methods: HTTP methods to allow (e.g., "GET", "POST")

    Returns:
        Decorated function with `_nilpoint_allowed_methods` attribute
    """
    allowed = {m.upper() for m in methods}

    def decorator(func):
        func._nilpoint_allowed_methods = allowed

        @functools.wraps(func)
        def wrapper(self, request, *args, **kwargs):
            if request.method not in allowed:
                from nilpoint.views import HtmxTriggerResponse

                return HtmxTriggerResponse(
                    content=f"Method {request.method} not allowed for {func.__name__}",
                    content_type="text/plain",
                )
            return func(self, request, *args, **kwargs)

        return wrapper

    return decorator


def _get_handler_methods(view_class, handler_name):
    """Get the allowed HTTP methods for a handler by name.

    Checks the view class's handler method for the `_nilpoint_allowed_methods`
    attribute. Falls back to checking the `_handlers` dict.

    Args:
        view_class: View class (e.g., NilpointGameBasic or subclass)
        handler_name: Action name (e.g., "take_item")

    Returns:
        Set of allowed HTTP methods (defaults to {"GET", "POST"} if unknown)
    """
    handler = getattr(view_class, handler_name, None)
    if handler and hasattr(handler, "_nilpoint_allowed_methods"):
        return handler._nilpoint_allowed_methods

    # Fallback: check _handlers dict for the method name and look it up
    method_name = view_class._handlers.get(handler_name)
    if method_name:
        handler = getattr(view_class, method_name, None)
        if handler and hasattr(handler, "_nilpoint_allowed_methods"):
            return handler._nilpoint_allowed_methods

    return {"GET", "POST"}  # Default: both allowed
