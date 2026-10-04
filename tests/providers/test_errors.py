"""Phase 3: normalized error taxonomy, status classification, redaction."""

from urllib.parse import quote

from pdf2epub.providers.errors import (
    CredentialError,
    ModelNotFoundError,
    ProviderError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderUnavailableError,
    error_from_status,
    normalize_error,
    redact_secret,
)


def test_status_mapping_table():
    assert isinstance(error_from_status(401, "key rejected"), CredentialError)
    assert isinstance(error_from_status(403, "forbidden"), CredentialError)
    assert isinstance(error_from_status(404, "no such model"), ModelNotFoundError)


def test_throttling_is_retryable_and_carries_retry_after():
    err = error_from_status(429, "slow down", retry_after=12.0)
    assert isinstance(err, ProviderRequestError)
    assert err.retryable is True
    assert err.retry_after == 12.0


def test_server_errors_are_retryable_unavailability():
    assert isinstance(error_from_status(500, "boom"), ProviderUnavailableError)
    unavailable = error_from_status(503, "overloaded")
    assert unavailable.retryable is True


def test_client_errors_are_permanent_request_failures():
    bad = error_from_status(400, "bad request")
    assert isinstance(bad, ProviderRequestError)
    assert bad.retryable is False
    assert bad.retry_after is None


def test_retryability_defaults_per_class():
    assert CredentialError("x").retryable is False
    assert ProviderUnavailableError("x").retryable is True
    assert ModelNotFoundError("x").retryable is False
    assert ProviderResponseError("x").retryable is False


def test_secret_is_scrubbed_from_error_message():
    key = "sk-super-secret-value"
    err = CredentialError(f"key {key} rejected by provider", secret=key)
    assert key not in str(err)
    assert "***" in str(err)


def test_redact_handles_case_variants():
    key = "abcDEF123"
    text = f"failed with {key} and {key.lower()} and {key.upper()}"
    out = redact_secret(text, key)
    assert key not in out
    assert "abcDEF123".lower() not in out


def test_redact_removes_url_encoded_variant():
    key = "ab+cd/9="
    encoded = quote(key, safe="")
    out = redact_secret(f"request failed for {encoded}", key)
    assert encoded not in out


def test_normalize_error_passes_provider_errors_through():
    original = ModelNotFoundError("gone")
    assert normalize_error(original) is original


def test_normalize_error_wraps_and_redacts_unknown_exceptions():
    key = "sk-super-secret-value"
    wrapped = normalize_error(ValueError(f"boom {key}"), secret=key)
    assert isinstance(wrapped, ProviderUnavailableError)
    assert "ValueError" in str(wrapped)
    assert key not in str(wrapped)


def test_provider_error_is_the_common_base():
    for cls in (
        CredentialError,
        ProviderUnavailableError,
        ModelNotFoundError,
        ProviderRequestError,
        ProviderResponseError,
    ):
        assert issubclass(cls, ProviderError)
