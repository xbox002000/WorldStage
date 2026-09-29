"""MCP adapter: an MCP server's offer becomes an ordinary provider in the registry.

The core never sees MCP. It sees a provider whose manifest the server reported (discovery through the
`capability_manifest` tool), whose transport is "mcp", and whose results come back as the same Take a local
provider returns. If the server cannot be started or reached, the provider reports itself unavailable and the
registry falls back to others; nothing in the core depends on the server being up.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

from capability.mcp_client import McpError, McpStdioClient
from contracts.backends import ShotRequest
from contracts.base import from_dict, to_dict
from contracts.capability import ProviderManifest
from contracts.render_request import RenderRequest, Take
from production.provenance import file_sha256

ROOT = Path(__file__).resolve().parent.parent
VISUAL_MOCK = [sys.executable, "-m", "capability.mcp_servers.visual_mock"]


class McpVisualProvider:
    def __init__(self, server: str, command: list[str], remote_provider: str | None = None, timeout: float = 120.0) -> None:
        self.server = server
        self.command = command
        self.remote_provider = remote_provider  # which of the server's providers; None = its first visual one
        self.timeout = timeout
        self._client: McpStdioClient | None = None
        self._offer: dict | None = None
        self._error = ""

    @property
    def name(self) -> str:
        return f"mcp:{self.server}"

    def _connect(self) -> dict | None:
        if self._offer is None and not self._error:
            try:
                self._client = McpStdioClient(self.command, timeout=self.timeout, cwd=str(ROOT))
                offers = self._client.call("capability_manifest", {})["providers"]
                self._offer = next(o for o in offers if "visual.generate" in o["manifest"]["capabilities"] and (
                    self.remote_provider in (None, o["manifest"]["provider_id"])))
            except (McpError, OSError, StopIteration, KeyError) as e:
                self._error = f"{type(e).__name__}: {e}"[:300]
                self.close()
        return self._offer

    def manifest(self) -> ProviderManifest:
        offer = self._connect()
        if offer is None:  # unknown until the server answers: no features, so nothing selects it
            return ProviderManifest(self.name, "unknown", ["visual.generate"], [], transport="mcp", local=False,
                                    deterministic=False, notes=self._error)
        m = from_dict(ProviderManifest, offer["manifest"])
        return dataclasses.replace(m, provider_id=self.name, transport="mcp",
                                   notes=f"via MCP server {self.server}: {m.notes}")

    def available(self) -> tuple[bool, str]:
        return (True, "") if self._connect() is not None else (False, self._error or "MCP server did not answer")

    def toolchain(self) -> dict[str, str]:
        offer = self._connect()
        return {**(offer or {}).get("toolchain", {}), "transport": "mcp", "mcp_server": self.server}

    def generate(self, request: RenderRequest, shot: ShotRequest, dest: Path) -> Take:
        if self._connect() is None:
            return Take(request.request_hash, "failed", error=self._error)
        try:
            data = self._client.call("visual_generate", {"request": to_dict(request), "shot": to_dict(shot),
                                                         "dest": str(dest)})
        except McpError as e:
            return Take(request.request_hash, "failed", error=str(e)[:400])
        take = from_dict(Take, data["take"])
        if take.status == "ready":  # trust the server's word only as far as the bytes on disk agree
            path = Path(take.artifact_path or "")
            if not path.exists() or file_sha256(path) != take.artifact_hash:
                return Take(request.request_hash, "failed", error="MCP server reported a clip whose hash does not match")
        return dataclasses.replace(take, request_hash=request.request_hash)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
