"""Asyncio daemon server for patchright-cli.

Manages the browser session and handles all commands via a Unix domain socket.
This is the core module: it owns the BrowserSession (Playwright browser, context,
pages, element refs, dialog queue, console/network logs, route table, tracing state)
and exposes ~50 command handlers dispatched through ``handle_command``.

The server is started as a background daemon process by ``start_daemon`` (called from
``client.py``).  Communication is line-delimited JSON over a Unix socket.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from patchright.async_api import async_playwright

from patchright_cli.config import CLIConfig
from patchright_cli.session import (
    cleanup_session,
    generate_output_filename,
    get_log_path,
    get_output_dir,
    get_session_dir,
    get_socket_path,
    write_pid,
)
from patchright_cli.snapshot import take_snapshot

logger = logging.getLogger("patchright_cli.server")


# ---------------------------------------------------------------------------
# Response builder
# ---------------------------------------------------------------------------


class Response:
    """Builds section-based markdown output matching playwright-cli format."""

    def __init__(self) -> None:
        self._errors: list[str] = []
        self._results: list[str] = []
        self._code: str | None = None
        self._include_snapshot: bool = False
        self._include_full_snapshot: bool = False
        self._full_snapshot_filename: str | None = None
        self._is_snapshot_command: bool = False

    def add_result(self, text: str) -> None:
        self._results.append(text)

    def add_error(self, text: str) -> None:
        self._errors.append(text)

    def add_code(self, code: str) -> None:
        self._code = code

    def set_include_snapshot(self) -> None:
        self._include_snapshot = True

    def set_include_full_snapshot(self, filename: str | None = None) -> None:
        self._include_full_snapshot = True
        self._full_snapshot_filename = filename
        self._is_snapshot_command = True

    async def add_file_result(
        self,
        title: str,
        data: str | bytes,
        prefix: str,
        ext: str,
        filename: str | None = None,
    ) -> None:
        if filename:
            path = Path(filename)
        else:
            path = generate_output_filename(prefix, ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data, encoding="utf-8")
        rel_path = f".patchright-cli/{path.name}"
        self._results.append(f"- [{title}]({rel_path})")

    async def serialize(self, session: BrowserSession) -> str:
        sections: list[str] = []

        if self._errors:
            sections.append("### Error\n" + "\n".join(self._errors))

        if self._results:
            sections.append("### Result\n" + "\n".join(self._results))

        if self._code and session.config.codegen != "none":
            sections.append(f"### Ran Playwright code\n```js\n{self._code}\n```")

        if self._include_snapshot or self._include_full_snapshot:
            page = session.active_page
            if page is not None:
                snapshot_text, refs_dict, new_counter = await take_snapshot(
                    page, session.ref_counter
                )
                session.element_refs.update(refs_dict)
                session.ref_counter = new_counter

                if self._full_snapshot_filename:
                    snapshot_path = Path(self._full_snapshot_filename)
                else:
                    snapshot_path = generate_output_filename("page", "yml")

                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                snapshot_path.write_text(snapshot_text, encoding="utf-8")
                rel_path = f".patchright-cli/{snapshot_path.name}"

                url = page.url
                try:
                    title = await page.title()
                except Exception:
                    title = url

                page_lines = [f"- Page URL: {url}"]
                if title:
                    page_lines.append(f"- Page Title: {title}")
                if self._is_snapshot_command:
                    errors = sum(
                        1 for m in session.console_messages if m.get("type") == "error"
                    )
                    warnings = sum(
                        1
                        for m in session.console_messages
                        if m.get("type") == "warning"
                    )
                    page_lines.append(
                        f"- Console: {errors} errors, {warnings} warnings"
                    )

                page_section = "### Page\n" + "\n".join(page_lines)
                sections.append(page_section)
                sections.append(f"### Snapshot\n- [Snapshot]({rel_path})")

        # Events section - new console messages since last snapshot
        new_console = session.console_messages[session._last_console_index :]
        start_line = session._last_console_index + 1
        session._last_console_index = len(session.console_messages)
        if new_console:
            lines = [
                f"[{m.get('elapsed_ms', 0):>8}ms] [{m.get('type', 'log').upper()}] {m.get('text', '')}{m.get('loc_str', '')}"
                for m in new_console
            ]
            text = "\n".join(lines)
            path = generate_output_filename("console", "log")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            rel_path = f".patchright-cli/{path.name}"
            sections.append(
                f"### Events\n- New console entries: {rel_path}#L{start_line}"
            )

        return "\n".join(sections)


# ---------------------------------------------------------------------------
# BrowserSession
# ---------------------------------------------------------------------------


class BrowserSession:
    """Holds all state for a single daemon-managed browser session."""

    def __init__(self, session_name: str, config: CLIConfig) -> None:
        self.session_name: str = session_name
        self.config: CLIConfig = config

        # Playwright objects
        self.playwright: Any = None
        self.browser: Any = None
        self.context: Any = None
        self.pages: list[Any] = []
        self.active_page_index: int = 0

        # Element reference tracking
        self.element_refs: dict[str, str | dict[str, str | None]] = {}
        self.ref_counter: int = 0

        # Captured events
        self.dialog_queue: list[dict[str, Any]] = []
        self.console_messages: list[dict[str, Any]] = []
        self.network_log: list[dict[str, Any]] = []

        # Console index for event tracking
        self._last_console_index: int = 0

        # Route management
        self.active_routes: dict[str, Any] = {}

        # Tracing
        self.tracing_active: bool = False

        # Timing
        self._start_time: float = 0.0

    # -- Properties ----------------------------------------------------------

    @property
    def active_page(self) -> Any | None:
        """Return the currently active page, or ``None`` if no pages exist."""
        if self.pages:
            # Clamp index just in case
            idx = max(0, min(self.active_page_index, len(self.pages) - 1))
            return self.pages[idx]
        return None

    # -- Browser lifecycle ---------------------------------------------------

    async def launch_browser(self) -> None:
        """Launch browser according to the current config."""
        cfg = self.config
        bcfg = cfg.browser

        self.playwright = await async_playwright().start()

        browser_type = getattr(self.playwright, bcfg.browser_name)

        launch_opts = dict(bcfg.launch_options)
        context_opts = dict(bcfg.context_options)

        # Strip Chromium flags that leak automation detection signals.
        # Patchright's driver adds these by default; ignore_default_args
        # removes them and extra args adds the anti-detection flag.
        if bcfg.browser_name == "chromium":
            _stealth_ignored = [
                "--enable-automation",
                "--disable-popup-blocking",
                "--disable-component-update",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-background-networking",
            ]
            existing = launch_opts.get("ignore_default_args")
            if existing is True:
                pass  # already ignoring all defaults
            elif isinstance(existing, list):
                merged = list(existing)
                for flag in _stealth_ignored:
                    if flag not in merged:
                        merged.append(flag)
                launch_opts["ignore_default_args"] = merged
            else:
                launch_opts["ignore_default_args"] = _stealth_ignored

            args = list(launch_opts.get("args", []))
            if not any("AutomationControlled" in a for a in args):
                args.append("--disable-blink-features=AutomationControlled")
                args.append("--test-type") # this removes the banner that appears from passing the previous arg

            launch_opts["args"] = args

            # Suppress "Google API keys are missing" infobar.
            # Patchright's env param replaces process.env entirely, so
            # we must merge into a copy of the current environment.
            env = {**os.environ, **launch_opts.get("env", {})}
            env.setdefault("GOOGLE_API_KEY", "no")
            env.setdefault("GOOGLE_DEFAULT_CLIENT_ID", "no")
            launch_opts["env"] = env

        # Video recording
        if cfg.save_video is not None:
            context_opts["record_video_dir"] = str(get_output_dir())
            context_opts["record_video_size"] = {
                "width": cfg.save_video.width,
                "height": cfg.save_video.height,
            }

        # ---- Connection strategies -----------------------------------------
        if bcfg.cdp_endpoint:
            # 1. Connect over CDP
            self.browser = await browser_type.connect_over_cdp(
                bcfg.cdp_endpoint,
                headers=bcfg.cdp_headers or None,
                timeout=bcfg.cdp_timeout,
            )
            contexts = self.browser.contexts
            if contexts:
                self.context = contexts[0]
            else:
                self.context = await self.browser.new_context(**context_opts)

        elif bcfg.remote_endpoint:
            # 2. Connect to remote browser
            self.browser = await browser_type.connect(bcfg.remote_endpoint)
            self.context = await self.browser.new_context(**context_opts)

        elif bcfg.user_data_dir or not bcfg.isolated:
            # 3. Persistent context
            user_data = bcfg.user_data_dir or str(
                get_session_dir(self.session_name) / "browser-data"
            )
            self.context = await browser_type.launch_persistent_context(
                user_data,
                **launch_opts,
                **context_opts,
            )
            # Persistent context IS the browser
            self.browser = self.context

        else:
            # 4. Normal isolated launch
            self.browser = await browser_type.launch(**launch_opts)
            self.context = await self.browser.new_context(**context_opts)

        # ---- Post-launch setup ---------------------------------------------
        self.context.on("page", self._on_new_page_sync)

        # Timeouts
        self.context.set_default_timeout(cfg.timeouts.action)
        self.context.set_default_navigation_timeout(cfg.timeouts.navigation)

        # Init scripts
        for script in bcfg.init_script:
            await self.context.add_init_script(script)

        # WebGL renderer spoofing (via route-based HTML injection)
        await self._setup_webgl_override()

        # Network filtering
        await self._setup_network_filtering()

        # Open initial page
        if self.context.pages:
            page = self.context.pages[0]
            if page not in self.pages:
                self.pages.append(page)
        else:
            page = await self.context.new_page()
            # _on_new_page_sync may have added it already
            if page not in self.pages:
                self.pages.append(page)
        self.active_page_index = 0
        await self._setup_page_listeners(page)

        # Navigate to init pages
        for url in bcfg.init_page:
            await page.goto(url, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("load", timeout=5000)
            except Exception:
                pass

        self._start_time = time.time()

    # -- Page event handlers -------------------------------------------------

    def _on_new_page_sync(self, page: Any) -> None:
        """Synchronous callback for the context 'page' event.

        Adds the page to our list (if not already present) and schedules
        listener setup.  Pages created via ``context.new_page()`` fire this
        event *before* ``new_page`` returns, so callers that create pages
        explicitly should check before appending again.
        """
        if page not in self.pages:
            self.pages.append(page)
        asyncio.ensure_future(self._setup_page_listeners(page))

    async def _setup_page_listeners(self, page: Any) -> None:
        """Attach console, dialog, request, and response listeners to *page*."""

        def _on_dialog(dialog: Any) -> None:
            self.dialog_queue.append(
                {
                    "type": dialog.type,
                    "message": dialog.message,
                    "default_value": dialog.default_value,
                    "dialog": dialog,
                }
            )

        def _on_console(msg: Any) -> None:
            elapsed_ms = (
                int((time.time() - self._start_time) * 1000) if self._start_time else 0
            )
            location = msg.location
            loc_str = ""
            if location:
                loc_url = (
                    location.get("url", "")
                    if isinstance(location, dict)
                    else str(location)
                )
                loc_line = (
                    location.get("lineNumber", "") if isinstance(location, dict) else ""
                )
                if loc_url:
                    loc_str = f" @ {loc_url}"
                    if loc_line:
                        loc_str += f":{loc_line}"
            self.console_messages.append(
                {
                    "type": msg.type,
                    "text": msg.text,
                    "location": str(msg.location),
                    "elapsed_ms": elapsed_ms,
                    "loc_str": loc_str,
                }
            )

        def _on_request(req: Any) -> None:
            self.network_log.append(
                {
                    "method": req.method,
                    "url": req.url,
                    "resource_type": req.resource_type,
                    "timestamp": time.time(),
                    "status": None,
                }
            )

        def _on_response(resp: Any) -> None:
            url = resp.url
            # Walk backwards to find the matching request entry
            for entry in reversed(self.network_log):
                if entry["url"] == url and entry["status"] is None:
                    entry["status"] = resp.status
                    break

        page.on("dialog", _on_dialog)
        page.on("console", _on_console)
        page.on("request", _on_request)
        page.on("response", _on_response)

    # -- WebGL renderer spoofing ---------------------------------------------

    def _webgl_override_script(self) -> str | None:
        """Return the WebGL override JS snippet, or ``None`` if not configured."""
        renderer = self.config.browser.webgl_renderer
        if not renderer:
            return None

        # Extract vendor from renderer string: "ANGLE (NVIDIA Corporation, ...)"
        # -> "Google Inc. (NVIDIA Corporation)" or fall back to a generic vendor.
        vendor = "Google Inc. (NVIDIA)"
        if "(" in renderer:
            inner = renderer.split("(", 1)[1]
            vendor_part = inner.split(",", 1)[0].strip()
            vendor = f"Google Inc. ({vendor_part})"

        return (
            "(function(){"
            "var v=" + json.dumps(vendor) + ";"
            "var r=" + json.dumps(renderer) + ";"
            "var G=WebGLRenderingContext.prototype;"
            "var G2=WebGL2RenderingContext.prototype;"
            "var origG=G.getParameter;"
            "var origG2=G2.getParameter;"
            "function mk(orig){"
            "return function(p){"
            "if(p===37445)return v;"
            "if(p===37446)return r;"
            "return orig.call(this,p);"
            "};"
            "}"
            "G.getParameter=mk(origG);"
            "G2.getParameter=mk(origG2);"
            "var origTS=Function.prototype.toString;"
            "var patched=new Set([G.getParameter,G2.getParameter]);"
            "Function.prototype.toString=function(){"
            "if(patched.has(this))return'function getParameter() { [native code] }';"
            "if(this===Function.prototype.toString)return origTS.call(origTS);"
            "return origTS.call(this);"
            "};"
            "patched.add(Function.prototype.toString);"
            "})();"
        )

    async def _setup_webgl_override(self) -> None:
        """Inject WebGL renderer override via context route.

        Intercepts HTML document responses and prepends a ``<script>`` tag
        that overrides ``getParameter`` on both WebGL rendering contexts.
        This avoids CDP methods (which patchright neuters) and
        ``add_init_script`` (which breaks DNS in patchright).
        """
        script = self._webgl_override_script()
        if not script:
            return

        logger.debug("Setting up WebGL renderer override via route injection")
        script_tag = f"<script>{script}</script>"

        async def _inject_route(route: Any) -> None:
            try:
                response = await route.fetch()
                content_type = response.headers.get("content-type", "")
                if "text/html" in content_type:
                    body = await response.text()
                    # Inject before first <script> or at start of <head>
                    lower = body.lower()
                    idx = lower.find("<script")
                    if idx == -1:
                        idx = lower.find("<head")
                        if idx != -1:
                            idx = lower.find(">", idx) + 1
                    if idx > 0:
                        body = body[:idx] + script_tag + body[idx:]
                    await route.fulfill(response=response, body=body)
                else:
                    await route.fulfill(response=response)
            except Exception:
                await route.continue_()

        await self.context.route("**/*", _inject_route)

    # -- Network filtering ---------------------------------------------------

    async def _setup_network_filtering(self) -> None:
        """Apply allowed/blocked origin rules from config."""
        allowed = self.config.network.allowed_origins
        blocked = self.config.network.blocked_origins

        if not allowed and not blocked:
            return

        async def _filter_route(route: Any) -> None:
            url = route.request.url
            if allowed:
                if any(origin in url for origin in allowed):
                    await route.continue_()
                else:
                    await route.abort()
                return
            if blocked:
                if any(origin in url for origin in blocked):
                    await route.abort()
                else:
                    await route.continue_()
                return
            await route.continue_()

        await self.context.route("**/*", _filter_route)

    # -- Ref resolution ------------------------------------------------------

    def _resolve_ref(self, ref: str) -> str:
        """Return the CSS selector for the given element ref.

        Raises ``ValueError`` if the ref is not found.
        """
        entry = self.element_refs.get(ref)
        if entry is None:
            raise ValueError(
                f"Element ref '{ref}' not found. Take a new snapshot to get "
                f"current refs."
            )
        if isinstance(entry, dict):
            return entry["selector"]
        return entry  # backward compat for plain string

    def _ref_to_code(self, ref: str) -> str:
        """Return a semantic JS locator expression for *ref*.

        If the ref has role/name metadata, generates
        ``page.getByRole('link', { name: 'Learn more' })``.
        Falls back to ``page.locator('aria-ref=eN')``
        for plain-string entries.
        """
        entry = self.element_refs.get(ref)
        if entry is None:
            return f"page.locator('aria-ref={ref}')"
        if isinstance(entry, dict):
            role = entry.get("role")
            name = entry.get("name")
            if role and name:
                escaped = name.replace("'", "\\'")
                return f"page.getByRole('{role}', {{ name: '{escaped}' }})"
            elif role:
                return f"page.getByRole('{role}')"
        return f"page.locator('{self._resolve_ref(ref)}')"

    # -- Command dispatch ----------------------------------------------------

    async def handle_command(self, cmd: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch *cmd* to the appropriate ``cmd_*`` handler."""
        method_name = f"cmd_{cmd.replace('-', '_')}"
        handler = getattr(self, method_name, None)
        if handler is None:
            return {"ok": False, "error": f"Unknown command: {cmd}"}
        try:
            result = await handler(**args)
            return result
        except Exception as exc:
            return {"ok": False, "error": f"{exc}\n{traceback.format_exc()}"}

    # -----------------------------------------------------------------------
    # Command handlers
    # -----------------------------------------------------------------------

    # -- Core ---------------------------------------------------------------

    async def cmd_open(
        self,
        url: str | None = None,
        headless: bool = False,
        browser: str | None = None,
        isolated: bool = False,
        profile: str | None = None,
        config_path: str | None = None,
        extension: str | None = None,
        persistent: bool = False,
    ) -> dict[str, Any]:
        """Launch the browser and optionally navigate to *url*."""
        # Apply overrides to config before launch
        if headless:
            self.config.browser.launch_options["headless"] = True
            self.config.browser.context_options.pop("no_viewport", None)
        if browser:
            self.config.browser.launch_options["channel"] = browser
        if isolated:
            self.config.browser.isolated = True
        if profile:
            self.config.browser.user_data_dir = profile

        await self.launch_browser()

        if url:
            await self.active_page.goto(url, wait_until="domcontentloaded")
            try:
                await self.active_page.wait_for_load_state("load", timeout=5000)
            except Exception:
                pass

        # Build browser info header
        import os as _os

        pid = _os.getpid()
        bcfg = self.config.browser
        headed = not bcfg.launch_options.get("headless", False)
        if bcfg.isolated:
            user_data = bcfg.user_data_dir or "<in-memory>"
        else:
            user_data = bcfg.user_data_dir or str(
                get_session_dir(self.session_name) / "browser-data"
            )

        info = (
            f"### Browser `{self.session_name}` opened with pid {pid}.\n"
            f"- {self.session_name}:\n"
            f"  - browser-type: {bcfg.browser_name}\n"
            f"  - user-data-dir: {user_data}\n"
            f"  - headed: {str(headed).lower()}\n"
            f"---"
        )

        response = Response()
        response.set_include_snapshot()
        output = await response.serialize(self)
        return {"ok": True, "output": f"{info}\n\n{output}"}

    async def cmd_goto(self, url: str) -> dict[str, Any]:
        """Navigate the active page to *url*."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.goto(url, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("load", timeout=5000)
        except Exception:
            pass
        response = Response()
        response.add_code(f"await page.goto('{url}');")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_close(self) -> dict[str, Any]:
        """Close browser and signal daemon shutdown."""
        try:
            if self.context and self.context != self.browser:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
        return {"ok": True, "output": f"Browser '{self.session_name}' closed\n"}

    async def cmd_type(self, text: str, submit: bool = False) -> dict[str, Any]:
        """Type *text* using the keyboard on the active page."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.keyboard.type(text)
        if submit:
            await page.keyboard.press("Enter")
        response = Response()
        code = f"await page.keyboard.type('{text}');"
        if submit:
            code += "\nawait page.keyboard.press('Enter');"
        response.add_code(code)
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_click(
        self, ref: str, button: str = "left", modifiers: list[str] | None = None
    ) -> dict[str, Any]:
        """Click on the element identified by *ref*."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        selector = self._resolve_ref(ref)
        click_kwargs: dict[str, Any] = {"button": button}
        if modifiers:
            click_kwargs["modifiers"] = modifiers
        await page.locator(selector).click(**click_kwargs)
        response = Response()
        response.add_code(f"await {self._ref_to_code(ref)}.click();")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_dblclick(
        self, ref: str, button: str = "left", modifiers: list[str] | None = None
    ) -> dict[str, Any]:
        """Double-click on the element identified by *ref*."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        selector = self._resolve_ref(ref)
        dblclick_kwargs: dict[str, Any] = {"button": button}
        if modifiers:
            dblclick_kwargs["modifiers"] = modifiers
        await page.locator(selector).dblclick(**dblclick_kwargs)
        response = Response()
        response.add_code(f"await {self._ref_to_code(ref)}.dblclick();")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_fill(
        self, ref: str, text: str, submit: bool = False
    ) -> dict[str, Any]:
        """Fill the element identified by *ref* with *text*."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        selector = self._resolve_ref(ref)
        await page.locator(selector).fill(text)
        if submit:
            await page.keyboard.press("Enter")
        response = Response()
        code = f"await {self._ref_to_code(ref)}.fill('{text}');"
        if submit:
            code += "\nawait page.keyboard.press('Enter');"
        response.add_code(code)
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_drag(self, start_ref: str, end_ref: str) -> dict[str, Any]:
        """Drag from *start_ref* to *end_ref*."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        start_sel = self._resolve_ref(start_ref)
        end_sel = self._resolve_ref(end_ref)
        await page.drag_and_drop(start_sel, end_sel)
        response = Response()
        start_code = self._ref_to_code(start_ref)
        end_code = self._ref_to_code(end_ref)
        response.add_code(f"await {start_code}.dragTo({end_code});")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_hover(self, ref: str) -> dict[str, Any]:
        """Hover over the element identified by *ref*."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        selector = self._resolve_ref(ref)
        await page.locator(selector).hover()
        response = Response()
        response.add_code(f"await {self._ref_to_code(ref)}.hover();")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_select(self, ref: str, value: str) -> dict[str, Any]:
        """Select an option by *value* in the element identified by *ref*."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        selector = self._resolve_ref(ref)
        await page.locator(selector).select_option(value)
        response = Response()
        response.add_code(f"await {self._ref_to_code(ref)}.selectOption('{value}');")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_upload(self, file: str) -> dict[str, Any]:
        """Upload a file via a file input on the page."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        file_input = page.locator('input[type="file"]')
        await file_input.set_input_files(file)
        response = Response()
        response.add_code(
            f"await page.locator('input[type=\"file\"]').setInputFiles('{file}');"
        )
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_check(self, ref: str) -> dict[str, Any]:
        """Check the checkbox identified by *ref*."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        selector = self._resolve_ref(ref)
        await page.locator(selector).check()
        response = Response()
        response.add_code(f"await {self._ref_to_code(ref)}.check();")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_uncheck(self, ref: str) -> dict[str, Any]:
        """Uncheck the checkbox identified by *ref*."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        selector = self._resolve_ref(ref)
        await page.locator(selector).uncheck()
        response = Response()
        response.add_code(f"await {self._ref_to_code(ref)}.uncheck();")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_snapshot(self, filename: str | None = None) -> dict[str, Any]:
        """Take a DOM snapshot, optionally saving to *filename*."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        response = Response()
        response.set_include_full_snapshot(filename)
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_eval(self, expression: str, ref: str | None = None) -> dict[str, Any]:
        """Evaluate a JavaScript *expression*, optionally scoped to *ref*."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        if ref:
            selector = self._resolve_ref(ref)
            result = await page.locator(selector).evaluate(expression)
        else:
            result = await page.evaluate(expression)
        response = Response()
        response.add_result(json.dumps(result, default=str))
        response.add_code(f"await page.evaluate('() => ({expression})');")
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_dialog_accept(self, prompt_text: str | None = None) -> dict[str, Any]:
        """Accept the oldest pending dialog."""
        if not self.dialog_queue:
            return {"ok": False, "error": "No dialog to accept."}
        entry = self.dialog_queue.pop(0)
        dialog = entry["dialog"]
        if prompt_text is not None:
            await dialog.accept(prompt_text)
        else:
            await dialog.accept()
        response = Response()
        if prompt_text is not None:
            response.add_code(f"await page.dialog.accept('{prompt_text}');")
        else:
            response.add_code("await page.dialog.accept();")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_dialog_dismiss(self) -> dict[str, Any]:
        """Dismiss the oldest pending dialog."""
        if not self.dialog_queue:
            return {"ok": False, "error": "No dialog to dismiss."}
        entry = self.dialog_queue.pop(0)
        dialog = entry["dialog"]
        await dialog.dismiss()
        response = Response()
        response.add_code("await page.dialog.dismiss();")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_resize(self, width: int, height: int) -> dict[str, Any]:
        """Resize the active page viewport."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.set_viewport_size({"width": int(width), "height": int(height)})
        response = Response()
        response.add_code(
            f"await page.setViewportSize({{width: {int(width)}, height: {int(height)}}});"
        )
        return {"ok": True, "output": await response.serialize(self)}

    # -- Navigation ----------------------------------------------------------

    async def cmd_go_back(self) -> dict[str, Any]:
        """Navigate back in history."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.go_back()
        response = Response()
        response.add_code("await page.goBack();")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_go_forward(self) -> dict[str, Any]:
        """Navigate forward in history."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.go_forward()
        response = Response()
        response.add_code("await page.goForward();")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_reload(self) -> dict[str, Any]:
        """Reload the active page."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.reload()
        response = Response()
        response.add_code("await page.reload();")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    # -- Keyboard ------------------------------------------------------------

    async def cmd_press(self, key: str) -> dict[str, Any]:
        """Press a key (e.g. ``Enter``, ``Tab``, ``ArrowDown``)."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.keyboard.press(key)
        response = Response()
        response.add_code(f"await page.keyboard.press('{key}');")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_keydown(self, key: str) -> dict[str, Any]:
        """Dispatch a key-down event."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.keyboard.down(key)
        response = Response()
        response.add_code(f"await page.keyboard.down('{key}');")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_keyup(self, key: str) -> dict[str, Any]:
        """Dispatch a key-up event."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.keyboard.up(key)
        response = Response()
        response.add_code(f"await page.keyboard.up('{key}');")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    # -- Mouse ---------------------------------------------------------------

    async def cmd_mousemove(self, x: float, y: float) -> dict[str, Any]:
        """Move the mouse to (*x*, *y*)."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.mouse.move(float(x), float(y))
        response = Response()
        response.add_code(f"await page.mouse.move({x}, {y});")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_mousedown(self, button: str = "left") -> dict[str, Any]:
        """Press a mouse button down."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.mouse.down(button=button)
        response = Response()
        response.add_code(f"await page.mouse.down({{button: '{button}'}});")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_mouseup(self, button: str = "left") -> dict[str, Any]:
        """Release a mouse button."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.mouse.up(button=button)
        response = Response()
        response.add_code(f"await page.mouse.up({{button: '{button}'}});")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_mousewheel(self, dx: float, dy: float) -> dict[str, Any]:
        """Scroll the mouse wheel by (*dx*, *dy*)."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.mouse.wheel(float(dx), float(dy))
        response = Response()
        response.add_code(f"await page.mouse.wheel({dx}, {dy});")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    # -- Save as -------------------------------------------------------------

    async def cmd_screenshot(
        self,
        ref: str | None = None,
        filename: str | None = None,
        full_page: bool = False,
    ) -> dict[str, Any]:
        """Take a screenshot of the page or a specific element."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        response = Response()
        if ref:
            selector = self._resolve_ref(ref)
            data = await page.locator(selector).screenshot()
            response.add_code(f"await {self._ref_to_code(ref)}.screenshot();")
        else:
            data = await page.screenshot(full_page=full_page)
            # Determine output path for code display
            if filename:
                screenshot_path = filename
            else:
                screenshot_path = str(generate_output_filename("page", "png"))
            opts_parts = [f"path: '{screenshot_path}'", "scale: 'css'", "type: 'png'"]
            if full_page:
                opts_parts.append("fullPage: true")
            opts = ", ".join(opts_parts)
            response.add_code(f"await page.screenshot({{ {opts} }});")
        await response.add_file_result(
            "Screenshot of viewport", data, "page", "png", filename
        )
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_pdf(self, filename: str | None = None) -> dict[str, Any]:
        """Save the active page as a PDF."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        response = Response()
        data = await page.pdf()
        await response.add_file_result("Page as pdf", data, "page", "pdf", filename)
        response.add_code("await page.pdf();")
        return {"ok": True, "output": await response.serialize(self)}

    # -- Tabs ----------------------------------------------------------------

    async def cmd_tab_list(self) -> dict[str, Any]:
        """List all open tabs/pages."""
        lines: list[str] = []
        for i, page in enumerate(self.pages):
            marker = "(current) " if i == self.active_page_index else ""
            url = page.url
            try:
                title = await page.title()
            except Exception:
                title = url
            lines.append(f"- {i}: {marker}[{title}]({url})")
        response = Response()
        response.add_result("\n".join(lines))
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_tab_new(self, url: str | None = None) -> dict[str, Any]:
        """Open a new tab, optionally navigating to *url*."""
        page = await self.context.new_page()
        # _on_new_page_sync already appended the page via the "page" event
        if page not in self.pages:
            self.pages.append(page)
        self.active_page_index = self.pages.index(page)
        if url:
            await page.goto(url, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("load", timeout=5000)
            except Exception:
                pass
        response = Response()
        response.add_code("const page = await context.newPage();")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_tab_close(self, index: int | None = None) -> dict[str, Any]:
        """Close the tab at *index* (default: active tab)."""
        if index is None:
            index = self.active_page_index
        index = int(index)
        if index < 0 or index >= len(self.pages):
            return {"ok": False, "error": f"Invalid tab index: {index}"}
        page = self.pages.pop(index)
        await page.close()
        # Adjust active index
        if not self.pages:
            self.active_page_index = 0
            return {"ok": True, "output": "All tabs closed."}
        if self.active_page_index >= len(self.pages):
            self.active_page_index = len(self.pages) - 1
        elif self.active_page_index > index:
            self.active_page_index -= 1
        response = Response()
        response.add_code("await page.close();")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_tab_select(self, index: int) -> dict[str, Any]:
        """Switch to the tab at *index*."""
        index = int(index)
        if index < 0 or index >= len(self.pages):
            return {"ok": False, "error": f"Invalid tab index: {index}"}
        self.active_page_index = index
        page = self.pages[index]
        await page.bring_to_front()
        response = Response()
        response.add_code("await page.bringToFront();")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    # -- Storage: state ------------------------------------------------------

    async def cmd_state_save(self, filename: str | None = None) -> dict[str, Any]:
        """Save browser storage state to a JSON file."""
        if filename:
            path = Path(filename)
        else:
            path = generate_output_filename("state", "json")
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.context.storage_state(path=str(path))
        response = Response()
        response.add_result(f"Storage state saved to {path}")
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_state_load(self, filename: str) -> dict[str, Any]:
        """Load storage state from a JSON file by creating a new context."""
        path = Path(filename)
        if not path.is_file():
            return {"ok": False, "error": f"File not found: {filename}"}

        # Close current context
        old_context = self.context
        context_opts = dict(self.config.browser.context_options)
        context_opts["storage_state"] = str(path)

        if self.config.save_video is not None:
            context_opts["record_video_dir"] = str(get_output_dir())
            context_opts["record_video_size"] = {
                "width": self.config.save_video.width,
                "height": self.config.save_video.height,
            }

        self.context = await self.browser.new_context(**context_opts)
        self.context.on("page", self._on_new_page_sync)
        self.context.set_default_timeout(self.config.timeouts.action)
        self.context.set_default_navigation_timeout(self.config.timeouts.navigation)

        # Re-apply init scripts
        for script in self.config.browser.init_script:
            await self.context.add_init_script(script)

        # Close old context (after new one is ready)
        try:
            await old_context.close()
        except Exception:
            pass

        # Open a page
        page = await self.context.new_page()
        self.pages = [page]
        self.active_page_index = 0
        await self._setup_page_listeners(page)

        # Reset refs
        self.element_refs = {}
        self.ref_counter = 0

        response = Response()
        response.add_result(f"State loaded from {path}")
        response.set_include_snapshot()
        return {"ok": True, "output": await response.serialize(self)}

    # -- Storage: cookies ----------------------------------------------------

    async def cmd_cookie_list(
        self, domain: str | None = None, path: str | None = None
    ) -> dict[str, Any]:
        """List cookies, optionally filtered by *domain* and/or *path*."""
        cookies = await self.context.cookies()
        if domain:
            cookies = [c for c in cookies if domain in c.get("domain", "")]
        if path:
            cookies = [c for c in cookies if c.get("path", "") == path]
        response = Response()
        lines = [
            f"{c['name']}={c['value']} (domain: {c.get('domain', '')}, path: {c.get('path', '')})"
            for c in cookies
        ]
        response.add_result("\n".join(lines) if lines else "No cookies.")
        response.add_code("await page.context().cookies();")
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_cookie_get(self, name: str) -> dict[str, Any]:
        """Get a specific cookie by *name*."""
        cookies = await self.context.cookies()
        matches = [c for c in cookies if c.get("name") == name]
        if not matches:
            return {"ok": False, "error": f"Cookie '{name}' not found."}
        response = Response()
        lines = []
        for c in matches:
            lines.append(
                f"{c['name']}={c['value']} (domain: {c.get('domain', '')}, "
                f"path: {c.get('path', '')}, httpOnly: {c.get('httpOnly', False)}, "
                f"secure: {c.get('secure', False)}, sameSite: {c.get('sameSite', 'None')})"
            )
        response.add_result("\n".join(lines))
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_cookie_set(
        self,
        name: str,
        value: str,
        domain: str | None = None,
        path: str | None = None,
        expires: float | None = None,
        httpOnly: bool = False,
        secure: bool = False,
        sameSite: str | None = None,
    ) -> dict[str, Any]:
        """Set a cookie."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        url = page.url
        cookie: dict[str, Any] = {"name": name, "value": value, "url": url}
        if domain is not None:
            cookie["domain"] = domain
        if path is not None:
            cookie["path"] = path
        if expires is not None:
            cookie["expires"] = expires
        if httpOnly:
            cookie["httpOnly"] = True
        if secure:
            cookie["secure"] = True
        if sameSite is not None:
            cookie["sameSite"] = sameSite
        await self.context.add_cookies([cookie])
        response = Response()
        response.add_result(f"Cookie '{name}' set.")
        response.add_code(
            f"await page.context().addCookies([{{name: '{name}', value: '{value}'}}]);"
        )
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_cookie_delete(self, name: str) -> dict[str, Any]:
        """Delete a cookie by *name*."""
        await self.context.clear_cookies(name=name)
        response = Response()
        response.add_result(f"Cookie '{name}' deleted.")
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_cookie_clear(self) -> dict[str, Any]:
        """Clear all cookies."""
        await self.context.clear_cookies()
        response = Response()
        response.add_result("All cookies cleared.")
        return {"ok": True, "output": await response.serialize(self)}

    # -- Storage: localStorage -----------------------------------------------

    async def cmd_localstorage_list(self) -> dict[str, Any]:
        """List all localStorage entries."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        result = await page.evaluate("JSON.stringify(Object.entries(localStorage))")
        entries = json.loads(result) if isinstance(result, str) else result
        formatted = json.dumps(entries, indent=2, default=str)
        response = Response()
        response.add_result(f"### localStorage\n```json\n{formatted}\n```")
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_localstorage_get(self, key: str) -> dict[str, Any]:
        """Get a value from localStorage by *key*."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        result = await page.evaluate(f"localStorage.getItem({json.dumps(key)})")
        response = Response()
        response.add_result(json.dumps(result, default=str))
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_localstorage_set(self, key: str, value: str) -> dict[str, Any]:
        """Set a localStorage entry."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.evaluate(
            f"localStorage.setItem({json.dumps(key)}, {json.dumps(value)})"
        )
        response = Response()
        response.add_result(f"localStorage[{key!r}] set.")
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_localstorage_delete(self, key: str) -> dict[str, Any]:
        """Delete a localStorage entry by *key*."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.evaluate(f"localStorage.removeItem({json.dumps(key)})")
        response = Response()
        response.add_result(f"localStorage[{key!r}] deleted.")
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_localstorage_clear(self) -> dict[str, Any]:
        """Clear all localStorage entries."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.evaluate("localStorage.clear()")
        response = Response()
        response.add_result("localStorage cleared.")
        return {"ok": True, "output": await response.serialize(self)}

    # -- Storage: sessionStorage ---------------------------------------------

    async def cmd_sessionstorage_list(self) -> dict[str, Any]:
        """List all sessionStorage entries."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        result = await page.evaluate("JSON.stringify(Object.entries(sessionStorage))")
        entries = json.loads(result) if isinstance(result, str) else result
        formatted = json.dumps(entries, indent=2, default=str)
        response = Response()
        response.add_result(f"### sessionStorage\n```json\n{formatted}\n```")
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_sessionstorage_get(self, key: str) -> dict[str, Any]:
        """Get a value from sessionStorage by *key*."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        result = await page.evaluate(f"sessionStorage.getItem({json.dumps(key)})")
        response = Response()
        response.add_result(json.dumps(result, default=str))
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_sessionstorage_set(self, key: str, value: str) -> dict[str, Any]:
        """Set a sessionStorage entry."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.evaluate(
            f"sessionStorage.setItem({json.dumps(key)}, {json.dumps(value)})"
        )
        response = Response()
        response.add_result(f"sessionStorage[{key!r}] set.")
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_sessionstorage_delete(self, key: str) -> dict[str, Any]:
        """Delete a sessionStorage entry by *key*."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.evaluate(f"sessionStorage.removeItem({json.dumps(key)})")
        response = Response()
        response.add_result(f"sessionStorage[{key!r}] deleted.")
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_sessionstorage_clear(self) -> dict[str, Any]:
        """Clear all sessionStorage entries."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        await page.evaluate("sessionStorage.clear()")
        response = Response()
        response.add_result("sessionStorage cleared.")
        return {"ok": True, "output": await response.serialize(self)}

    # -- Network: routes -----------------------------------------------------

    async def cmd_route(
        self,
        pattern: str,
        body: str | None = None,
        status: int | None = None,
        content_type: str | None = None,
        header: list[str] | None = None,
        remove_header: str | None = None,
    ) -> dict[str, Any]:
        """Intercept requests matching *pattern* and fulfill with a custom response."""
        # If header/remove_header specified, use continue with modified headers
        if header or remove_header:
            headers_to_add = {}
            if header:
                for h in header:
                    parts = h.split(":", 1)
                    if len(parts) == 2:
                        headers_to_add[parts[0].strip()] = parts[1].strip()
            headers_to_remove = []
            if remove_header:
                headers_to_remove = [h.strip() for h in remove_header.split(",")]

            async def _header_handler(route: Any) -> None:
                headers = {**route.request.headers, **headers_to_add}
                for name in headers_to_remove:
                    headers.pop(name, None)
                await route.continue_(headers=headers)

        else:

            async def _header_handler(route: Any) -> None:
                fulfill_kwargs: dict[str, Any] = {}
                if body is not None:
                    fulfill_kwargs["body"] = body
                if status is not None:
                    fulfill_kwargs["status"] = int(status)
                if content_type is not None:
                    fulfill_kwargs["content_type"] = content_type
                await route.fulfill(**fulfill_kwargs)

        await self.context.route(pattern, _header_handler)
        self.active_routes[pattern] = _header_handler
        response = Response()
        response.add_result(f"Route added for pattern: {pattern}")
        response.add_code(f"await page.route('{pattern}', handler);")
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_route_list(self) -> dict[str, Any]:
        """List all active route patterns."""
        response = Response()
        if not self.active_routes:
            response.add_result("No active routes")
        else:
            lines = [f"  - {p}" for p in self.active_routes]
            response.add_result("\n".join(lines))
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_unroute(self, pattern: str | None = None) -> dict[str, Any]:
        """Remove route(s). If *pattern* is given, remove that one; otherwise all."""
        if pattern is not None:
            handler = self.active_routes.pop(pattern, None)
            if handler is None:
                return {"ok": False, "error": f"No active route for: {pattern}"}
            await self.context.unroute(pattern, handler)
            response = Response()
            response.add_result(f"Route removed: {pattern}")
            return {"ok": True, "output": await response.serialize(self)}
        else:
            for p, h in self.active_routes.items():
                await self.context.unroute(p, h)
            self.active_routes.clear()
            response = Response()
            response.add_result("All routes removed.")
            return {"ok": True, "output": await response.serialize(self)}

    # -- DevTools ------------------------------------------------------------

    async def cmd_console(
        self, min_level: str | None = None, clear: bool = False
    ) -> dict[str, Any]:
        """Return buffered console messages, optionally filtered by level."""
        if clear:
            self.console_messages.clear()
            self._last_console_index = 0
            return {"ok": True, "output": "Console cleared."}
        LEVEL_ORDER = {"debug": 0, "log": 1, "info": 2, "warning": 3, "error": 4}
        messages = self.console_messages
        if min_level and min_level in LEVEL_ORDER:
            threshold = LEVEL_ORDER[min_level]
            messages = [
                m
                for m in messages
                if LEVEL_ORDER.get(m.get("type", "log"), 1) >= threshold
            ]
        if not messages:
            return {"ok": True, "output": "No console messages."}
        text = "\n".join(
            f"[{m.get('elapsed_ms', 0):>8}ms] [{m.get('type', 'log').upper()}] {m.get('text', '')}{m.get('loc_str', '')}"
            for m in messages
        )
        response = Response()
        await response.add_file_result("Console", text, "console", "log")
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_network(
        self, static: bool = False, clear: bool = False
    ) -> dict[str, Any]:
        """Return the buffered network log."""
        if clear:
            self.network_log.clear()
            return {"ok": True, "output": "Network log cleared."}
        STATIC_TYPES = {"image", "font", "stylesheet", "script", "media"}
        entries = self.network_log
        if not static:
            entries = [
                e
                for e in entries
                if e.get("resource_type", "") not in STATIC_TYPES
                or e.get("status") not in range(200, 300)
            ]
        if not entries:
            return {"ok": True, "output": "No network requests recorded."}
        lines = [
            f"{e.get('status', '?')} {e.get('method', '?')} {e.get('url', '?')} ({e.get('resource_type', '')})"
            for e in entries
        ]
        text = "\n".join(lines)
        response = Response()
        await response.add_file_result("Network", text, "network", "log")
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_tracing_start(self) -> dict[str, Any]:
        """Start tracing (screenshots + snapshots)."""
        if self.tracing_active:
            return {"ok": False, "error": "Tracing is already active."}
        await self.context.tracing.start(screenshots=True, snapshots=True)
        self.tracing_active = True
        response = Response()
        response.add_result("Tracing started.")
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_tracing_stop(self) -> dict[str, Any]:
        """Stop tracing and save the trace file."""
        if not self.tracing_active:
            return {"ok": False, "error": "Tracing is not active."}
        path = generate_output_filename("trace", "zip")
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.context.tracing.stop(path=str(path))
        self.tracing_active = False
        response = Response()
        response.add_result(f"Trace saved to {path}")
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_video_start(self) -> dict[str, Any]:
        """Note: video recording is configured at context level."""
        if self.config.save_video is None:
            return {
                "ok": False,
                "error": (
                    "Video recording is not enabled. Set save_video in config "
                    "(e.g. '1280x720') before launching the browser."
                ),
            }
        response = Response()
        response.add_result(
            "Video recording is active (configured at context level). "
            "Use video-stop to save the current page's video."
        )
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_video_stop(self, filename: str | None = None) -> dict[str, Any]:
        """Save the active page's video."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        video = page.video
        if video is None:
            return {
                "ok": False,
                "error": "No video is being recorded for this page.",
            }
        if filename:
            path = Path(filename)
        else:
            path = generate_output_filename("video", "webm")
        path.parent.mkdir(parents=True, exist_ok=True)
        await video.save_as(str(path))
        response = Response()
        response.add_result(f"Video saved to {path}")
        return {"ok": True, "output": await response.serialize(self)}

    # -- New commands --------------------------------------------------------

    async def cmd_run_code(self, code: str) -> dict[str, Any]:
        """Run arbitrary Playwright code."""
        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}
        result = await page.evaluate(f"async (page) => {{ {code} }}")
        response = Response()
        if result is not None:
            response.add_result(json.dumps(result, default=str))
        response.add_code(code)
        return {"ok": True, "output": await response.serialize(self)}

    async def cmd_show(self) -> dict[str, Any]:
        """Show DevTools."""
        return {"ok": True, "output": "DevTools are not available in daemon mode."}

    async def cmd_devtools_start(self) -> dict[str, Any]:
        """Start DevTools."""
        return {"ok": True, "output": "DevTools are not available in daemon mode."}

    async def cmd_config_print(self) -> dict[str, Any]:
        """Print the current configuration."""
        return {"ok": True, "output": self.config.model_dump_json(indent=2)}

    async def cmd_transcribe_audio(
        self, url: str | None = None, filename: str | None = None
    ) -> dict[str, Any]:
        """Transcribe audio from the page or a given URL using OpenAI Whisper."""
        import os

        from patchright_cli.captcha import find_audio_url, transcribe_audio

        page = self.active_page
        if page is None:
            return {"ok": False, "error": "No active page."}

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return {
                "ok": False,
                "error": "OPENAI_API_KEY environment variable is not set.",
            }

        audio_url = url
        if not audio_url:
            audio_url = await find_audio_url(page)
        if not audio_url:
            return {
                "ok": False,
                "error": "No audio element found on the page. Use --url to specify a direct URL.",
            }

        resp = await self.context.request.get(audio_url)
        audio_bytes = await resp.body()

        response = Response()

        if filename:
            await response.add_file_result(
                "Audio file", audio_bytes, "audio", "wav", filename
            )

        text = await transcribe_audio(audio_bytes, api_key)
        response.add_result(text)
        return {"ok": True, "output": await response.serialize(self)}


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------


async def run_server(session_name: str, config_dict: dict[str, Any]) -> None:
    """Main daemon entry point. Creates BrowserSession, starts Unix socket server."""
    config = CLIConfig(**config_dict)
    session = BrowserSession(session_name, config)
    logger.info(f"BrowserSession created for {session_name!r}")

    # Persist config to session dir for `list` command
    config_path = get_session_dir(session_name) / "config.json"
    config_path.write_text(config.model_dump_json(indent=2), encoding="utf-8")

    socket_path = get_socket_path(session_name)
    # Remove stale socket
    if socket_path.exists():
        socket_path.unlink()

    server: asyncio.AbstractServer | None = None

    async def handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        nonlocal server
        try:
            data = await reader.readline()
            if not data:
                writer.close()
                await writer.wait_closed()
                return

            request = json.loads(data.decode())
            cmd = request.get("cmd", "")
            args = request.get("args", {})
            logger.debug(f"Received command: {cmd} args={args}")

            try:
                result = await session.handle_command(cmd, args)
            except Exception as e:
                logger.exception(f"Command {cmd!r} raised an exception")
                result = {"ok": False, "error": str(e)}

            ok = result.get("ok", False)
            if not ok:
                logger.warning(f"Command {cmd!r} failed: {result.get('error')}")
            else:
                logger.debug(f"Command {cmd!r} succeeded")

            writer.write(json.dumps(result).encode() + b"\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

            # If close command, stop the server
            if cmd == "close":
                logger.info("Close command received, shutting down server")
                if server is not None:
                    server.close()
        except Exception:
            logger.exception("Unhandled error in handle_client")
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_unix_server(handle_client, path=str(socket_path))
    write_pid(session_name, os.getpid())
    logger.info(f"Server listening on {socket_path}")

    async with server:
        await server.serve_forever()

    # Cleanup on exit
    logger.info("Server stopped, cleaning up session")
    cleanup_session(session_name)


def _setup_logging(session_name: str) -> None:
    """Configure logging for the daemon process.

    Writes to ``~/.patchright-cli/sessions/<name>/daemon.log`` with rotation-friendly
    append mode.  Also redirects *stdout*/*stderr* so that any stray ``print()``
    calls or unhandled tracebacks land in the same file.
    """
    log_path = get_log_path(session_name)
    handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)

    # Redirect stdout/stderr so print() and unhandled exceptions also appear
    sys.stdout = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
    sys.stderr = sys.stdout


def start_daemon(session_name: str, config_dict: dict[str, Any] | str) -> None:
    """Entry point for the daemon subprocess. Called by client.py."""
    _setup_logging(session_name)
    logger.info(f"Daemon starting for session {session_name!r} (pid={os.getpid()})")
    parsed: dict[str, Any] = (
        json.loads(config_dict) if isinstance(config_dict, str) else config_dict
    )
    try:
        asyncio.run(run_server(session_name, parsed))
    except Exception:
        logger.exception("Daemon crashed")
        raise
