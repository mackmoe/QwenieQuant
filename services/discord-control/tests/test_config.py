import os

import pytest
from pydantic import ValidationError


def _make_settings(allowed_user_ids: str, **extra_env: str):
    """Build a Settings instance with the given ALLOWED_USER_IDS value."""
    env = {
        "DISCORD_BOT_TOKEN": "test-token",
        "DISCORD_GUILD_ID": "123456789",
        "ALLOWED_USER_IDS": allowed_user_ids,
        **extra_env,
    }
    # Isolate from any real .env file by pointing at a non-existent one.
    from pydantic_settings import BaseSettings

    from app.config import Settings

    with pytest.MonkeyPatch().context() as mp:
        for k, v in env.items():
            mp.setenv(k, v)
        mp.delenv("ALLOWED_USER_IDS", raising=False)
        mp.setenv("ALLOWED_USER_IDS", allowed_user_ids)
        return Settings(_env_file=None)


# ── valid inputs ─────────────────────────────────────────────────────────────


def test_single_user_id():
    s = _make_settings("444992730335019019")
    assert s.allowed_user_ids == [444992730335019019]


def test_multiple_user_ids():
    s = _make_settings("444992730335019019,123456789012345678")
    assert s.allowed_user_ids == [444992730335019019, 123456789012345678]


def test_whitespace_around_comma():
    s = _make_settings("444992730335019019, 123456789012345678")
    assert s.allowed_user_ids == [444992730335019019, 123456789012345678]


def test_leading_and_trailing_whitespace():
    s = _make_settings("  444992730335019019  ,  123456789012345678  ")
    assert s.allowed_user_ids == [444992730335019019, 123456789012345678]


def test_empty_string_returns_empty_list():
    s = _make_settings("")
    assert s.allowed_user_ids == []


def test_result_type_is_list_of_int():
    s = _make_settings("444992730335019019")
    assert isinstance(s.allowed_user_ids, list)
    assert all(isinstance(uid, int) for uid in s.allowed_user_ids)


# ── invalid inputs ────────────────────────────────────────────────────────────


def test_non_numeric_value_raises():
    with pytest.raises((ValidationError, ValueError)):
        _make_settings("abc")


def test_mixed_valid_invalid_raises():
    with pytest.raises((ValidationError, ValueError)):
        _make_settings("123456789012345678,abc")


def test_consecutive_commas_raises():
    with pytest.raises((ValidationError, ValueError)):
        _make_settings("123456789012345678,,987654321098765432")


def test_lone_comma_raises():
    with pytest.raises((ValidationError, ValueError)):
        _make_settings(",")
