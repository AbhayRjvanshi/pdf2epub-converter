"""Shared keyring fixtures for the credential resolver tests.

The resolver's find_spec guard is patched directly (the module imported it
by name), so the "package absent" state is simulated regardless of whether
keyring happens to be installed in this environment.
"""

import sys
import types

import pytest

from pdf2epub.config import credentials


class FakeKeyring:
    """Records calls; programmable get/set/delete results."""

    def __init__(self):
        self.store = {}
        self.get_calls = []
        self.set_calls = []
        self.delete_calls = []
        self.get_error = None
        self.set_error = None
        self.delete_error = None

    def get_password(self, service, username):
        self.get_calls.append((service, username))
        if self.get_error is not None:
            raise self.get_error
        return self.store.get(username)

    def set_password(self, service, username, password):
        self.set_calls.append((service, username, password))
        if self.set_error is not None:
            raise self.set_error
        self.store[username] = password

    def delete_password(self, service, username):
        self.delete_calls.append((service, username))
        if self.delete_error is not None:
            raise self.delete_error
        self.store.pop(username, None)


@pytest.fixture
def fake_keyring(monkeypatch):
    ring = FakeKeyring()
    module = types.ModuleType("keyring")
    module.get_password = ring.get_password
    module.set_password = ring.set_password
    module.delete_password = ring.delete_password
    monkeypatch.setitem(sys.modules, "keyring", module)
    monkeypatch.setattr(
        credentials,
        "find_spec",
        lambda name: object() if name == "keyring" else None,
    )
    return ring


@pytest.fixture
def no_keyring(monkeypatch):
    monkeypatch.setattr(credentials, "find_spec", lambda name: None)
