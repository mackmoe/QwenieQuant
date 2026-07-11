"""Tests for prompt_builder — especially the self-knowledge (history) sections."""

from app.models import PredictionRequest
from app.prompt_builder import build_prediction_prompt


def _request(**overrides) -> PredictionRequest:
    defaults = dict(
        question="Will Shane Bieber record 4 or more strikeouts?",
        category="Sports",
        options=["Yes", "No"],
        market_id="KXMLBKS-26JUL10-X",
    )
    defaults.update(overrides)
    return PredictionRequest(**defaults)


def _history(**overrides) -> dict:
    defaults = dict(
        category_stats={"label": "Sports", "resolved": 210, "accuracy": 0.52},
        series_stats={"label": "KXMLBKS", "resolved": 45, "accuracy": 0.64},
        lessons=["Average confidence is 0.43, which is low."],
        exemplars=[
            {"question": "Will X win the match?", "prediction": "No", "confidence": 0.72},
        ],
    )
    defaults.update(overrides)
    return defaults


# --- backward compatibility ---


def test_no_history_prompt_unchanged():
    _, user_no_hist = build_prediction_prompt(_request())
    _, user_none = build_prediction_prompt(_request(), history=None)
    assert user_no_hist == user_none
    assert "Track Record" not in user_no_hist


def test_empty_history_renders_nothing():
    empty = {"category_stats": None, "series_stats": None, "lessons": [], "exemplars": []}
    _, user = build_prediction_prompt(_request(), history=empty)
    assert "Track Record" not in user
    assert "Lessons" not in user


# --- track record ---


def test_track_record_renders_category_and_series():
    _, user = build_prediction_prompt(_request(), history=_history())
    assert "Your Track Record (last 30 days):" in user
    assert "Sports: 52% correct over 210 resolved" in user
    assert "KXMLBKS: 64% correct over 45 resolved" in user


def test_strong_series_marked_as_strength():
    _, user = build_prediction_prompt(_request(), history=_history())
    assert "a proven strength" in user


def test_weak_series_gets_confidence_warning():
    hist = _history(series_stats={"label": "KXMLBHR", "resolved": 120, "accuracy": 0.38})
    _, user = build_prediction_prompt(_request(), history=hist)
    assert "your record here is poor; lower your confidence" in user


# --- lessons and exemplars ---


def test_lessons_rendered_capped_at_three():
    hist = _history(lessons=[f"lesson {i}" for i in range(5)])
    _, user = build_prediction_prompt(_request(), history=hist)
    assert "Lessons from your recent performance reviews:" in user
    assert "lesson 2" in user
    assert "lesson 3" not in user


def test_exemplars_rendered_with_confidence():
    _, user = build_prediction_prompt(_request(), history=_history())
    assert "Examples of your past correct calls:" in user
    assert 'Q: "Will X win the match?" -> No (confidence 0.72)' in user


def test_long_exemplar_question_truncated():
    hist = _history(exemplars=[
        {"question": "X" * 300, "prediction": "Yes", "confidence": 0.60},
    ])
    _, user = build_prediction_prompt(_request(), history=hist)
    assert "X" * 121 not in user


# --- system prompt guidance ---


def test_system_prompt_teaches_track_record_use():
    system, _ = build_prediction_prompt(_request(), history=_history())
    assert "Your Track Record" in system
    assert "Lessons" in system


# --- evidence + history coexist ---


def test_history_renders_alongside_evidence():
    from app.searxng import SearchResult
    evidence = [SearchResult(title="t", snippet="Bieber struck out 8 last start", url="u")]
    _, user = build_prediction_prompt(_request(), evidence, history=_history())
    assert "Current Evidence:" in user
    assert "Your Track Record" in user
    # history comes after evidence, before the final instruction
    assert user.index("Current Evidence") < user.index("Your Track Record")
    assert user.strip().endswith("respond with JSON only.")
