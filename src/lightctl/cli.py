"""Command-line interface: one `lights` command for both light brands."""

from __future__ import annotations

import asyncio
import getpass
import sys

from aiohttp import ClientSession

from . import aidot_backend, cync_backend
from .base import Action, DeviceResult
from .engine import ACTIONS, build_action, run_action
from .config import load_config, save_config

ROOMS = ("living", "bedroom", "all")

USAGE = """\
lights - control the living room (GE/Cync) and bedroom (AiDot) lights.

Usage:
  lights <room> <action> [value]
  lights <action> [value]          (applies to all rooms)
  lights setup                     (first-run login for both brands)
  lights serve [--port N]          (start the web UI, default port 8765)

  room     living | bedroom | all
  action   on
           off
           dim <0-100>             brightness percent
           temp <2700-6500>        white color temperature in Kelvin
           color <name|#rrggbb>    e.g. warm, red, #0044ff
           status                  show on/off + level per light

Examples:
  lights all off
  lights bedroom dim 40
  lights living temp 3000
  lights bedroom color warm
  lights status
  lights serve
"""


def _fail(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 2


def parse_args(argv: list[str]) -> tuple[str, Action]:
    """Parse ``room`` and a resolved :class:`Action` from CLI args."""
    if not argv:
        raise ValueError(USAGE)

    # Allow "lights <action> ..." as shorthand for room = all.
    if argv[0] in ACTIONS:
        room, rest = "all", argv
    elif argv[0] in ROOMS:
        room, rest = argv[0], argv[1:]
    else:
        raise ValueError(f"unknown room or action '{argv[0]}'.\n\n{USAGE}")

    if not rest:
        raise ValueError(f"missing action for room '{room}'.\n\n{USAGE}")

    action_name = rest[0]
    value = rest[1] if len(rest) > 1 else None
    try:
        action = build_action(action_name, value)
    except ValueError as exc:
        raise ValueError(f"{exc}.\n\n{USAGE}")
    return room, action


def _print_results(label: str, results: list[DeviceResult]) -> bool:
    """Print a room's results; return True if at least one device succeeded."""
    print(f"\n{label}:")
    any_ok = False
    width = max((len(r.name) for r in results), default=0)
    for r in results:
        mark = "✓" if r.ok else "✗"
        print(f"  {mark} {r.name.ljust(width)}  {r.detail}")
        any_ok = any_ok or r.ok
    return any_ok


async def do_command(room: str, action: Action, cfg: dict) -> int:
    try:
        outcomes = await run_action(room, action, cfg)
    except KeyError:
        return _fail(f"unknown room '{room}'")

    overall_ok = False
    for outcome in outcomes:
        ok = _print_results(outcome.label, outcome.results)
        overall_ok = overall_ok or ok
    print()
    return 0 if overall_ok else 1


async def do_setup(cfg: dict) -> int:
    print("Setting up the lights CLI. You'll log in once per brand; "
          "credentials and tokens are stored in your macOS Keychain.\n")
    country = cfg.get("aidot", {}).get("country_code", "US")

    async with ClientSession() as session:
        # --- AiDot (bedrooms) ---
        print("== AiDot (bedrooms) ==")
        try:
            a_user = input("  AiDot account email: ").strip()
            a_pass = getpass.getpass("  AiDot password: ")
            names = await aidot_backend.setup(session, country, a_user, a_pass)
            if names:
                print(f"  Found {len(names)} device(s): {', '.join(names)}")
            else:
                print("  Logged in, but no AiDot devices were found on the account.")
        except Exception as exc:  # noqa: BLE001
            print(f"  AiDot setup failed: {exc}", file=sys.stderr)

        # --- Cync (living room) ---
        print("\n== Cync / GE (living room) ==")
        try:
            c_user = input("  Cync account email: ").strip()
            c_pass = getpass.getpass("  Cync password: ")
            auth, needs_2fa = await cync_backend.setup_start(session, c_user, c_pass)
            code = None
            if needs_2fa:
                code = input("  Enter the 6-digit code Cync just emailed you: ").strip()
            names = await cync_backend.setup_finish(auth, code)
            if names:
                print(f"  Found {len(names)} light(s): {', '.join(names)}")
            else:
                print("  Logged in, but no Cync lights were found on the account.")
        except Exception as exc:  # noqa: BLE001
            print(f"  Cync setup failed: {exc}", file=sys.stderr)

    save_config(cfg)  # ensure config.json exists on disk
    print("\nSetup complete. Try:  lights all on")
    return 0


async def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cfg = load_config()

    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0

    if argv[0] == "setup":
        return await do_setup(cfg)

    try:
        room, action = parse_args(argv)
    except ValueError as exc:
        return _fail(str(exc))

    return await do_command(room, action, cfg)


def _parse_port(args: list[str]) -> int:
    """Pull an optional --port N (default 8765) out of serve args."""
    if "--port" in args:
        i = args.index("--port")
        try:
            return int(args[i + 1])
        except (IndexError, ValueError):
            raise SystemExit("--port needs a number, e.g. lights serve --port 9000")
    return 8765


def run() -> None:
    """Console entry point."""
    argv = sys.argv[1:]

    # `serve` starts aiohttp, which manages its own event loop, so it must run
    # outside asyncio.run().
    if argv and argv[0] == "serve":
        from .server import run_server
        run_server(port=_parse_port(argv[1:]))
        return

    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
