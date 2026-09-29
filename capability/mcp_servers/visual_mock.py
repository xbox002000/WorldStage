"""An MCP server (stdio) that offers the visual.generate capability, backed by the mock-clip provider.

It stands for any outside video tool wrapped as MCP (a ComfyUI workflow, a cloud model). Two tools:
  capability_manifest   the providers it offers, with their manifests and toolchains (discovery)
  visual_generate       RenderRequest + ShotRequest in, a Take out
Tool names use underscores: dots in tool names are not accepted by every MCP client.

Run: python -m capability.mcp_servers.visual_mock
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.backends import ShotRequest  # noqa: E402
from contracts.base import from_dict, to_dict  # noqa: E402
from contracts.render_request import RenderRequest  # noqa: E402
from render.mock_clip import MockClipBackend  # noqa: E402

PROTOCOL_VERSION = "2025-06-18"
PROVIDER = MockClipBackend()
TOOLS = [
    {"name": "capability_manifest", "description": "List the capability providers this server offers.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "visual_generate", "description": "Generate one shot as a video clip (capability visual.generate).",
     "inputSchema": {"type": "object", "required": ["request", "shot", "dest"], "properties": {
         "request": {"type": "object", "description": "a RenderRequest (contracts/render_request.py)"},
         "shot": {"type": "object", "description": "a ShotRequest (contracts/backends.py)"},
         "dest": {"type": "string", "description": "where to write the clip"}}}},
]


def _call(name: str, args: dict) -> dict:
    if name == "capability_manifest":
        return {"providers": [{"manifest": to_dict(PROVIDER.manifest()), "toolchain": PROVIDER.toolchain()}]}
    if name == "visual_generate":
        take = PROVIDER.generate(from_dict(RenderRequest, args["request"]), from_dict(ShotRequest, args["shot"]),
                                 Path(args["dest"]))
        return {"take": to_dict(take)}
    raise KeyError(name)


def handle(msg: dict) -> dict | None:
    method, rid = msg.get("method"), msg.get("id")
    if rid is None:
        return None  # notifications get no answer
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "visual-mock", "version": "1"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params", {})
        try:
            data = _call(p.get("name"), p.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                      "structuredContent": data, "isError": False}
        except KeyError as e:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"unknown tool or argument {e}"}}
        except Exception as e:  # noqa: BLE001 - a tool failure is a result with isError, not a protocol error
            result = {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin.buffer:
        try:
            msg = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}), flush=True)
            continue
        answer = handle(msg)
        if answer is not None:
            print(json.dumps(answer, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
