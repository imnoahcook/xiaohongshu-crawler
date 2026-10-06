"""Shared pytest configuration."""

import pytest


@pytest.fixture(autouse=True)
def _no_login_state_wait(monkeypatch):
    """Mock pages never produce a user/me response, so do not wait for one."""
    monkeypatch.setattr("src.auth._USER_ME_WAIT_SECONDS", 0)
