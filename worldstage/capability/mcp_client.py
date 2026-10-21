"""A minimal MCP client over stdio (JSON-RPC 2.0, one message per line), written against the MCP specification
(protocol revision 2025-06-18: initialize -> notifications/initialized -> tools/list, tools/call).

No SDK on purpose: the core must not depend on MCP, and this is all a capability adapter needs. Servers are
launched as child processes; nothing here listens on a port.
"""
from __future__ import annotations

import json
import queue
import subprocess
import threading

PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    pass


class McpStdioClient:
    def __init__(self, command: list[str], timeout: float = 120.0, cwd: str | None = None) -> None:
        self.command = command
        self.timeout = timeout
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding="utf-8", errors="replace", cwd=cwd, bufsize=1)
        self._lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self._next = 0
        self.server_info: dict = {}
        self.tools: dict[str, dict] = {}
        try:
            self._handshake()
        except BaseException:
            self.close()
            raise

    def _pump(self) -> None:
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _send(self, msg: dict) -> None:
        if self.proc.poll() is not None:
            raise McpError(f"server exited ({self.proc.returncode}): {self.proc.stderr.read()[-300:]}")
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict | None = None) -> dict:
        self._next += 1
        rid = self._next
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        while True:
            try:
                line = self._lines.get(timeout=self.timeout)
            except queue.Empty:
                raise McpError(f"{method}: no answer within {self.timeout:g}s") from None
            if line is None:
                raise McpError(f"{method}: server closed the connection")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # stdout noise is not a protocol message
            if msg.get("id") != rid:
                continue  # a notification or a stale answer
            if "error" in msg:
                raise McpError(f"{method}: {msg['error'].get('message')} ({msg['error'].get('code')})")
            return msg.get("result", {})

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def _handshake(self) -> None:
        result = self.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                             "clientInfo": {"name": "world-to-video", "version": "1"}})
        self.server_info = result.get("serverInfo", {})
        self.notify("notifications/initialized")
        self.tools = {t["name"]: t for t in self.request("tools/list").get("tools", [])}

    def call(self, tool: str, arguments: dict) -> dict:
        """Call a tool and return its structured result (or its first text block parsed as JSON)."""
        if tool not in self.tools:
            raise McpError(f"server has no tool {tool!r} (has {sorted(self.tools)})")
        result = self.request("tools/call", {"name": tool, "arguments": arguments})
        text = next((c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"), "")
        if result.get("isError"):
            raise McpError(f"{tool}: {text[:300]}")
        if "structuredContent" in result:
            return result["structuredContent"]
        return json.loads(text) if text else {}

    def close(self) -> None:
        try:
            self.proc.stdin.close()  # a well-behaved server exits when its input ends
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        for stream in (self.proc.stdout, self.proc.stderr):
            stream.close()
