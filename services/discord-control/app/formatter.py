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
