"""
Tests for HtmxTriggerResponse log collection and header serialisation.

The ephemeral on-screen log collects messages per response and ships them in
the HX-Trigger header as ``nilpoint_log: {"messages": [...]}``
"""

import json

from django.test import SimpleTestCase

from nilpoint.views import HtmxTriggerResponse


class HtmxTriggerResponseLogTests(SimpleTestCase):
    """The nilpoint_log trigger collects messages per response."""

    def test_single_message_is_serialised_under_messages(self):
        response = HtmxTriggerResponse()
        response.add_log_item("Took the widget")
        response.serialize_htmx_headers()
        triggers = json.loads(response["HX-Trigger"])
        self.assertEqual(
            triggers["nilpoint_log"],
            {"messages": [{"message": "Took the widget", "level": "success"}]},
        )

    def test_multiple_messages_are_all_collected(self):
        response = HtmxTriggerResponse()
        response.add_log_item("first", level="info")
        response.add_log_item("second", level="error")
        response.serialize_htmx_headers()
        triggers = json.loads(response["HX-Trigger"])
        self.assertEqual(
            triggers["nilpoint_log"]["messages"],
            [
                {"message": "first", "level": "info"},
                {"message": "second", "level": "error"},
            ],
        )

    def test_log_is_isolated_between_responses(self):
        """Messages collected on one response don't leak into a later one."""
        first = HtmxTriggerResponse()
        first.add_log_item("from the first response")
        first.serialize_htmx_headers()
        self.assertIn("nilpoint_log", json.loads(first["HX-Trigger"]))

        second = HtmxTriggerResponse()
        second.serialize_htmx_headers()
        self.assertNotIn("nilpoint_log", second.get("HX-Trigger", ""))

    def test_no_log_key_when_nothing_logged(self):
        response = HtmxTriggerResponse()
        response.serialize_htmx_headers()
        self.assertEqual(response.get("HX-Trigger", ""), "")
