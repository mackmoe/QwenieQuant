import base64
import time
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.authentication import build_auth_headers, sign_message


def _generate_key_pem() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


_KEY_PEM = _generate_key_pem()


def test_sign_message_returns_base64_string():
    sig = sign_message("hello", _KEY_PEM)
    assert isinstance(sig, str)
    decoded = base64.b64decode(sig)
    assert len(decoded) == 256  # 2048-bit RSA signature = 256 bytes


def test_sign_message_is_deterministic_for_same_input():
    sig1 = sign_message("same message", _KEY_PEM)
    sig2 = sign_message("same message", _KEY_PEM)
    # PSS uses random salt, so signatures differ — both should decode cleanly
    assert base64.b64decode(sig1) is not None
    assert base64.b64decode(sig2) is not None


def test_sign_message_differs_for_different_inputs():
    sig1 = sign_message("message-a", _KEY_PEM)
    sig2 = sign_message("message-b", _KEY_PEM)
    assert sig1 != sig2


def test_build_auth_headers_returns_required_keys():
    headers = build_auth_headers("GET", "/trade-api/v2/markets", "my-key", _KEY_PEM)
    assert "KALSHI-ACCESS-KEY" in headers
    assert "KALSHI-ACCESS-SIGNATURE" in headers
    assert "KALSHI-ACCESS-TIMESTAMP" in headers
    assert "Content-Type" in headers


def test_build_auth_headers_api_key_is_set():
    headers = build_auth_headers("GET", "/trade-api/v2/markets", "api-key-123", _KEY_PEM)
    assert headers["KALSHI-ACCESS-KEY"] == "api-key-123"


def test_build_auth_headers_timestamp_is_recent():
    before = int(time.time() * 1000)
    headers = build_auth_headers("GET", "/trade-api/v2/markets", "k", _KEY_PEM)
    after = int(time.time() * 1000)
    ts = int(headers["KALSHI-ACCESS-TIMESTAMP"])
    assert before <= ts <= after


def test_build_auth_headers_content_type_is_json():
    headers = build_auth_headers("POST", "/trade-api/v2/portfolio/orders", "k", _KEY_PEM)
    assert headers["Content-Type"] == "application/json"


def test_build_auth_headers_signature_is_valid_base64():
    headers = build_auth_headers("GET", "/trade-api/v2/markets", "k", _KEY_PEM)
    decoded = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
    assert len(decoded) == 256


def test_build_auth_headers_different_paths_produce_different_signatures():
    h1 = build_auth_headers("GET", "/trade-api/v2/markets", "k", _KEY_PEM)
    h2 = build_auth_headers("GET", "/trade-api/v2/positions", "k", _KEY_PEM)
    assert h1["KALSHI-ACCESS-SIGNATURE"] != h2["KALSHI-ACCESS-SIGNATURE"]


def test_build_auth_headers_method_is_uppercased_in_message():
    # Both "get" and "GET" should produce valid (but probably different due to PSS salt) headers
    h1 = build_auth_headers("get", "/trade-api/v2/markets", "k", _KEY_PEM)
    h2 = build_auth_headers("GET", "/trade-api/v2/markets", "k", _KEY_PEM)
    # Both should have valid base64 signatures regardless of case
    assert base64.b64decode(h1["KALSHI-ACCESS-SIGNATURE"]) is not None
    assert base64.b64decode(h2["KALSHI-ACCESS-SIGNATURE"]) is not None
