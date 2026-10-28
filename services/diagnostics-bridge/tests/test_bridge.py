"""Regression and leak-resistance tests; uses unittest from the stdlib."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge


class TestDiagnosticsBridge(unittest.TestCase):
    def test_report_only_has_allowed_fields_even_when_responses_contain_secrets(self):
        def response(url):
            if "stats/activity" in url:
                return {"processed": 5, "approved": 1, "would_approve": 3,
                        "avg_edge_directional": 0.09, "api_key": "TOPSECRET"}
            if "/queue?" in url:
                return {"active": 2, "by_state": {"QUEUED": 2, "FAILED": 1},
                        "entries": [{"ticker": "PRIVATE-MARKET", "secret": "TOPSECRET"}]}
            return {"status": "ok", "dry_run": True, "postgres": True,
                    "kalshi_reachable": True, "credentials_configured": True,
                    "markets_scored": 120, "tier3_candidates": 8,
                    "environment": "demo", "token": "TOPSECRET"}
        with patch.object(bridge, "_get_safe", side_effect=response), patch.object(bridge, "_probe_ok", return_value=True):
            report = bridge.build_report()
        serialized = json.dumps(report)
        self.assertNotIn("TOPSECRET", serialized)
        self.assertNotIn("PRIVATE-MARKET", serialized)
        self.assertEqual(report["activity_last_60m"]["processed"], 5)
        self.assertEqual(report["risk"]["dry_run"], True)
        self.assertEqual(report["queue"]["by_state"]["queued"], 2)

    def test_invalid_and_missing_metrics_do_not_turn_into_fake_zeros(self):
        with patch.object(bridge, "_get_safe", return_value={"status": "degraded", "processed": True,
                                                      "avg_edge_directional": float("nan")}), patch.object(bridge, "_probe_ok", return_value=False):
            r = bridge.build_report()
        self.assertIsNone(r["activity_last_60m"]["processed"])
        self.assertIsNone(r["activity_last_60m"]["avg_claimed_gross_edge"])
        self.assertFalse(r["services"]["prediction_api"]["healthy"])

    def test_public_destination_is_never_written(self):
        with patch.object(bridge, "_request_json", return_value={"private": False, "full_name": "owner/public"}) as req:
            with self.assertRaisesRegex(ValueError, "not confirmed private"):
                bridge.publish_private({"hello": "world"}, "owner/public", "secret")
        self.assertEqual(req.call_count, 1)

    def test_private_repo_creates_report_without_mutating_source(self):
        calls = []
        def req(url, **kw):
            calls.append((url, kw))
            if url.endswith("/repos/owner/private"):
                return {"private": True, "full_name": "owner/private"}
            if kw.get("method") == "PUT":
                return {"content": {"name": "latest.json"}}
            raise HTTPError(url, 404, "Not Found", {}, None)
        with patch.object(bridge, "_request_json", side_effect=req):
            bridge.publish_private({"services": {}}, "owner/private", "secret")
        put = [k for _,k in calls if k.get("method")=="PUT"]
        self.assertEqual(len(put), 1)
        self.assertNotIn("sha", put[0]["data"])
        self.assertEqual(json.loads(__import__("base64").b64decode(put[0]["data"]["content"]))["services"], {})

    def test_unexpected_repo_name_and_bad_path_rejected(self):
        with self.assertRaises(ValueError):
            bridge._github_repo("owner/repo/../../x")
        with patch.object(bridge, "_request_json", return_value={"private": True, "full_name": "other/repo"}) as request:
            with self.assertRaisesRegex(ValueError, "Unexpected repository identity"):
                bridge.publish_private({}, "owner/repo", "secret")
            self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
