"""The demo game's dispatch view.

Almost nothing is needed here: every handler is inherited from
`NilpointGameBasic`.  The one override is the landing page, done by
naming a different partial in the `landing_partial` class attribute -
`handle_landing` picks it up via `_value_from_subclass_or_default`, so
no handler code is copied or re-implemented.
"""

from nilpoint.views import NilpointGameBasic


class DemoGameView(NilpointGameBasic):
    landing_partial = "demo/landing.jinja2#landing"
