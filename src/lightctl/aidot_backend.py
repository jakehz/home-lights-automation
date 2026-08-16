"""AiDot backend (bedrooms).

One cloud login fetches an access token plus per-device AES keys; after that
all control happens locally over the LAN (UDP discovery + encrypted TCP to
each bulb). See the ``python-aidot`` library for the underlying protocol.
"""

from __future__ import annotations

import asyncio
import logging

from aiohttp import ClientSession
from aidot.client import AidotClient
from aidot.const import CONF_DEVICE_LIST
from aidot.exceptions import AidotAuthFailed, AidotUserOrPassIncorrect

from . import secrets
from .base import Action, DeviceResult
from .colors import clamp

# The library logs full device dicts (including AES keys) at WARNING. Silence it
# so nothing sensitive lands on the console.
logging.getLogger("aidot").setLevel(logging.CRITICAL)

TOKEN_SVC = "lights-aidot-token"
USER_SVC = "lights-aidot-username"
PASS_SVC = "lights-aidot-password"

CONNECT_TIMEOUT = 8.0  # seconds to wait for LAN discovery + connect
STATUS_SETTLE = 0.6    # seconds to let a freshly connected bulb report state


class AidotError(Exception):
    """Raised when the AiDot backend cannot be used (e.g. not set up)."""


def _attach_save_callback(client: AidotClient) -> None:
    """Persist refreshed login info whenever the library rotates the token."""
    def _save() -> None:
        if client.login_info:
            secrets.set_json(TOKEN_SVC, client.login_info)

    client.set_token_fresh_cb(_save)


async def _fresh_login(session: ClientSession, country_code: str) -> AidotClient:
    """Log in with stored username/password and cache the new token."""
    username = secrets.get(USER_SVC)
    password = secrets.get(PASS_SVC)
    if not username or not password:
        raise AidotError("AiDot is not set up. Run: lights setup")
    client = AidotClient(session, country_code=country_code,
                         username=username, password=password)
    _attach_save_callback(client)
    try:
        await client.async_post_login()
    except AidotUserOrPassIncorrect as exc:
        await client.async_close()
        raise AidotError(
            "AiDot login failed: wrong email/password. Re-run: lights setup"
        ) from exc
    secrets.set_json(TOKEN_SVC, client.login_info)
    return client


async def _login_and_list(session: ClientSession, country_code: str):
    """Return ``(client, devices)``, healing a stale token automatically.

    Tries the cached token first; on an auth failure (expired/rotated token)
    it deletes the cache and re-logs in with the stored credentials.
    """
    token = secrets.get_json(TOKEN_SVC)
    if token:
        client = AidotClient(session, token=token)
        _attach_save_callback(client)
        try:
            result = await client.async_get_all_device()
            return client, result.get(CONF_DEVICE_LIST, [])
        except AidotAuthFailed:
            await client.async_close()
            secrets.delete(TOKEN_SVC)  # stale token; fall through to full login

    client = await _fresh_login(session, country_code)
    result = await client.async_get_all_device()
    return client, result.get(CONF_DEVICE_LIST, [])


async def _connect_devices(client: AidotClient, devices: list[dict]) -> list[tuple]:
    """Create device clients and wait for LAN discovery to connect them.

    Returns a list of ``(device_client, connected: bool)``.
    """
    dcs = [client.get_device_client(dev) for dev in devices]

    deadline = asyncio.get_event_loop().time() + CONNECT_TIMEOUT
    while asyncio.get_event_loop().time() < deadline:
        if all(dc.connect_and_login for dc in dcs):
            break
        await asyncio.sleep(0.2)

    return [(dc, dc.connect_and_login) for dc in dcs]


async def _apply_one(dc, action: Action) -> DeviceResult:
    name = dc.info.name or dc.device_id
    try:
        if action.kind == "on":
            await dc.async_turn_on()
            return DeviceResult(name, True, "on")
        if action.kind == "off":
            await dc.async_turn_off()
            return DeviceResult(name, True, "off")
        if action.kind == "dim":
            level = clamp(action.dim, 0, 100)
            await dc.async_set_brightness(round(level * 255 / 100))
            return DeviceResult(name, True, f"dim {level}%")
        if action.kind == "temp":
            if not dc.info.enable_cct:
                return DeviceResult(name, False, "no color-temp support")
            lo = getattr(dc.info, "cct_min", 2700)
            hi = getattr(dc.info, "cct_max", 6500)
            k = clamp(action.kelvin, lo, hi)
            await dc.async_set_cct(k)
            return DeviceResult(name, True, f"{k}K")
        if action.kind == "color":
            if not dc.info.enable_rgbw:
                return DeviceResult(name, False, "no color support")
            r, g, b = action.rgb
            await dc.async_set_rgbw((r, g, b, 0))
            return DeviceResult(name, True, f"rgb({r},{g},{b})")
        return DeviceResult(name, False, f"unknown action {action.kind}")
    except Exception as exc:  # noqa: BLE001 - report, don't crash the whole run
        return DeviceResult(name, False, str(exc) or exc.__class__.__name__)


def _status_line(dc) -> DeviceResult:
    name = dc.info.name or dc.device_id
    st = dc.status
    if not st.online:
        return DeviceResult(name, False, "offline")
    power = "on" if st.on else "off"
    pct = round(st.dimming * 100 / 255)
    return DeviceResult(name, True, f"{power}, {pct}%")


async def apply(action: Action, session: ClientSession, country_code: str) -> list[DeviceResult]:
    """Apply ``action`` to every AiDot device, or report status."""
    client, devices = await _login_and_list(session, country_code)
    try:
        if not devices:
            return [DeviceResult("(bedroom)", False, "no AiDot devices found")]

        connected = await _connect_devices(client, devices)

        if action.kind == "status":
            await asyncio.sleep(STATUS_SETTLE)
            out = []
            for dc, ok in connected:
                out.append(_status_line(dc) if ok else
                           DeviceResult(dc.info.name or dc.device_id, False,
                                        "offline (powered off at switch, or not on Wi-Fi)"))
            return out

        out = []
        for dc, ok in connected:
            if not ok:
                out.append(DeviceResult(dc.info.name or dc.device_id, False,
                                        "offline (powered off at switch, or not on Wi-Fi)"))
                continue
            out.append(await _apply_one(dc, action))
        return out
    finally:
        await client.async_close()


async def setup(session: ClientSession, country_code: str, username: str,
                password: str) -> list[str]:
    """Store credentials, verify by logging in, and return device names."""
    secrets.set(USER_SVC, username)
    secrets.set(PASS_SVC, password)
    secrets.delete(TOKEN_SVC)  # force a fresh login below

    client = AidotClient(session, country_code=country_code,
                         username=username, password=password)
    try:
        await client.async_post_login()
        secrets.set_json(TOKEN_SVC, client.login_info)
        result = await client.async_get_all_device()
        devices = result.get(CONF_DEVICE_LIST, [])
        return [d.get("name") or d.get("id", "?") for d in devices]
    finally:
        await client.async_close()
