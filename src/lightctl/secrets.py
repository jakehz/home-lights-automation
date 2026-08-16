"""Thin wrapper over the macOS Keychain via the ``security`` CLI.

Every item is a generic password stored under a fixed account name
(:data:`config.KEYCHAIN_ACCOUNT`) and a per-secret service name. Nothing
sensitive is ever written to disk in plaintext.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from .config import KEYCHAIN_ACCOUNT

_SECURITY = "/usr/bin/security"


def get(service: str) -> str | None:
    """Return the stored secret for ``service`` or ``None`` if absent."""
    result = subprocess.run(
        [_SECURITY, "find-generic-password", "-s", service, "-a", KEYCHAIN_ACCOUNT, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n")


def set(service: str, value: str) -> None:
    """Store (or replace) ``value`` for ``service`` in the Keychain."""
    subprocess.run(
        [
            _SECURITY, "add-generic-password",
            "-U",  # update if it already exists
            "-s", service,
            "-a", KEYCHAIN_ACCOUNT,
            "-w", value,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def delete(service: str) -> None:
    """Remove ``service`` from the Keychain if present."""
    subprocess.run(
        [_SECURITY, "delete-generic-password", "-s", service, "-a", KEYCHAIN_ACCOUNT],
        capture_output=True,
        text=True,
    )


def get_json(service: str) -> Any | None:
    """Return a stored JSON blob decoded, or ``None`` if absent/corrupt."""
    raw = get(service)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def set_json(service: str, value: Any) -> None:
    """Store ``value`` as a compact JSON blob."""
    set(service, json.dumps(value))
