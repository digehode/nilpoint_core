"""The demo game's dispatch view.

Almost nothing is needed here: every handler, the landing page included,
is inherited from `NilpointGameBasic`.  The demo uses the default landing
as-is, which is enough for most games.  A game that needs extra UI points
`landing_partial` at a partial of its own - `handle_landing` picks it up
via `_value_from_subclass_or_default`, so no handler code is copied or
re-implemented.  The line is left commented as the pointer to that door.
"""

from nilpoint.views import NilpointGameBasic


class DemoGameView(NilpointGameBasic):
    """The demo needs no handler overrides; see the module docstring."""

    # A game with extra landing UI would set, e.g.:
    # landing_partial = "demo/landing.jinja2#landing"
