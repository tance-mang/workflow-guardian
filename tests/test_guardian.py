import json
import os
import unittest
from unittest.mock import patch

from workflow_guardian.__main__ import diagnose, report
from workflow_guardian.ai import suggestion
from workflow_guardian.schedule import minutes_since
from datetime import datetime, timezone


class GuardianTests(unittest.TestCase):
    def test_generic_classifications(self):
        for symptom, code in [
            ("No matching distribution found", "dependency"),
            ("HTTP Error 401", "credentials"),
            ("HTTP 503", "upstream"),
            ("error TS2304", "build"),
            ("TimeoutError", "network"),
            ("HTTP 429", "rate_limit"),
        ]:
            with self.subTest(symptom=symptom):
                self.assertEqual(diagnose("failure", symptom)[0], code)

    def test_blog_extension_is_opt_in(self):
        with patch.dict(os.environ, {"GUARDIAN_PROFILE": "generic"}):
            self.assertEqual(diagnose("failure", "BLOG_TOKEN is required")[0], "unknown")
        with patch.dict(os.environ, {"GUARDIAN_PROFILE": "blog"}):
            self.assertEqual(diagnose("failure", "BLOG_TOKEN is required")[0], "configuration")

    def test_report_keeps_raw_log_private(self):
        run = {"id": 123, "run_attempt": 2, "conclusion": "failure"}
        result = report("example/repo", run, "HTTP Error 429\nprivate-data", True)
        self.assertIn("rate_limit", result)
        self.assertIn("/attempts/2", result)
        self.assertNotIn("private-data", result)

    def test_unknown_when_logs_missing(self):
        self.assertEqual(diagnose("startup_failure", "")[0], "unknown")
        self.assertEqual(diagnose("timed_out", "")[0], "timeout")

    def test_ai_only_receives_allowed_signals(self):
        with patch.dict(os.environ, {"GUARDIAN_AI_KEY": "test", "GUARDIAN_AI_MODEL": "test"}):
            with patch("workflow_guardian.ai.urlopen") as urlopen:
                urlopen.return_value.__enter__.return_value.read.return_value = (
                    b'{"choices":[{"message":{"content":"Check provider"}}]}')
                self.assertEqual(suggestion("failure", "HTTP 503\nsecret-value", 2), "Check provider")
                sent = json.loads(urlopen.call_args.args[0].data)["messages"][1]["content"]
                self.assertIn("upstream_5xx", sent)
                self.assertIn('"recent_failure_count": 2', sent)
                self.assertNotIn("secret-value", sent)

    def test_schedule_age_uses_utc(self):
        now = datetime(2026, 11, 5, 3, 1, tzinfo=timezone.utc)
        self.assertEqual(minutes_since("2026-11-05T00:00:00Z", now), 181)
