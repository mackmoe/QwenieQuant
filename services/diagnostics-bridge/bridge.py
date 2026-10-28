"""Read-only, allowlisted QwenieQuant health snapshots sent to a PRIVATE GitHub repo.

No Discord, trading, database, account or raw-log access. The reporter is
opt-in and refuses to publish to a public destination repository.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request

LOG = logging.getLogger("diagnostics_bridge")
GITHUB_API = "https://api.github.com"
REPORT_PATH = "reports/qweniequant/latest.json"
MAX_RESPONSE_BYTES = 65536
INTERVAL_SECONDS = 60
SERVICE_ENDPOINTS = {
    "prediction_api": "http://prediction-api:8000/health",
    "learning_engine": "http://learning-engine:8001/health",
    "reflection_engine": "http://reflection-engine:8002/health",
    "opportunity_engine": "http://opportunity-engine:8005/health",
    "prediction_queue": "http://prediction-queue:8006/health",
    "risk_manager": "http://risk-manager:8004/health",
    "kalshi_connector": "http://kalshi-connector:8003/health",
    "ollama": "http://ollama:11434/api/tags",
    "searxng": "http://searxng:8080/healthz",
}
QUEUE_STATS_URL = "http://prediction-queue:8006/queue?limit=1"
ACTIVITY_URL = "http://prediction-queue:8006/stats/activity?window_minutes=60"
WORKFLOW_DIAGNOSTICS_URL = "http://prediction-queue:8006/stats/diagnostics"


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = request.build_opener(_NoRedirect)


def _request_json(url: str, *, token: str | None = None,
                  method: str = "GET", data: dict | None = None) -> dict:
    """Fetch only small JSON objects. Never log remote response bodies."""
    headers = {"Accept": "application/vnd.github+json"} if token else {"Accept": "application/json"}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    if data is not None:
        body = json.dumps(data, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=body, headers=headers, method=method)
    with OPENER.open(req, timeout=6) as resp:
        raw = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("Oversized JSON response")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Expected JSON object")
        return parsed


def _counter(data: dict, field: str) -> int | None:
    value = data.get(field)
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else None


def _fraction(data: dict, field: str) -> float | None:
    value = data.get(field)
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return round(float(value), 4) if -1 <= value <= 1 else None


def _boolean(data: dict, field: str) -> bool | None:
    value = data.get(field)
    return value if type(value) is bool else None


SAFE_RISK_CHECKS = frozenset({
    "confidence", "expected_value", "edge", "open_positions", "daily_loss",
    "bankroll", "consecutive_losses", "executable_quote", "direction_bias",
})
TRADE_STATUSES = frozenset({"rejected", "dry_run", "executed", "execution_failed", "unknown"})


def _safe_workflow(data: dict) -> dict:
    """Resanitize even trusted internal API responses before private publish."""
    latest = data.get("latest_recorded")
    if not isinstance(latest, dict):
        latest = None
    clean = None
    if latest is not None:
        reasons = latest.get("failed_risk_checks")
        reasons = (
            [v for v in reasons if type(v) is str and v in SAFE_RISK_CHECKS][:9]
            if isinstance(reasons, list) else None
        )
        status = latest.get("trade_status")
        timestamp = latest.get("completed_at_utc")
        if isinstance(timestamp, str) and len(timestamp) <= 40:
            try:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                timestamp = parsed.astimezone(timezone.utc).isoformat(timespec="seconds") if parsed.tzinfo else None
            except ValueError:
                timestamp = None
        else:
            timestamp = None
        clean = {
            "completed_at_utc": timestamp,
            "trade_status": status if isinstance(status, str) and status in TRADE_STATUSES else None,
            "side": latest.get("side") if isinstance(latest.get("side"), str) and latest.get("side") in ("yes", "no") else None,
            "confidence": _fraction(latest, "confidence"),
            "gross_edge": _fraction(latest, "gross_edge"),
            "estimated_net_ev": _fraction(latest, "estimated_net_ev"),
            "quoted_ask_cents": _counter(latest, "quoted_ask_cents"),
            "estimated_taker_fee_cents": _counter(latest, "estimated_taker_fee_cents"),
            "risk_approved": _boolean(latest, "risk_approved"),
            "passed_all_risk_checks": _boolean(latest, "passed_all_risk_checks"),
            "failed_risk_checks": reasons,
            "dry_run": _boolean(latest, "dry_run"),
        }
    return {
        "available": data.get("state") == "ready",
        "queued_now": _counter(data, "queued_now"),
        "in_progress_now": _counter(data, "in_progress_now"),
        "latest_recorded": clean,
    }


def _get_safe(url: str) -> dict:
    try:
        return _request_json(url)
    except (error.URLError, OSError, ValueError, TimeoutError):
        return {}


def _probe_ok(url: str) -> bool:
    """Status-only probe for non-JSON services such as SearXNG."""
    try:
        with OPENER.open(request.Request(url, method="GET"), timeout=6) as resp:
            return 200 <= resp.status < 300
    except (error.URLError, OSError, ValueError, TimeoutError):
        return False


def build_report() -> dict:
    """Construct a report from strictly allowlisted fields, never arbitrary logs."""
    raw = {name: _get_safe(url) for name, url in SERVICE_ENDPOINTS.items() if name != "searxng"}
    services = {}
    for name, data in raw.items():
        # Ollama does not follow the platform health response shape.
        healthy = bool(data) if name == "ollama" else data.get("status") == "ok"
        services[name] = {"healthy": healthy}

    services["searxng"] = {"healthy": _probe_ok(SERVICE_ENDPOINTS["searxng"])}

    queue = _get_safe(QUEUE_STATS_URL)
    activity = _get_safe(ACTIVITY_URL)
    by_state = queue.get("by_state") if isinstance(queue.get("by_state"), dict) else {}
    state_counts = {state.lower(): _counter(by_state, state) for state in
                    ("QUEUED", "IN_PROGRESS", "COMPLETED", "FAILED")}
    kalshi = raw["kalshi_connector"]
    risk = raw["risk_manager"]
    opportunity = raw["opportunity_engine"]
    workflow = _get_safe(WORKFLOW_DIAGNOSTICS_URL)

    return {
        "schema_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "services": services,
        "workflow": _safe_workflow(workflow),
        "queue": {
            "active": _counter(queue, "active"),
            "by_state": state_counts,
        },
        "activity_last_60m": {
            "processed": _counter(activity, "processed"),
            "approved": _counter(activity, "approved"),
            "would_approve": _counter(activity, "would_approve"),
            "directional": _counter(activity, "directional"),
            "searched": _counter(activity, "searched"),
            "avg_claimed_gross_edge": _fraction(activity, "avg_edge_directional"),
            "oldest_queued_minutes": _counter(activity, "oldest_queued_minutes"),
        },
        "risk": {
            "dry_run": _boolean(risk, "dry_run"),
            "postgres_reachable": _boolean(risk, "postgres"),
        },
        "kalshi": {
            "api_reachable": _boolean(kalshi, "kalshi_reachable"),
            "credentials_configured": _boolean(kalshi, "credentials_configured"),
            "environment": kalshi.get("environment") if kalshi.get("environment") in ("production", "demo") else None,
        },
        "opportunities": {
            "markets_scored": _counter(opportunity, "markets_scored"),
            "tier3_candidates": _counter(opportunity, "tier3_candidates"),
        },
    }


def _github_repo(repo: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("DIAG_PRIVATE_REPO must be owner/repo")
    return f"{GITHUB_API}/repos/{repo}"


def publish_private(report: dict, repo: str, token: str) -> None:
    if not token.strip():
        raise ValueError("Missing GitHub token")
    base = _github_repo(repo)
    metadata = _request_json(base, token=token)
    if metadata.get("private") is not True:
        raise ValueError("Destination is not confirmed private; refusing to publish")
    if metadata.get("full_name", "").lower() != repo.lower():
        raise ValueError("Unexpected repository identity; refusing to publish")

    endpoint = base + "/contents/" + REPORT_PATH
    try:
        old = _request_json(endpoint, token=token)
        sha = old.get("sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Invalid current report blob SHA")
    except error.HTTPError as exc:
        if exc.code != 404:
            raise
        sha = None

    encoded = base64.b64encode((json.dumps(report, sort_keys=True, indent=2) + "\n").encode()).decode()
    payload = {"message": "Update sanitized QwenieQuant diagnostics", "content": encoded}
    if sha is not None:
        payload["sha"] = sha
    _request_json(endpoint, token=token, method="PUT", data=payload)


def run_once(repo: str, token_file: Path) -> None:
    # Validate that a private, writable target exists BEFORE probing services.
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("Empty diagnostics token file")
    _github_repo(repo)
    metadata = _request_json(_github_repo(repo), token=token)
    if metadata.get("private") is not True or metadata.get("full_name", "").lower() != repo.lower():
        raise ValueError("Private diagnostics destination not verified")
    report = build_report()
    publish_private(report, repo, token)
    healthy = sum(int(x["healthy"]) for x in report["services"].values())
    LOG.info("Published sanitized diagnostics; %d/%d endpoints healthy", healthy, len(report["services"]))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    repo = os.environ.get("DIAG_PRIVATE_REPO", "")
    token_file = Path(os.environ.get("DIAG_GITHUB_TOKEN_FILE", "/run/secrets/github_token"))
    if not repo:
        raise SystemExit("DIAG_PRIVATE_REPO is required (must be a separate private repository)")
    if not token_file.is_file():
        raise SystemExit("GitHub token file missing; see docs/DIAGNOSTICS_BRIDGE.md")
    while True:
        try:
            run_once(repo, token_file)
        except (error.URLError, OSError, ValueError, TimeoutError) as exc:
            # Do not print exception strings: they may contain a URL or server details.
            LOG.error("Diagnostic publish failed (%s)", type(exc).__name__)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
