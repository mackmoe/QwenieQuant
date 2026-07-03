import base64
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def sign_message(message: str, private_key_pem: str) -> str:
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode(),
        password=None,
    )
    signature = private_key.sign(
        message.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def build_auth_headers(
    method: str,
    path: str,
    api_key: str,
    private_key_pem: str,
) -> dict[str, str]:
    ts_ms = str(int(time.time() * 1000))
    message = ts_ms + method.upper() + path
    signature = sign_message(message, private_key_pem)
    return {
        "KALSHI-ACCESS-KEY": api_key,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        "Content-Type": "application/json",
    }
