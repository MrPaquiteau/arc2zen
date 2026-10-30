"""Tiny Marionette client (Firefox's built-in remote protocol), stdlib only.

We only need one thing: run a privileged script in Zen's browser window.
"""
from __future__ import annotations

import json
import socket
import time
from typing import Any, Optional


class MarionetteError(Exception):
    pass


class Marionette:
    def __init__(self, host: str = "127.0.0.1", port: int = 2828):
        self.host, self.port = host, port
        self.sock: Optional[socket.socket] = None
        self.msg_id = 0

    # ---------------------------------------------------------------- transport
    def _recv(self) -> Any:
        assert self.sock
        head = b""
        while not head.endswith(b":"):
            ch = self.sock.recv(1)
            if not ch:
                raise MarionetteError("Zen closed the connection")
            head += ch
        length = int(head[:-1])
        body = b""
        while len(body) < length:
            chunk = self.sock.recv(length - len(body))
            if not chunk:
                raise MarionetteError("Zen closed the connection")
            body += chunk
        return json.loads(body)

    def command(self, name: str, params: Optional[dict] = None) -> Any:
        assert self.sock
        self.msg_id += 1
        payload = json.dumps([0, self.msg_id, name, params or {}]).encode()
        self.sock.sendall(str(len(payload)).encode() + b":" + payload)
        while True:
            msg = self._recv()
            if isinstance(msg, list) and msg[0] == 1 and msg[1] == self.msg_id:
                if msg[2]:
                    err = msg[2]
                    raise MarionetteError(f"{err.get('error')}: {err.get('message')}")
                return msg[3]

    # ------------------------------------------------------------------ session
    def connect(self, timeout: float = 90) -> None:
        deadline = time.time() + timeout
        last: Optional[Exception] = None
        while time.time() < deadline:
            try:
                self.sock = socket.create_connection((self.host, self.port), timeout=5)
                self.sock.settimeout(None)
                self._recv()  # handshake
                break
            except OSError as e:
                last = e
                time.sleep(1)
        else:
            raise MarionetteError(f"Could not connect to Zen on port {self.port}: {last}")
        # A browser window may take a few seconds to appear after startup.
        while True:
            try:
                self.command("WebDriver:NewSession", {"capabilities": {"alwaysMatch": {}}})
                break
            except MarionetteError as e:
                if "window" not in str(e).lower() or time.time() > deadline:
                    raise
                time.sleep(1)
        self.command("Marionette:SetContext", {"value": "chrome"})
        self._select_browser_window()

    def _select_browser_window(self) -> None:
        handles = self.command("WebDriver:GetWindowHandles")
        if isinstance(handles, dict):
            handles = handles.get("value", [])
        for h in handles:
            self.command("WebDriver:SwitchToWindow", {"handle": h})
            if self.execute("return !!(window.gBrowser && window.gZenWorkspaces);", timeout=10):
                return
        raise MarionetteError("No Zen browser window found")

    def execute(self, script: str, args: Any = None, timeout: float = 600) -> Any:
        self.command("WebDriver:SetTimeouts", {"script": int(timeout * 1000)})
        res = self.command("WebDriver:ExecuteScript", {"script": script, "args": [args] if args is not None else []})
        return res.get("value") if isinstance(res, dict) else res

    def run_async(self, body: str, args: Any = None, timeout: float = 600) -> Any:
        """Run `body` as the inside of an async function; `args` is available as a variable."""
        wrapped = "const args = arguments[0];\nreturn (async () => {\n" + body + "\n})();"
        return self.execute(wrapped, args if args is not None else {}, timeout)

    def close(self) -> None:
        if self.sock:
            try:
                self.command("WebDriver:DeleteSession")
            except (MarionetteError, OSError):
                pass
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
