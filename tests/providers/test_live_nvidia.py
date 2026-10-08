"""Environment-gated live NVIDIA/Kimi K3 smoke tests.

These prove the real path the unit suite can only fake:
``build_registry -> NvidiaStyleAdapter -> openai SDK ->
integrate.api.nvidia.com -> moonshotai/kimi-k3 -> response``.

They run only when ``NVIDIA_API_KEY`` is present in the environment and
skip (never fail) without it, so CI and offline development are
unaffected. Select with ``pytest -m live``; exclude with ``-m "not
live"``. No ad-hoc SDK scripts: every request goes through the project's
provider abstraction (stabilization plan, Phase G / Phase P).
"""

import base64
import os

import fitz
import pytest

from pdf2epub.providers.registry import build_registry

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("NVIDIA_API_KEY"),
        reason="NVIDIA_API_KEY not set; live provider tests skip",
    ),
]

KIMI_K3 = "moonshotai/kimi-k3"


def _key() -> str:
    return os.environ["NVIDIA_API_KEY"]


def _tiny_png_b64() -> str:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8))
    pix.set_pixel(0, 0, (255, 0, 0))
    data = pix.tobytes("png")
    return base64.b64encode(data).decode("ascii")


def test_live_credential_verification_reaches_nvidia():
    adapter = build_registry().get("nvidia")
    assert adapter.validate_credentials(_key()) is True


def test_live_text_request_through_kimi_k3():
    adapter = build_registry().get("nvidia")
    llm = adapter.create_llm_callable(KIMI_K3, _key())
    response = llm(
        "You are a connectivity smoke test. Reply with exactly the JSON "
        'object {"ok": true} and nothing else.',
        "smoke",
    )
    assert isinstance(response, str) and response.strip()
    assert "true" in response.lower()


def test_live_image_request_through_kimi_k3():
    adapter = build_registry().get("nvidia")
    llm = adapter.create_llm_callable(KIMI_K3, _key())
    response = llm(
        "You are a multimodal smoke test. Reply with exactly the JSON "
        'object {"image": true} and nothing else.',
        "smoke",
        image_b64=_tiny_png_b64(),
    )
    assert isinstance(response, str) and response.strip()
    assert "true" in response.lower()
