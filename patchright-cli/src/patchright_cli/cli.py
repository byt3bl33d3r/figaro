"""Argparse-based CLI for patchright-cli.

Parses all commands and dispatches to the client module or handles
session-management commands directly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from patchright_cli.client import (
    close_all_sessions,
    delete_session_data,
    kill_all_sessions,
    open_session,
    send_command,
)
from patchright_cli.config import load_config
from patchright_cli.session import (
    get_log_path,
    get_session_dir,
    list_sessions,
    resolve_session_name,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _args_to_dict(
    args: argparse.Namespace,
    exclude: tuple[str, ...] = ("session", "config", "command", "version"),
) -> dict:
    """Convert argparse Namespace to dict, excluding global/meta keys."""
    return {k: v for k, v in vars(args).items() if k not in exclude and v is not None}


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def _register_subcommands(subparsers: argparse._SubParsersAction) -> None:
    """Register every subcommand on *subparsers*."""

    # ── Core ───────────────────────────────────────────────────────────

    p = subparsers.add_parser("open", help="Open a browser session")
    p.add_argument("url", nargs="?", default=None, help="Initial URL to navigate to")
    p.add_argument(
        "--headed",
        action="store_true",
        default=False,
        help="Run browser in headed mode (default)",
    )
    p.add_argument("--browser", default=None, help="Browser channel to use")
    p.add_argument(
        "--isolated",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )
    p.add_argument("--profile", default=None, help="Path to user data directory")
    p.add_argument("--extension", default=None, help="Connect to browser extension")
    p.add_argument(
        "--persistent",
        action="store_true",
        default=False,
        help="Use persistent browser context",
    )
    p.add_argument(
        "--webgl-renderer",
        default=None,
        help="Spoof WebGL renderer string (e.g. 'ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 3060/PCIe/SSE2, OpenGL 4.5)')",
    )

    p = subparsers.add_parser("goto", help="Navigate to a URL")
    p.add_argument("url", help="URL to navigate to")

    subparsers.add_parser("close", help="Close the current page")

    p = subparsers.add_parser("type", help="Type text into the focused element")
    p.add_argument("text", help="Text to type")
    p.add_argument(
        "--submit", action="store_true", default=False, help="Press Enter after typing"
    )

    p = subparsers.add_parser("click", help="Click an element")
    p.add_argument("ref", help="Element reference")
    p.add_argument(
        "button", nargs="?", default="left", help="Mouse button (default: left)"
    )
    p.add_argument(
        "--modifiers", nargs="*", default=None, help="Modifier keys (e.g. ctrl shift)"
    )

    p = subparsers.add_parser("dblclick", help="Double-click an element")
    p.add_argument("ref", help="Element reference")
    p.add_argument(
        "button", nargs="?", default="left", help="Mouse button (default: left)"
    )
    p.add_argument(
        "--modifiers", nargs="*", default=None, help="Modifier keys (e.g. ctrl shift)"
    )

    p = subparsers.add_parser("fill", help="Fill an input element with text")
    p.add_argument("ref", help="Element reference")
    p.add_argument("text", help="Text to fill")
    p.add_argument(
        "--submit", action="store_true", default=False, help="Press Enter after filling"
    )

    p = subparsers.add_parser("drag", help="Drag from one element to another")
    p.add_argument("start_ref", help="Source element reference")
    p.add_argument("end_ref", help="Target element reference")

    p = subparsers.add_parser("hover", help="Hover over an element")
    p.add_argument("ref", help="Element reference")

    p = subparsers.add_parser("select", help="Select an option in a dropdown")
    p.add_argument("ref", help="Element reference")
    p.add_argument("value", help="Option value to select")

    p = subparsers.add_parser("upload", help="Upload a file")
    p.add_argument("file", help="Path to the file to upload")

    p = subparsers.add_parser("check", help="Check a checkbox")
    p.add_argument("ref", help="Element reference")

    p = subparsers.add_parser("uncheck", help="Uncheck a checkbox")
    p.add_argument("ref", help="Element reference")

    p = subparsers.add_parser(
        "snapshot", help="Take an accessibility snapshot of the page"
    )
    p.add_argument("--filename", default=None, help="Output filename")

    p = subparsers.add_parser("eval", help="Evaluate a JavaScript expression")
    p.add_argument("expression", help="JavaScript expression to evaluate")
    p.add_argument("ref", nargs="?", default=None, help="Element reference for context")

    p = subparsers.add_parser("dialog-accept", help="Accept a dialog")
    p.add_argument(
        "prompt_text", nargs="?", default=None, help="Text to enter in a prompt dialog"
    )

    subparsers.add_parser("dialog-dismiss", help="Dismiss a dialog")

    p = subparsers.add_parser("resize", help="Resize the browser viewport")
    p.add_argument("width", type=int, help="Viewport width")
    p.add_argument("height", type=int, help="Viewport height")

    # ── Navigation ─────────────────────────────────────────────────────

    subparsers.add_parser("go-back", help="Navigate back in history")
    subparsers.add_parser("go-forward", help="Navigate forward in history")
    subparsers.add_parser("reload", help="Reload the current page")

    # ── Keyboard ───────────────────────────────────────────────────────

    p = subparsers.add_parser("press", help="Press a key or key combination")
    p.add_argument("key", help="Key to press (e.g. Enter, Control+c)")

    p = subparsers.add_parser("keydown", help="Dispatch a keydown event")
    p.add_argument("key", help="Key to press down")

    p = subparsers.add_parser("keyup", help="Dispatch a keyup event")
    p.add_argument("key", help="Key to release")

    # ── Mouse ──────────────────────────────────────────────────────────

    p = subparsers.add_parser("mousemove", help="Move the mouse to coordinates")
    p.add_argument("x", type=float, help="X coordinate")
    p.add_argument("y", type=float, help="Y coordinate")

    p = subparsers.add_parser("mousedown", help="Press a mouse button down")
    p.add_argument(
        "button", nargs="?", default="left", help="Mouse button (default: left)"
    )

    p = subparsers.add_parser("mouseup", help="Release a mouse button")
    p.add_argument(
        "button", nargs="?", default="left", help="Mouse button (default: left)"
    )

    p = subparsers.add_parser("mousewheel", help="Scroll the mouse wheel")
    p.add_argument("dx", type=float, help="Horizontal scroll delta")
    p.add_argument("dy", type=float, help="Vertical scroll delta")

    # ── Save as ────────────────────────────────────────────────────────

    p = subparsers.add_parser("screenshot", help="Take a screenshot")
    p.add_argument(
        "ref", nargs="?", default=None, help="Element reference to screenshot"
    )
    p.add_argument("--filename", default=None, help="Output filename")
    p.add_argument(
        "--full-page",
        action="store_true",
        default=False,
        help="Take full scrollable page screenshot",
    )

    p = subparsers.add_parser("pdf", help="Save page as PDF")
    p.add_argument("--filename", default=None, help="Output filename")

    # ── Tabs ───────────────────────────────────────────────────────────

    subparsers.add_parser("tab-list", help="List open tabs")

    p = subparsers.add_parser("tab-new", help="Open a new tab")
    p.add_argument("url", nargs="?", default=None, help="URL to open in the new tab")

    p = subparsers.add_parser("tab-close", help="Close a tab")
    p.add_argument(
        "index", nargs="?", default=None, type=int, help="Tab index to close"
    )

    p = subparsers.add_parser("tab-select", help="Switch to a tab")
    p.add_argument("index", type=int, help="Tab index to select")

    # ── Storage ────────────────────────────────────────────────────────

    p = subparsers.add_parser("state-save", help="Save browser state")
    p.add_argument("filename", nargs="?", default=None, help="Output filename")

    p = subparsers.add_parser("state-load", help="Load browser state")
    p.add_argument("filename", help="State file to load")

    p = subparsers.add_parser("cookie-list", help="List cookies")
    p.add_argument("--domain", default=None, help="Filter by domain")
    p.add_argument("--path", default=None, help="Filter by path")

    p = subparsers.add_parser("cookie-get", help="Get a cookie by name")
    p.add_argument("name", help="Cookie name")

    p = subparsers.add_parser("cookie-set", help="Set a cookie")
    p.add_argument("name", help="Cookie name")
    p.add_argument("value", help="Cookie value")
    p.add_argument("--domain", default=None, help="Cookie domain")
    p.add_argument("--path", default=None, help="Cookie path")
    p.add_argument(
        "--expires", type=float, default=None, help="Cookie expiration (Unix timestamp)"
    )
    p.add_argument(
        "--httpOnly", action="store_true", default=False, help="HTTP only cookie"
    )
    p.add_argument("--secure", action="store_true", default=False, help="Secure cookie")
    p.add_argument(
        "--sameSite",
        choices=["Strict", "Lax", "None"],
        default=None,
        help="SameSite attribute",
    )

    p = subparsers.add_parser("cookie-delete", help="Delete a cookie")
    p.add_argument("name", help="Cookie name")

    subparsers.add_parser("cookie-clear", help="Clear all cookies")

    subparsers.add_parser("localstorage-list", help="List all localStorage entries")

    p = subparsers.add_parser("localstorage-get", help="Get a localStorage value")
    p.add_argument("key", help="Storage key")

    p = subparsers.add_parser("localstorage-set", help="Set a localStorage value")
    p.add_argument("key", help="Storage key")
    p.add_argument("value", help="Storage value")

    p = subparsers.add_parser("localstorage-delete", help="Delete a localStorage entry")
    p.add_argument("key", help="Storage key")

    subparsers.add_parser("localstorage-clear", help="Clear all localStorage entries")

    subparsers.add_parser("sessionstorage-list", help="List all sessionStorage entries")

    p = subparsers.add_parser("sessionstorage-get", help="Get a sessionStorage value")
    p.add_argument("key", help="Storage key")

    p = subparsers.add_parser("sessionstorage-set", help="Set a sessionStorage value")
    p.add_argument("key", help="Storage key")
    p.add_argument("value", help="Storage value")

    p = subparsers.add_parser(
        "sessionstorage-delete", help="Delete a sessionStorage entry"
    )
    p.add_argument("key", help="Storage key")

    subparsers.add_parser(
        "sessionstorage-clear", help="Clear all sessionStorage entries"
    )

    # ── Network ────────────────────────────────────────────────────────

    p = subparsers.add_parser("route", help="Intercept requests matching a pattern")
    p.add_argument("pattern", help="URL pattern to intercept")
    p.add_argument("--body", default=None, help="Response body")
    p.add_argument("--status", default=None, type=int, help="Response status code")
    p.add_argument("--content-type", default=None, help="Response content type")
    p.add_argument(
        "--header", action="append", default=None, help='Header in "Name: Value" format'
    )
    p.add_argument(
        "--remove-header", default=None, help="Comma-separated header names to remove"
    )

    subparsers.add_parser("route-list", help="List active routes")

    p = subparsers.add_parser("unroute", help="Remove a route")
    p.add_argument(
        "pattern",
        nargs="?",
        default=None,
        help="URL pattern to remove (all if omitted)",
    )

    # ── DevTools ───────────────────────────────────────────────────────

    p = subparsers.add_parser("console", help="Show console messages")
    p.add_argument(
        "min_level", nargs="?", default=None, help="Minimum log level to display"
    )
    p.add_argument(
        "--clear", action="store_true", default=False, help="Clear console messages"
    )

    p = subparsers.add_parser("network", help="Show network activity")
    p.add_argument(
        "--static",
        action="store_true",
        default=False,
        help="Include successful static resources",
    )
    p.add_argument(
        "--clear", action="store_true", default=False, help="Clear network log"
    )

    subparsers.add_parser("tracing-start", help="Start tracing")
    subparsers.add_parser("tracing-stop", help="Stop tracing and save trace file")

    subparsers.add_parser("video-start", help="Start recording video")

    p = subparsers.add_parser("video-stop", help="Stop recording video")
    p.add_argument("--filename", default=None, help="Output filename for video")

    # ── New commands ───────────────────────────────────────────────────
    p = subparsers.add_parser("run-code", help="Run a Playwright code snippet")
    p.add_argument("code", help="JavaScript code to execute")

    subparsers.add_parser("show", help="Show browser DevTools")
    subparsers.add_parser("devtools-start", help="Show browser DevTools")
    subparsers.add_parser("config-print")  # Hidden command (no help text)
    p = subparsers.add_parser("install", help="Initialize workspace")
    p.add_argument(
        "--skills",
        action="store_true",
        default=False,
        help="Install skills for claude / github copilot",
    )

    p = subparsers.add_parser("install-browser", help="Install browser")
    p.add_argument(
        "--browser",
        default=None,
        help="Browser or chrome channel to use (chrome, firefox, webkit, msedge)",
    )

    p = subparsers.add_parser(
        "transcribe-audio", help="Transcribe audio from the page"
    )
    p.add_argument("--url", default=None, help="Direct URL to audio file")
    p.add_argument(
        "--filename", default=None, help="Save audio file to this path"
    )

    # ── Session management (client-side) ───────────────────────────────

    p = subparsers.add_parser("list", help="List all sessions")
    p.add_argument(
        "--all", action="store_true", default=False, help="List all browser sessions"
    )

    subparsers.add_parser("close-all", help="Gracefully close all sessions")
    subparsers.add_parser("kill-all", help="Force-kill all sessions")
    subparsers.add_parser("delete-data", help="Delete session data directory")

    p = subparsers.add_parser("logs", help="Show daemon log for a session")
    p.add_argument(
        "-n",
        "--lines",
        type=int,
        default=50,
        help="Number of lines to show (default: 50, 0 for all)",
    )
    p.add_argument(
        "-f", "--follow", action="store_true", help="Follow log output (like tail -f)"
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Parse CLI arguments and dispatch to the appropriate handler."""

    parser = argparse.ArgumentParser(
        prog="patchright-cli",
        description="CLI tool for browser automation via patchright",
    )

    # Global options
    parser.add_argument("-s", "--session", default=None, help="Session name")
    parser.add_argument("--config", default=None, help="Path to config file")
    parser.add_argument("-v", "--version", action="store_true", help="Print version")

    subparsers = parser.add_subparsers(dest="command")
    _register_subcommands(subparsers)

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command is None:
        if hasattr(args, "version") and args.version:
            from patchright_cli.config import get_version

            print(get_version())
            return
        parser.print_help()
        sys.exit(1)

    if args.version:
        from patchright_cli.config import get_version

        print(get_version())
        return

    # 1. Resolve session name
    session_name = resolve_session_name(args.session)

    # 2. Load config
    config = load_config(args.config)

    # 3. Handle client-side commands directly
    if args.command == "list":
        sessions = list_sessions()
        if not sessions:
            print("No sessions found.")
            return
        print("### Browsers")
        for s in sessions:
            status = "open" if s["alive"] else "closed"
            print(f"- {s['name']}:")
            print(f"  - status: {status}")
            cfg = s.get("config")
            if cfg:
                browser_cfg = cfg.get("browser", {})
                browser_type = browser_cfg.get("browser_name", "chromium")
                if browser_cfg.get("isolated"):
                    user_data_dir = "<in-memory>"
                else:
                    user_data_dir = browser_cfg.get("user_data_dir") or str(
                        get_session_dir(s["name"]) / "browser-data"
                    )
                headed = not browser_cfg.get("launch_options", {}).get(
                    "headless", False
                )
                print(f"  - browser-type: {browser_type}")
                print(f"  - user-data-dir: {user_data_dir}")
                print(f"  - headed: {str(headed).lower()}")
        return

    if args.command == "close-all":
        results = close_all_sessions()
        for r in results:
            name = r["name"]
            if r["ok"]:
                print(f"Closed session '{name}'")
            else:
                print(
                    f"Failed to close session '{name}': {r.get('error', '')}",
                    file=sys.stderr,
                )
        return

    if args.command == "kill-all":
        results = kill_all_sessions()
        for r in results:
            name = r["name"]
            if r["ok"]:
                print(r.get("output", f"Killed session '{name}'"))
            else:
                print(
                    f"Failed to kill session '{name}': {r.get('error', '')}",
                    file=sys.stderr,
                )
        return

    if args.command == "delete-data":
        result = delete_session_data(session_name)
        if result["ok"]:
            print(result.get("output", f"Deleted data for session '{session_name}'"))
        else:
            print(
                result.get(
                    "error", f"Failed to delete data for session '{session_name}'"
                ),
                file=sys.stderr,
            )
            sys.exit(1)
        return

    if args.command == "logs":
        import subprocess

        log_path = get_log_path(session_name)
        if not log_path.exists():
            print(f"No log file found for session '{session_name}'.", file=sys.stderr)
            print(f"Expected: {log_path}", file=sys.stderr)
            sys.exit(1)
        if args.follow:
            try:
                subprocess.run(["tail", "-f", str(log_path)], check=False)
            except KeyboardInterrupt:
                pass
        elif args.lines == 0:
            print(log_path.read_text(encoding="utf-8"), end="")
        else:
            subprocess.run(["tail", "-n", str(args.lines), str(log_path)], check=False)
        return

    if args.command == "install":
        if hasattr(args, "skills") and args.skills:
            import shutil

            skills_src = Path(__file__).parent / "skills"
            skills_dst = Path.home() / ".claude" / "skills"
            if not skills_src.is_dir():
                print("Skills data not found in package.", file=sys.stderr)
                sys.exit(1)
            for skill_dir in skills_src.iterdir():
                if skill_dir.is_dir():
                    dst = skills_dst / skill_dir.name
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(skill_dir, dst)
                    print(f"Installed skill '{skill_dir.name}' to {dst}")
            return
        workspace_dir = Path.cwd() / ".playwright"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        print(f"Workspace initialized at {Path.cwd()}.")
        return

    if args.command == "install-browser":
        import subprocess

        cmd = ["patchright", "install"]
        if hasattr(args, "browser") and args.browser:
            cmd.append(args.browser)
        try:
            subprocess.run(cmd, check=True)
        except FileNotFoundError:
            print(
                "patchright command not found. Install patchright first.",
                file=sys.stderr,
            )
            sys.exit(1)
        return

    # 4. Handle `open` specially — merge CLI flags into config
    if args.command == "open":
        if args.browser is not None:
            config.browser.launch_options["channel"] = args.browser
        if args.isolated:
            config.browser.isolated = True
        if args.profile is not None:
            config.browser.user_data_dir = args.profile
        if args.extension is not None:
            config.browser.context_options["extension"] = args.extension
        if args.webgl_renderer is not None:
            config.browser.webgl_renderer = args.webgl_renderer

        result = open_session(
            session_name,
            config.model_dump(),
            url=args.url,
        )
        if result["ok"]:
            print(result.get("output", "Session opened."))
        else:
            print(result.get("error", "Failed to open session."), file=sys.stderr)
            sys.exit(1)
        return

    # 5. All other commands — send to the daemon
    cmd_name = args.command
    args_dict = _args_to_dict(args)

    result = send_command(session_name, cmd_name, args_dict)

    # 6. Print result
    if result["ok"]:
        output = result.get("output", "")
        if output:
            print(output)
    else:
        print(result.get("error", "Unknown error"), file=sys.stderr)
        sys.exit(1)
