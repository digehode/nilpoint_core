"""Test settings for nilpoint - extends main settings with test-specific overrides."""

from nilpoint_harness.settings import *  # noqa: F403,F401

# Use simple staticfiles storage for tests to avoid manifest issues
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
