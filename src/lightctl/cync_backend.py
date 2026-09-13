"""Cync / GE backend (living room).

Cync has no local API, so this talks to Cync's cloud over TCP via the
reverse-engineered ``pycync`` library. Auth is email/password plus a one-time
emailed 2FA code; we cache the resulting token in the Keychain so everyday
commands stay non-interactive.

Two intrinsic Cync limitations the caller should surface to the user:
  * Only one connection per account at a time -- opening the Cync phone app
    temporarily disconnects this client (and vice-versa).
  * Requires internet plus at least one Wi-Fi Cync device acting as a bridge.
"""

from __future__ import annotations

import asyncio
import time

from aiohttp import ClientSession
from pycync import Auth, Cync
from pycync.user import User
from pycync.devices.capabilities import CyncCapability
from pycync.exceptions import TwoFactorRequiredError, AuthFailedError

from . import secrets
from .base import Action, DeviceResult
from .colors import clamp, kelvin_to_cync_percent

TOKEN_SVC = "lights-cync-token"
USER_SVC = "lights-cync-username"
PASS_SVC = "lights-cync-password"

CONNECT_SETTLE = 1.2  # seconds for the TCP connection to come up after create()
STATUS_SETTLE = 1.5   # seconds to let a state poll return


class CyncError(Exception):
    """Raised when the Cync backend cannot be used without re-running setup."""


class CyncNeedsSetup(CyncError):
    """Token missing/expired and interactive 2FA is required."""


def _user_from_token(token: dict) -> User:
    return User(
        token["access_token"],
        token["refresh_token"],
        token["authorize"],
        token["user_id"],
        expires_at=token.get("expires_at"),
    )


def _token_from_user(user: User) -> dict:
    return {
        "access_token": user.access_token,
        "refresh_token": user.refresh_token,
        "authorize": user.authorize,
        "user_id": user.user_id,
        "expires_at": user.expires_at,
    }


async def _authenticated(session: ClientSession) -> Auth:
    """Return an Auth with a valid (refreshed if needed) token, or raise."""
    token = secrets.get_json(TOKEN_SVC)
    if not token:
        raise CyncNeedsSetup("Cync is not set up. Run: lights setup")

    auth = Auth(session, user=_user_from_token(token))

    # Refresh proactively if the token is expired or close to it.
    if user_expiring(auth.user):
        try:
            await auth.async_refresh_user_token()
            secrets.set_json(TOKEN_SVC, _token_from_user(auth.user))
        except AuthFailedError as exc:
            raise CyncNeedsSetup(
                "Cync session expired and needs a fresh 2FA login. Run: lights setup"
            ) from exc
    return auth


def user_expiring(user: User) -> bool:
    try:
        return user.expires_at is None or (user.expires_at - time.time()) < 120
    except TypeError:
        return True


def _lights(cync: Cync) -> list:
    """Return devices that can at least be turned on/off."""
    out = []
    for dev in cync.get_devices():
        try:
            if dev.supports_capability(CyncCapability.ON_OFF):
                out.append(dev)
        except Exception:  # noqa: BLE001
            continue
    return out


async def _apply_one(dev, action: Action) -> DeviceResult:
    name = dev.name
    try:
        if not dev.is_online:
            return DeviceResult(name, False, "offline")
        if action.kind == "on":
            await dev.turn_on()
            return DeviceResult(name, True, "on")
        if action.kind == "off":
            await dev.turn_off()
            return DeviceResult(name, True, "off")
        if action.kind == "dim":
            level = clamp(action.dim, 0, 100)
            await dev.set_brightness(level)
            return DeviceResult(name, True, f"dim {level}%")
        if action.kind == "temp":
            if not dev.supports_capability(CyncCapability.CCT_COLOR):
                return DeviceResult(name, False, "no color-temp support")
            await dev.set_color_temp(kelvin_to_cync_percent(action.kelvin))
            return DeviceResult(name, True, f"{action.kelvin}K")
        if action.kind == "color":
            if not dev.supports_capability(CyncCapability.RGB_COLOR):
                return DeviceResult(name, False, "no color support")
            await dev.set_rgb(action.rgb)
            r, g, b = action.rgb
            return DeviceResult(name, True, f"rgb({r},{g},{b})")
        return DeviceResult(name, False, f"unknown action {action.kind}")
    except Exception as exc:  # noqa: BLE001
        return DeviceResult(name, False, str(exc) or exc.__class__.__name__)


def _status_line(dev) -> DeviceResult:
    try:
        if not dev.is_online:
            return DeviceResult(dev.name, False, power=False)
        try:
            pct = dev.brightness
            return DeviceResult(dev.name, True, power = True, brightness = str(pct))
        except Exception:  # noqa: BLE001 - no dimming capability
            return DeviceResult(dev.name, True, power = True)
    except Exception as exc:  # noqa: BLE001
        return DeviceResult(dev.name, False, str(exc))


async def apply(action: Action, session: ClientSession) -> list[DeviceResult]:
    """Apply ``action`` to every Cync light, or report status."""
    auth = await _authenticated(session)
    cync = await Cync.create(auth)
    try:
        await asyncio.sleep(CONNECT_SETTLE)
        devices = _lights(cync)
        if not devices:
            return [DeviceResult("(living)", False, "no Cync lights found")]

        if action.kind == "status":
            cync.update_device_states()
            await asyncio.sleep(STATUS_SETTLE)
            return [_status_line(d) for d in devices]

        return [await _apply_one(d, action) for d in devices]
    finally:
        await cync.shut_down()


# --- interactive setup (2FA) -------------------------------------------------

async def setup_start(session: ClientSession, username: str, password: str):
    """Begin Cync login. Returns (auth, needs_2fa: bool).

    If 2FA is required, a code has been emailed and the caller should prompt
    for it, then call :func:`setup_finish` with the same ``auth``.
    """
    secrets.set(USER_SVC, username)
    secrets.set(PASS_SVC, password)
    secrets.delete(TOKEN_SVC)

    auth = Auth(session, username=username, password=password)
    try:
        await auth.login()
        return auth, False
    except TwoFactorRequiredError:
        return auth, True


async def setup_finish(auth: Auth, code: str | None) -> list[str]:
    """Complete login (with 2FA ``code`` if needed), save token, list lights."""
    if code:
        await auth.login(code)
    secrets.set_json(TOKEN_SVC, _token_from_user(auth.user))

    cync = await Cync.create(auth)
    try:
        await asyncio.sleep(CONNECT_SETTLE)
        return [d.name for d in _lights(cync)]
    finally:
        await cync.shut_down()
