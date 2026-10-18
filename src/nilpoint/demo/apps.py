from django.apps import AppConfig


class DemoConfig(AppConfig):
    """The demo game ships inside the nilpoint package.

    `label` is set explicitly because the default for "nilpoint.demo"
    would be "demo", which is a common app name in host projects; the
    label is what migrations and the archetype strings in
    NILPOINT_SETTINGS refer to ("nilpoint_demo.DemoPC").
    """

    name = "nilpoint.demo"
    label = "nilpoint_demo"
