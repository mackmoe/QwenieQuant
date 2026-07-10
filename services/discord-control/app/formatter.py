"""
Converts platform API responses into concise Discord-formatted strings.

Discord enforces a 2000-character message limit. Long fields (e.g. LLM
reasoning) are truncated to keep responses readable. No business logic
lives here — only string construction.
"""

_MAX_REASONING = 300
_MAX_OBSERVATIONS = 5

UNAUTHORIZED_MESSAGE = "❌ You are not authorized to use this command."


def _icon(ok: bool) -> str:
    return "✅" if ok else "❌"


def format_status(health: dict) -> str:
    pred = health.get("prediction_api", {})
    learn = health.get("learning_engine", {})
    reflect = health.get("reflection_engine", {})
    ollama = health.get("ollama", {})
    searxng = health.get("searxng", {})

    pred_ok = pred.get("status") == "ok"
    learn_ok = learn.get("status") == "ok"
    pg_ok = bool(learn.get("postgres", False))
    reflect_ok = reflect.get("status") == "ok"
    ollama_ok = bool(ollama.get("reachable", False))
    searxng_ok = bool(searxng.get("reachable", False))

    return "\n".join([
        "**Platform Status**",
        f"{_icon(pred_ok)} Prediction API — {pred.get('status', 'unreachable')}",
        f"{_icon(learn_ok)} Learning Engine — {learn.get('status', 'unreachable')}",
        f"{_icon(reflect_ok)} Reflection Engine — {reflect.get('status', 'unreachable')}",
        f"{_icon(pg_ok)} PostgreSQL — {'ok' if pg_ok else 'unreachable'}",
        f"{_icon(ollama_ok)} Ollama — {'reachable' if ollama_ok else 'unreachable'}",
        f"{_icon(searxng_ok)} SearXNG — {'reachable' if searxng_ok else 'unreachable'}",
    ])


def format_prediction(result: dict) -> str:
    if "error" in result:
        return f"❌ Prediction failed: {result['error']}"

    conf_pct = f"{result.get('confidence', 0) * 100:.0f}%"
    reasoning = result.get("reasoning", "")
    if len(reasoning) > _MAX_REASONING:
        reasoning = reasoning[:_MAX_REASONING - 3] + "..."

    lines = [
        "**Prediction**",
        f"**{result.get('prediction', '?')}** (confidence: {conf_pct})",
    ]
    if reasoning:
        lines += ["", f"_{reasoning}_"]
    return "\n".join(lines)


def _format_analysis_diagnostics(diagnostics: dict) -> list[str]:
    """Render up to 3 concise diagnostic highlight lines from diagnostics dict."""
    lines: list[str] = []

    # Strongest / weakest category
    cats = [
        c for c in diagnostics.get("category_performance", [])
        if c.get("accuracy") is not None and c.get("resolved", 0) >= 3
    ]
    if len(cats) >= 2:
        best = max(cats, key=lambda c: c["accuracy"])
        worst = min(cats, key=lambda c: c["accuracy"])
        if best["category"] != worst["category"]:
            lines.append(
                f"Best category: {best['category']} ({best['accuracy'] * 100:.0f}%)"
                f"  |  Worst: {worst['category']} ({worst['accuracy'] * 100:.0f}%)"
            )

    # YES vs NO
    yn = diagnostics.get("yes_no_analysis")
    if yn:
        ya = yn.get("yes", {}).get("accuracy")
        na = yn.get("no", {}).get("accuracy")
        yr = yn.get("yes", {}).get("resolved", 0)
        nr = yn.get("no", {}).get("resolved", 0)
        if ya is not None and na is not None and yr >= 3 and nr >= 3:
            lines.append(
                f"YES accuracy: {ya * 100:.0f}%  |  NO accuracy: {na * 100:.0f}%"
            )

    # SearXNG effectiveness
    se = diagnostics.get("search_effectiveness")
    if se and se.get("accuracy_delta") is not None:
        if se.get("with_search_count", 0) >= 3 and se.get("without_search_count", 0) >= 3:
            delta = se["accuracy_delta"]
            direction = "+" if delta >= 0 else ""
            lines.append(
                f"SearXNG impact: {direction}{delta * 100:.0f}pp accuracy delta"
                f" ({se.get('with_search_count', 0)} with"
                f" vs {se.get('without_search_count', 0)} without search)"
            )

    return lines[:3]


def format_analysis(summary: dict) -> str:
    if "error" in summary:
        return f"❌ Analysis failed: {summary['error']}"

    acc = summary.get("accuracy")
    acc_str = f"{acc * 100:.1f}%" if acc is not None else "N/A"
    conf = summary.get("average_confidence")
    conf_str = f"{conf:.2f}" if conf is not None else "N/A"
    time_range = summary.get("time_range", "all time")

    lines = [
        "**Learning Analysis**",
        f"Period: {time_range}",
        f"Predictions: {summary.get('predictions_analyzed', 0)}"
        f"  |  Outcomes: {summary.get('outcomes_available', 0)}",
        f"Accuracy: {acc_str}  |  Confidence: {conf_str}",
    ]

    observations = summary.get("observations", [])
    if observations:
        lines.append("")
        lines.append("**Observations**")
        for obs in observations[:_MAX_OBSERVATIONS]:
            lines.append(f"• {obs}")

    diagnostics = summary.get("diagnostics")
    if isinstance(diagnostics, dict):
        diag_lines = _format_analysis_diagnostics(diagnostics)
        if diag_lines:
            lines.append("")
            lines.append("**Diagnostics**")
            for dl in diag_lines:
                lines.append(f"• {dl}")

    return "\n".join(lines)


def format_reflection(reflection: dict) -> str:
    if "error" in reflection:
        return f"❌ Reflection failed: {reflection['error']}"

    sections = ["**Reflection**"]

    def _append_section(title: str, items: list[str]) -> None:
        if items:
            sections.append(f"\n**{title}**")
            for item in items:
                sections.append(f"• {item}")

    _append_section("Strengths", reflection.get("strengths", []))
    _append_section("Weaknesses", reflection.get("weaknesses", []))
    _append_section("Patterns", reflection.get("patterns", []))
    _append_section("Recommendations", reflection.get("recommendations", []))

    return "\n".join(sections)


def format_error(message: str) -> str:
    return f"❌ {message}"


def format_scan(result: dict) -> str:
    if "error" in result:
        return "❌ Opportunity Engine unavailable.\nUnable to start market scan."

    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
    markets = result.get("markets_scored", 0)
    tier_counts = result.get("tier_counts", {})
    tier3 = tier_counts.get("3", 0)
    duration_ms = result.get("duration_ms", 0)

    return "\n".join([
        "✅ Market scan complete.",
        "The Opportunity Engine has completed a new market discovery cycle.",
        "",
        f"**Markets Scored:** {markets:,}",
        f"**Tier 3 Candidates:** {tier3}",
        f"**Duration:** {duration_ms / 1000:.1f}s",
        f"**Completed:** {ts}",
    ])


_MAX_TITLE = 60
_MAX_TICKER = 28
_MARKETS_DEFAULT_LIMIT = 10
_DISCORD_MSG_LIMIT = 1900  # stay clear of Discord's 2000-char hard limit


# ---------------------------------------------------------------------------
# Dashboard helpers (SPEC-023)
# ---------------------------------------------------------------------------


def _time_ago(dt_str: str | None) -> str:
    if not dt_str:
        return "Unknown"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        secs = int((datetime.now(timezone.utc) - dt).total_seconds())
        if secs < 0:
            return "Just now"
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return "Unknown"


def _fmt_hhmm(dt_str: str | None) -> str:
    if not dt_str:
        return "??:??"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except Exception:
        return "??:??"


def _extract_model(analysis: dict) -> str:
    breakdown = analysis.get("model_breakdown", {})
    if breakdown:
        return max(breakdown, key=breakdown.get)
    return "qwen3:8b"


def format_workflow(
    oe_health: dict,
    pq_health: dict,
    pq_stats: dict,
    le_health: dict,
    re_health: dict,
    pred_health: dict,
) -> str:
    oe_ok = "error" not in oe_health and oe_health.get("status") == "ok"
    pq_ok = "error" not in pq_health
    le_ok = "error" not in le_health and le_health.get("status") == "ok"
    re_ok = "error" not in re_health and re_health.get("status") == "ok"
    pred_ok = "error" not in pred_health and pred_health.get("status") == "ok"

    all_ok = oe_ok and pq_ok and le_ok and re_ok and pred_ok
    status_icon = "✅ Running" if all_ok else "⚠️ Degraded"

    by_state = pq_stats.get("by_state", {}) if "error" not in pq_stats else {}
    queued = by_state.get("QUEUED", 0)
    in_progress = by_state.get("IN_PROGRESS", 0)
    completed = by_state.get("COMPLETED", 0)
    failed = by_state.get("FAILED", 0)

    markets = f"{oe_health.get('markets_scored', 0):,}" if oe_ok else "Unavailable"
    tier3 = oe_health.get("tier3_candidates", 0) if oe_ok else "—"
    last_scan = _time_ago(oe_health.get("last_scan")) if oe_ok else "Unknown"

    active_entries = pq_health.get("active_entries", 0) if pq_ok else 0
    in_prog_display = "Yes" if (in_progress > 0 or active_entries > 0) else "No"

    le_icon = "✅" if le_ok else "❌"
    re_icon = "✅" if re_ok else "❌"
    pred_icon = "✅" if pred_ok else "❌"

    return "\n".join([
        "**Prediction AI Platform**",
        "",
        f"**Status:** {status_icon}",
        "",
        f"**Markets Scanned:** {markets}",
        f"**Tier 3 Candidates:** {tier3}",
        f"**Queued:** {queued}",
        f"**In Progress:** {in_prog_display}",
        f"**Completed:** {completed:,}",
        f"**Failed:** {failed}",
        "",
        f"**Prediction API:** {pred_icon}  **Learning:** {le_icon}  **Reflection:** {re_icon}",
        "",
        f"**Last Scan:** {last_scan}",
    ])


def format_performance(analysis: dict, settings) -> str:
    calibration = "Active" if getattr(settings, "confidence_calibration_enabled", True) else "Disabled"

    if "error" in analysis:
        return "\n".join([
            "**Platform Performance**",
            "",
            "❌ Learning Engine unavailable.",
            "",
            f"**Calibration:** {calibration}",
        ])

    predictions_analyzed = analysis.get("predictions_analyzed", 0)
    outcomes_available = analysis.get("outcomes_available", 0)
    open_count = max(0, predictions_analyzed - outcomes_available)
    accuracy = analysis.get("accuracy")
    avg_conf = analysis.get("average_confidence")

    if outcomes_available < 1:
        model = _extract_model(analysis)
        return "\n".join([
            "**Platform Performance**",
            "",
            "*Insufficient historical data.*",
            "",
            f"**Predictions:** {predictions_analyzed:,}",
            f"**Calibration:** {calibration}",
            f"**Model:** {model}",
        ])

    acc_str = f"{accuracy * 100:.1f}%" if accuracy is not None else "N/A"
    conf_str = f"{avg_conf * 100:.1f}%" if avg_conf is not None else "N/A"
    model = _extract_model(analysis)

    return "\n".join([
        "**Platform Performance**",
        "",
        f"**Accuracy:** {acc_str}",
        f"**Confidence:** {conf_str}",
        f"**Calibration:** {calibration}",
        f"**Resolved:** {outcomes_available:,}",
        f"**Open:** {open_count:,}",
        f"**Predictions:** {predictions_analyzed:,}",
        "",
        f"**Model:** {model}",
    ])


def _format_prediction_bullets(title: str) -> list[str]:
    """
    Parse a comma-separated prediction string into bullet lines.

    Each element must start with "yes " or "no " (case-insensitive).
    Elements that don't match the prefix are passed through as plain bullets.

    Input:  "yes Baltimore,no Detroit,yes Pittsburgh"
    Output: ["• YES — Baltimore", "• NO — Detroit", "• YES — Pittsburgh"]
    """
    lines = []
    for part in (p.strip() for p in title.split(",") if p.strip()):
        low = part.lower()
        if low.startswith("yes "):
            lines.append(f"• YES — {part[4:].strip()}")
        elif low.startswith("no "):
            lines.append(f"• NO — {part[3:].strip()}")
        else:
            lines.append(f"• {part}")
    return lines


def format_activity(completed: dict, oe_health: dict) -> str:
    events: list[tuple[str, str]] = []

    if "error" not in completed:
        for entry in completed.get("entries", []):
            ts = entry.get("last_updated") or entry.get("enqueue_time") or ""
            meta = entry.get("metadata", {})
            title = meta.get("title", "") or entry.get("ticker", "—")
            bullets = _format_prediction_bullets(title)
            bullet_block = "\n".join(bullets)
            line = f"`{_fmt_hhmm(ts)}` · Prediction\n{bullet_block}"
            events.append((ts, line))

    if "error" not in oe_health and oe_health.get("last_scan"):
        ts = oe_health["last_scan"]
        markets = oe_health.get("markets_scored", 0)
        events.append((ts, f"`{_fmt_hhmm(ts)}` · Opportunity Scan · {markets:,} markets"))

    if not events:
        msg = "❌ Prediction Queue unavailable." if "error" in completed else "*No recent activity.*"
        return f"**Recent Activity**\n\n{msg}"

    events.sort(key=lambda x: x[0], reverse=True)

    header = "**Recent Activity** *(newest first)*\n\n"
    body = ""
    for _, line in events:
        candidate = body + line + "\n"
        if len(header + candidate) > _DISCORD_MSG_LIMIT:
            break
        body += line + "\n"

    return header + body.rstrip()


def _fmt_uptime(seconds: float) -> str:
    s = int(seconds)
    if s < 0:
        return "0s"
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    hours = s // 3600
    mins = (s % 3600) // 60
    if hours < 24:
        return f"{hours}h {mins}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"


def format_brief(
    oe_health: dict,
    pq_health: dict,
    pq_stats: dict,
    analysis: dict,
    pred_health: dict,
    rm_health: dict,
    top_opps: dict,
    reflection: dict,
    settings,
    uptime_seconds: float,
) -> str:
    lines: list[str] = ["**Platform Brief**", ""]

    # --- Section 1: Platform ---
    oe_ok = "error" not in oe_health and oe_health.get("status") == "ok"
    pq_ok = "error" not in pq_health
    pred_ok = "error" not in pred_health and pred_health.get("status") == "ok"
    rm_ok = "error" not in rm_health

    all_ok = oe_ok and pq_ok and pred_ok and rm_ok
    status_icon = "🟢" if all_ok else "🔴"
    status_text = "Running" if all_ok else "Degraded"
    last_scan = oe_health.get("last_scan") if oe_ok else None

    lines += [
        f"{status_icon} **Platform**",
        f"Status: {status_text}",
        f"Uptime: {_fmt_uptime(uptime_seconds)}",
        f"Last Activity: {_time_ago(last_scan)}",
        "",
    ]

    # --- Section 2: Activity Summary ---
    by_state = pq_stats.get("by_state", {}) if "error" not in pq_stats else {}
    markets_scored = oe_health.get("markets_scored") if oe_ok else None
    completed = by_state.get("COMPLETED", 0)

    lines.append("📊 **Activity**")
    if markets_scored is not None:
        lines.append(f"Markets Scanned: {markets_scored:,}")
    lines.append(f"Predictions: {completed:,}")
    lines.append("")

    # --- Section 3: Performance Snapshot ---
    lines.append("📈 **Performance**")
    if "error" in analysis:
        lines += ["*Learning Engine unavailable.*", ""]
    elif analysis.get("outcomes_available", 0) < 1:
        lines += ["*Insufficient historical data.*", ""]
    else:
        acc = analysis.get("accuracy")
        conf = analysis.get("average_confidence")
        outcomes = analysis.get("outcomes_available", 0)
        preds = analysis.get("predictions_analyzed", 0)
        open_count = max(0, preds - outcomes)
        cal = "Active" if getattr(settings, "confidence_calibration_enabled", True) else "Disabled"
        lines += [
            f"Accuracy: {acc * 100:.1f}%" if acc is not None else "Accuracy: N/A",
            f"Confidence: {conf * 100:.1f}%" if conf is not None else "Confidence: N/A",
            f"Calibration: {cal}",
            f"Resolved: {outcomes:,}",
            f"Open: {open_count:,}",
            "",
        ]

    # --- Section 4: Best Opportunity ---
    lines += _render_best_opportunity(top_opps)
    lines.append("")

    # --- Section 5: Latest Reflection ---
    lines.append("🧠 **Reflection**")
    if "error" in reflection:
        lines += ["*No reflections available.*", ""]
    else:
        strengths = reflection.get("strengths", [])
        weaknesses = reflection.get("weaknesses", [])
        recommendations = reflection.get("recommendations", [])
        shown = False
        for s in strengths[:2]:
            lines.append(f"Strength: {s}")
            shown = True
        for w in weaknesses[:2]:
            lines.append(f"Weakness: {w}")
            shown = True
        if recommendations:
            lines.append(f"Recommendation: {recommendations[0]}")
            shown = True
        if not shown:
            lines.append("*No reflections available.*")
        lines.append("")

    # --- Section 6: Operator Attention ---
    attention: list[str] = []
    if "error" in pred_health or pred_health.get("status") != "ok":
        attention.append("Prediction API unavailable.")
    if "error" in oe_health or oe_health.get("status") != "ok":
        attention.append("Opportunity Engine unavailable.")
    if "error" in pq_health:
        attention.append("Prediction Queue unavailable.")
    if "error" in rm_health:
        attention.append("Risk Manager unavailable.")
    if rm_ok and not rm_health.get("kalshi_connector", True):
        attention.append("Kalshi authentication failed.")
    if oe_ok and oe_health.get("markets_scored", 0) == 0:
        attention.append("No market scans completed.")

    if attention:
        lines.append("🚨 **Operator Attention**")
        for item in attention:
            lines.append(f"• {item}")
    else:
        lines.append("✅ No operator action required.")

    # Trim trailing blank lines, enforce Discord limit
    while lines and lines[-1] == "":
        lines.pop()
    result = "\n".join(lines)
    if len(result) > _DISCORD_MSG_LIMIT:
        result = result[: _DISCORD_MSG_LIMIT - 3] + "..."
    return result


def _fmt_completed_at(dt_str: str | None) -> str:
    if not dt_str:
        return "Unknown"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return "Unknown"


def format_notification(
    oe_health: dict,
    pq_health: dict,
    pq_stats: dict,
    analysis: dict,
    pred_health: dict,
    rm_health: dict,
    top_opps: dict,
    reflection: dict,
    settings,
    workflow_num: int,
    trigger: str,
    completed_at: str | None = None,
) -> str:
    lines: list[str] = []

    # --- Header ---
    lines += [
        "🤖 **Prediction Platform Update**",
        f"Workflow #{workflow_num} | {trigger} | {_fmt_completed_at(completed_at)}",
        "",
    ]

    # --- Platform ---
    oe_ok = "error" not in oe_health and oe_health.get("status") == "ok"
    pq_ok = "error" not in pq_health
    pred_ok = "error" not in pred_health and pred_health.get("status") == "ok"
    rm_ok = "error" not in rm_health
    all_ok = oe_ok and pq_ok and pred_ok and rm_ok
    status_icon = "🟢" if all_ok else "🔴"
    status_text = "Healthy" if all_ok else "Degraded"
    last_scan = oe_health.get("last_scan") if oe_ok else None

    lines += [
        f"{status_icon} **Platform**",
        f"Status: {status_text}",
        f"Last Activity: {_time_ago(last_scan)}",
        "",
    ]

    # --- Activity ---
    by_state = pq_stats.get("by_state", {}) if "error" not in pq_stats else {}
    markets_scored = oe_health.get("markets_scored") if oe_ok else None
    queued = by_state.get("QUEUED", 0)
    completed_count = by_state.get("COMPLETED", 0)

    lines.append("📊 **Activity**")
    if markets_scored is not None:
        lines.append(f"Markets Scanned: {markets_scored:,}")
    lines.append(f"Queued: {queued}")
    lines.append(f"Predictions: {completed_count:,}")
    lines.append("")

    # --- Performance ---
    lines.append("📈 **Performance**")
    if "error" in analysis:
        lines += ["*Learning Engine unavailable.*", ""]
    elif analysis.get("outcomes_available", 0) < 1:
        lines += ["*Insufficient historical data.*", ""]
    else:
        acc = analysis.get("accuracy")
        conf = analysis.get("average_confidence")
        outcomes = analysis.get("outcomes_available", 0)
        preds = analysis.get("predictions_analyzed", 0)
        open_count = max(0, preds - outcomes)
        cal = "Active" if getattr(settings, "confidence_calibration_enabled", True) else "Disabled"
        model = _extract_model(analysis)
        lines += [
            f"Accuracy: {acc * 100:.1f}%" if acc is not None else "Accuracy: N/A",
            f"Confidence: {conf * 100:.1f}%" if conf is not None else "Confidence: N/A",
            f"Calibration: {cal}",
            f"Resolved: {outcomes:,}",
            f"Open: {open_count:,}",
            f"Model: {model}",
            "",
        ]

    # --- Best Opportunity ---
    lines += _render_best_opportunity(top_opps)
    lines.append("")

    # --- Learning Summary (observations only) ---
    if "error" not in analysis:
        observations = analysis.get("observations", [])
        if observations:
            lines.append("🧠 **Learning**")
            for obs in observations[:2]:
                lines.append(f"• {obs}")
            lines.append("")

    # --- Reflection Summary ---
    if "error" not in reflection:
        strengths = reflection.get("strengths", [])
        weaknesses = reflection.get("weaknesses", [])
        recommendations = reflection.get("recommendations", [])
        if strengths or weaknesses or recommendations:
            lines.append("💡 **Reflection**")
            for s in strengths[:2]:
                lines.append(f"Strength: {s}")
            for w in weaknesses[:2]:
                lines.append(f"Weakness: {w}")
            if recommendations:
                lines.append(f"Recommendation: {recommendations[0]}")
            lines.append("")

    # --- Operator Attention ---
    attention: list[str] = []
    if "error" in pred_health or pred_health.get("status") != "ok":
        attention.append("Prediction API unavailable.")
    if "error" in oe_health or oe_health.get("status") != "ok":
        attention.append("Opportunity Engine unavailable.")
    if "error" in pq_health:
        attention.append("Prediction Queue unavailable.")
    if "error" in rm_health:
        attention.append("Risk Manager unavailable.")
    if rm_ok and not rm_health.get("kalshi_connector", True):
        attention.append("Kalshi authentication failed.")
    if oe_ok and oe_health.get("markets_scored", 0) == 0:
        attention.append("No markets discovered in this scan.")

    if attention:
        lines.append("🚨 **Operator Attention**")
        for item in attention:
            lines.append(f"• {item}")
    else:
        lines.append("✅ No operator action required.")
    lines.append("")

    # --- Quick Commands ---
    lines += [
        "──────────────",
        "Quick Commands: `/brief`  `/markets`  `/scan`  `/performance`  `/activity`",
    ]

    # Trim trailing blank lines, enforce Discord limit
    while lines and lines[-1] == "":
        lines.pop()
    result = "\n".join(lines)
    if len(result) > _DISCORD_MSG_LIMIT:
        result = result[:_DISCORD_MSG_LIMIT - 3] + "..."
    return result


def _fmt_expiry(days_remaining) -> str:
    if days_remaining is None:
        return "Unknown"
    if days_remaining < 0:
        return "Expired"
    total_hours = int(days_remaining * 24)
    days = total_hours // 24
    hours = total_hours % 24
    if days > 0:
        return f"{days}d {hours}h" if hours else f"{days}d"
    return f"{hours}h" if hours else "< 1h"


def _parse_opportunity_title(raw_title: str) -> tuple[str, str]:
    """
    Parse a Kalshi market title that may be a comma-separated prediction string.

    For multi-outcome markets the Kalshi API sets title to a string like
    "yes Gabriel Moreno: 1+,yes Geraldo Perdom..." — we take only the first
    element (highest priority in the list) and strip the yes/no prefix.

    Returns (market_name, prediction) where prediction is "YES", "NO", or "Unknown".
    """
    first = raw_title.split(",")[0].strip()
    low = first.lower()
    if low.startswith("yes "):
        return first[4:].strip(), "YES"
    if low.startswith("no "):
        return first[3:].strip(), "NO"
    return first, "Unknown"


def _render_best_opportunity(top_opps: dict) -> list[str]:
    """Return formatted lines for the ⭐ Best Opportunity block."""
    lines = ["⭐ **Best Opportunity**"]
    if "error" not in top_opps and top_opps.get("markets"):
        top = top_opps["markets"][0]
        market_name, prediction = _parse_opportunity_title(top.get("title", "—"))
        title = _truncate(market_name, 50)
        score = top.get("priority_score", 0.0)
        meta = top.get("metadata", {})
        days_remaining = meta.get("days_remaining")
        spread = meta.get("spread")
        edge_str = f"{spread}¢" if spread is not None else "N/A"
        lines += [
            title,
            f"Prediction: {prediction}  Priority: {score:.1f}",
            f"Expected Edge: {edge_str}  Confidence: N/A",
        ]
        if days_remaining is not None:
            lines.append(f"Expires: {_fmt_expiry(days_remaining)}")
    else:
        lines.append("No qualifying opportunities discovered.")
    return lines


def format_run(result: dict) -> str:
    status = result.get("status", "error")

    if status == "busy":
        started = result.get("started_at", "unknown")
        elapsed = result.get("elapsed_seconds")
        elapsed_str = f"{elapsed}s" if elapsed is not None else "unknown"
        return "\n".join([
            "⚙️ **Workflow Already Running**",
            f"Started: {started}",
            f"Elapsed: {elapsed_str}",
            "",
            "*Try again when the current execution completes.*",
        ])

    if status == "empty":
        return "\n".join([
            "📭 **Workflow Run Complete**",
            "",
            "*The queue is empty — no markets are awaiting prediction.*",
        ])

    if status == "completed":
        pred = result.get("prediction", "Unknown")
        conf = result.get("confidence")
        conf_str = f"{conf * 100:.0f}%" if conf is not None else "N/A"
        risk_approved = result.get("risk_approved")
        risk_str = "✅ Approved" if risk_approved else "❌ Rejected"
        trade_status = result.get("trade_status", "—")
        duration_ms = result.get("duration_ms")
        dur_str = f"{duration_ms / 1000:.1f}s" if duration_ms is not None else "—"
        dry_run = result.get("dry_run", True)
        title = result.get("title") or result.get("ticker", "—")

        lines = [
            "✅ **Workflow Run Complete**",
            "",
            f"**Market:** {_truncate(title, 50)}",
            f"**Ticker:** {result.get('ticker', '—')}",
            f"**Prediction:** {pred}",
            f"**Confidence:** {conf_str}",
            f"**Risk:** {risk_str}",
            f"**Trade Status:** {trade_status}",
            f"**Duration:** {dur_str}",
        ]
        if dry_run:
            lines.append("*Dry-run mode — no real trades placed.*")
        return "\n".join(lines)

    if status == "skipped":
        title = result.get("title") or result.get("ticker", "—")
        reason = result.get("reason", "unknown")
        return "\n".join([
            "⏭️ **Workflow Run — Skipped**",
            "",
            f"**Market:** {_truncate(title, 50)}",
            f"**Reason:** {reason}",
            "",
            "*This market was skipped and marked complete. It will not be retried.*",
        ])

    if status == "requeued":
        pred = result.get("prediction")
        title = result.get("title") or result.get("ticker", "—")
        lines = [
            "🔄 **Workflow Run — Requeued**",
            "",
            f"**Market:** {_truncate(title, 50)}",
        ]
        if pred:
            conf = result.get("confidence")
            conf_str = f"{conf * 100:.0f}%" if conf is not None else "N/A"
            lines += [f"**Prediction:** {pred}", f"**Confidence:** {conf_str}"]
        lines += [
            "",
            "*A downstream service was unavailable. The market has been requeued for retry.*",
        ]
        return "\n".join(lines)

    if status == "failed":
        return "\n".join([
            "❌ **Workflow Run Failed**",
            "",
            f"**Market:** {result.get('ticker', '—')}",
            "",
            "*An unexpected error occurred. Check service logs for details.*",
        ])

    return f"❌ Workflow run returned an unexpected status: `{status}`"


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def format_hot(views: dict) -> str:
    """
    Render the Market Interest views from the Opportunity Engine's /views:
    🔥 most active, 📈 fastest rising, 💧 highest liquidity, ⭐ top MIS.
    """
    if "error" in views:
        return "❌ Opportunity Engine is currently unavailable."

    def _line(m: dict, stat: str) -> str:
        title = _truncate(m.get("title") or m.get("ticker", "—"), 45)
        cat = m.get("category")
        cat_str = f" · {cat}" if cat else ""
        return f"• {title}{cat_str}\n  {stat}"

    sections: list[str] = ["**Market Interest** *(latest scan)*"]

    active = views.get("most_active", [])
    if active:
        sections.append("\n🔥 **Most Active** *(volume gained this scan)*")
        for m in active:
            sections.append(_line(m, f"+{m.get('volume_delta', 0):,} contracts"))

    rising = views.get("fastest_rising", [])
    if rising:
        sections.append("\n📈 **Fastest Rising** *(mid-price climb)*")
        for m in rising:
            delta = m.get("price_delta") or 0
            sections.append(_line(m, f"+{delta:.1f}¢ mid price"))

    liquid = views.get("highest_liquidity", [])
    if liquid:
        sections.append("\n💧 **Highest Liquidity**")
        for m in liquid:
            oi = m.get("open_interest") or 0
            spread = m.get("spread")
            spread_str = f" · {spread}¢ spread" if spread is not None else ""
            sections.append(_line(m, f"{oi:,} open interest{spread_str}"))

    top = views.get("highest_opportunity", [])
    if top:
        sections.append("\n⭐ **Highest Opportunity** *(Market Interest Score)*")
        for m in top:
            score = m.get("priority_score", 0)
            rank_delta = m.get("rank_delta")
            move = ""
            if rank_delta is not None and rank_delta != 0:
                arrow = "▲" if rank_delta > 0 else "▼"
                move = f" · {arrow}{abs(rank_delta)} rank"
            sections.append(_line(m, f"MIS {score:.1f}{move}"))

    if len(sections) == 1:
        sections.append("\n*No momentum data yet — needs at least two scans.*")

    result = "\n".join(sections)
    if len(result) > _DISCORD_MSG_LIMIT:
        result = result[: _DISCORD_MSG_LIMIT - 3] + "..."
    return result


def format_markets(response: dict, category: str | None = None) -> str:
    if "error" in response:
        return "❌ Opportunity Engine is currently unavailable."

    markets = response.get("markets", [])
    total = response.get("total", 0)

    if category and category.lower() != "all":
        markets = [
            m for m in markets
            if category.lower() in m.get("title", "").lower()
            or category.lower() in m.get("ticker", "").lower()
        ]
        total = len(markets)
        markets = markets[:_MARKETS_DEFAULT_LIMIT]

    if not markets:
        return "No opportunities are currently available."

    header = "**Kalshi Market Opportunities**\n"
    entries: list[str] = []

    for i, m in enumerate(markets, start=1):
        title = _truncate(m.get("title", "—"), _MAX_TITLE)
        ticker = _truncate(m.get("ticker", "—"), _MAX_TICKER)
        score = m.get("priority_score", 0.0)
        tier = m.get("assigned_tier", "—")
        days = m.get("metadata", {}).get("days_remaining")
        expires = _fmt_expiry(days)

        entries.append(
            f"**{i}.** {title}\n"
            f"`{ticker}` · P:{score:.1f} T:{tier} · {expires}\n"
            f"{'─' * 20}"
        )

    # Fit as many entries as possible without exceeding the Discord limit.
    body = ""
    shown = 0
    for entry in entries:
        candidate = header + body + entry + "\n"
        footer = f"*Showing {shown + 1} of {total} opportunities.*"
        if len(candidate + footer) > _DISCORD_MSG_LIMIT:
            break
        body += entry + "\n"
        shown += 1

    footer = f"*Showing {shown} of {total} opportunities.*"
    return header + body + footer
