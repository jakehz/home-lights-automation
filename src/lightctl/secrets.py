"""Cross-platform secret storage for credentials and auth tokens.

Each secret is stored under a per-secret ``service`` name:
  * macOS  -> the login Keychain via the ``security`` CLI (nothing on disk).
  * Linux/other -> a ``chmod 600`` JSON file at ``~/.lights/secrets.json``
    (there is no system keyring on a headless Raspberry Pi).

The public API (get/set/delete/get_json/set_json) is identical on both.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from .config import CONFIG_DIR, KEYCHAIN_ACCOUNT

_IS_MACOS = sys.platform == "darwin"
_SECURITY = "/usr/bin/security"
_SECRETS_FILE = CONFIG_DIR / "secrets.json"


# --- macOS Keychain backend --------------------------------------------------

def _kc_get(service: str) -> str | None:
    result = subprocess.run(
        [_SECURITY, "find-generic-password", "-s", service, "-a", KEYCHAIN_ACCOUNT, "-w"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n")


def _kc_set(service: str, value: str) -> None:
    subprocess.run(
        [_SECURITY, "add-generic-password", "-U",
         "-s", service, "-a", KEYCHAIN_ACCOUNT, "-w", value],
        check=True, capture_output=True, text=True,
    )


def _kc_delete(service: str) -> None:
    subprocess.run(
        [_SECURITY, "delete-generic-password", "-s", service, "-a", KEYCHAIN_ACCOUNT],
        capture_output=True, text=True,
    )


# --- Linux file backend (chmod 600) ------------------------------------------

def _file_load() -> dict[str, str]:
    try:
        return json.loads(_SECRETS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _file_save(data: dict[str, str]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Write with owner-only permissions from the start.
    fd = os.open(_SECRETS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.chmod(_SECRETS_FILE, 0o600)


def _file_get(service: str) -> str | None:
    return _file_load().get(service)


def _file_set(service: str, value: str) -> None:
    data = _file_load()
    data[service] = value
    _file_save(data)


def _file_delete(service: str) -> None:
    data = _file_load()
    if service in data:
        del data[service]
        _file_save(data)


# --- public API --------------------------------------------------------------

def get(service: str) -> str | None:
    """Return the stored secret for ``service`` or ``None`` if absent."""
    return _kc_get(service) if _IS_MACOS else _file_get(service)


def set(service: str, value: str) -> None:
    """Store (or replace) ``value`` for ``service``."""
    (_kc_set if _IS_MACOS else _file_set)(service, value)


def delete(service: str) -> None:
    """Remove ``service`` if present."""
    (_kc_delete if _IS_MACOS else _file_delete)(service)


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
