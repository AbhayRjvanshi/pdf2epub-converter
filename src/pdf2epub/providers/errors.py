"""Normalized provider errors.

Every SDK exception terminates at the provider-adapter boundary and is
re-raised as one of these five classes. Messages are scrubbed of credential
material before the exception is constructed, so a secret cannot leak into
logs through an error.

Classification (v2.4 delta): 401/403/400/404 are permanent; 429, 5xx and
timeouts are transient and may be retried. The ``retryable`` flag carries
that decision, so the future retry ladder and circuit breaker never need
to re-parse SDK exception types.
"""

from __future__ import annotations

from urllib.parse import quote

_REDACTED = "***"


def redact_secret(text: str, secret: str) -> str:
    """Remove the secret and its common variants from ``text``.

    Covers the bare value, surrounding whitespace, lower/upper-case copies
    and the URL-encoded form (keys echoed back inside request URLs).
    """
    if not secret:
        return text
    variants = {secret, secret.strip(), secret.lower(), secret.upper()}
    variants.add(quote(secret, safe=""))
    out = text
    for variant in variants:
        if variant:
            out = out.replace(variant, _REDACTED)
    return out


class ProviderError(Exception):
    """Base class for every normalized provider error."""

    retryable: bool = False
    retry_after: float | None = None

    def __init__(self, message: str, *, secret: str | None = None) -> None:
        if secret:
            message = redact_secret(message, secret)
        super().__init__(message)


class CredentialError(ProviderError):
    """API key missing, malformed, or rejected (401/403). Permanent."""


class ProviderUnavailableError(ProviderError):
    """Provider unreachable: network, DNS, sustained 5xx. Transient."""

    retryable = True


class ModelNotFoundError(ProviderError):
    """The requested model does not exist for this provider (404). Permanent."""


class ProviderRequestError(ProviderError):
    """Request rejected (400, permanent) or throttled (429, transient)."""

    def __init__(
        self,
        message: str,
        *,
        secret: str | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, secret=secret)
        self.retryable = retryable
        self.retry_after = retry_after


class ProviderResponseError(ProviderError):
    """A response arrived but was unusable (garbled JSON, wrong shape)."""


def error_from_status(
    status: int,
    message: str,
    *,
    secret: str | None = None,
    retry_after: float | None = None,
) -> ProviderError:
    """Map an HTTP status to the right normalized error.

    Adapters call this instead of hand-rolling per-SDK tables, so
    classification lives in exactly one place.
    """
    if status in (401, 403):
        return CredentialError(message, secret=secret)
    if status == 404:
        return ModelNotFoundError(message, secret=secret)
    if status == 429:
        return ProviderRequestError(
            message, secret=secret, retryable=True, retry_after=retry_after
        )
    if 500 <= status < 600:
        return ProviderUnavailableError(message, secret=secret)
    return ProviderRequestError(message, secret=secret)


def normalize_error(exc: BaseException, *, secret: str | None = None) -> ProviderError:
    """Boundary guard: convert any stray exception to a normalized error.

    ProviderError instances pass through untouched; anything else is wrapped
    as unavailable (the conservative default for unknown failures) with the
    original type kept in the message for diagnosis.
    """
    if isinstance(exc, ProviderError):
        return exc
    message = f"{type(exc).__name__}: {exc}"
    if secret:
        message = redact_secret(message, secret)
    return ProviderUnavailableError(message)


def extract_retry_after(exc: BaseException) -> float | None:
    """Best-effort Retry-After extraction from an SDK/httpx response."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    for name in ("retry-after", "Retry-After"):
        try:
            value = headers.get(name)
        except Exception:
            return None
        if value:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def map_sdk_error(exc: BaseException, *, secret: str | None = None) -> ProviderError:
    """Map an SDK exception to a normalized provider error.

    Works by attribute, never by importing SDK exception types: any
    exception exposing ``status_code`` is classified by
    :func:`error_from_status` (with ``Retry-After`` honoured); everything
    else degrades to :func:`normalize_error`'s unavailable default.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return error_from_status(
            status,
            f"{type(exc).__name__}: {exc}",
            secret=secret,
            retry_after=extract_retry_after(exc),
        )
    return normalize_error(exc, secret=secret)
