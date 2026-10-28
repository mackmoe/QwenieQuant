"""Privacy and cadence tests for the minute-level workflow snapshot."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge


class TestMinuteWorkflowReporting(unittest.TestCase):
    def test_one_minute_interval(self):
        self.assertEqual(bridge.INTERVAL_SECONDS, 60)

    def test_sanitizes_workflow_before_publishing(self):
        noisy = {
            "state": "ready",
            "queued_now": 7,
            "in_progress_now": 1,
            "secret": "DISCORD_TOKEN",
            "latest_recorded": {
                "completed_at_utc": "2026-10-28T02:42:00+00:00",
                "trade_status": "rejected",
                "side": "no",
                "confidence": 0.75,
                "gross_edge": -0.10,
                "estimated_net_ev": -0.12,
                "quoted_ask_cents": 70,
                "estimated_taker_fee_cents": 2,
                "risk_approved": False,
                "passed_all_risk_checks": False,
                "failed_risk_checks": ["confidence", "bankroll",
                                      "MY_SECRET_REASON", {"raw": "PRIVATE"}],
                "risk_reason": "SECRET PII URL",
                "market_id": "SECRET_TICKER",
                "order_id": "SECRET_ORDER",
            }
        }
        result = bridge._safe_workflow(noisy)
        self.assertTrue(result["available"])
        self.assertEqual(result["queued_now"], 7)
        self.assertEqual(result["in_progress_now"], 1)
        self.assertEqual(result["latest_recorded"]["failed_risk_checks"], ["confidence", "bankroll"])
        text = json.dumps(result)
        for secret in ("SECRET", "DISCORD_TOKEN", "PRIVATE"):
            self.assertNotIn(secret, text)

    def test_invalid_source_status_is_not_exposed(self):
        result = bridge._safe_workflow({
            "state": "broken", "queued_now": True,
            "latest_recorded": {"trade_status": {"secret": "TOKEN"},
                                "completed_at_utc": "bad timestamp",
                                "estimated_net_ev": float("nan"),
                                "failed_risk_checks": ["PASSWORD"]}
        })
        self.assertFalse(result["available"])
        self.assertIsNone(result["queued_now"])
        self.assertIsNone(result["latest_recorded"]["completed_at_utc"])
        self.assertIsNone(result["latest_recorded"]["trade_status"])
        self.assertIsNone(result["latest_recorded"]["estimated_net_ev"])
        self.assertEqual(result["latest_recorded"]["failed_risk_checks"], [])

    def test_build_report_includes_sanitized_workflow_not_private_identifiers(self):
        def response(url):
            if url == bridge.WORKFLOW_DIAGNOSTICS_URL:
                return {"state": "ready", "queued_now": 2, "in_progress_now": 1,
                        "latest_recorded": {"trade_status": "dry_run",
                                            "risk_approved": False,
                                            "failed_risk_checks": ["expected_value"],
                                            "market_id": "LEAK_IF_COPIED"}}
            return {"status": "ok", "environment": "demo"}
        with patch.object(bridge, "_get_safe", side_effect=response), \
             patch.object(bridge, "_probe_ok", return_value=True):
            report = bridge.build_report()
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["workflow"]["in_progress_now"], 1)
        self.assertEqual(report["workflow"]["latest_recorded"]["failed_risk_checks"], ["expected_value"])
        self.assertNotIn("LEAK_IF_COPIED", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
