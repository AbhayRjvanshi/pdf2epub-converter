"""Phase 3: the explicit-offline provider needs nothing and fakes nothing."""

import pytest

from pdf2epub.providers.base import ProviderAdapter
from pdf2epub.providers.errors import ProviderError
from pdf2epub.providers.offline import OfflineProvider


def test_offline_conforms_to_the_contract():
    provider = OfflineProvider()
    assert isinstance(provider, ProviderAdapter)
    assert provider.provider_id == "none"


def test_offline_needs_no_credential():
    assert OfflineProvider().validate_credentials("") is True


def test_offline_offers_no_models():
    assert OfflineProvider().resolve_models() == []


def test_offline_never_fabricates_a_callable():
    with pytest.raises(ProviderError):
        OfflineProvider().create_llm_callable("any-model", "any-key")
