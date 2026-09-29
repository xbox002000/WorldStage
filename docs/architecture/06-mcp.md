# 06 MCP

Code: `capability/mcp_client.py`, `capability/mcp_adapter.py`, `capability/mcp_servers/visual_mock.py`.

**Problem.** Outside tools (ComfyUI workflows, cloud models, Blender) should be pluggable without the core learning
each one. MCP is a common way to wrap a tool.

**Options.**
1. The core speaks MCP to everything.
2. MCP is one adapter behind the capability interface, next to local, CLI and HTTP providers.

**Decision: option 2.**

`McpVisualProvider` connects to a server over stdio. It discovers what the server offers by calling its
`capability_manifest` tool, and then behaves like any `visual.generate` provider:
- It marks `transport = "mcp"`.
- It returns the same `Take`.
- It checks the reported clip's hash against the bytes on disk.

A server that cannot start or answer makes the provider unavailable, never an error. The registry falls back
(tested with a server that exits at once).

Server tools are named by capability (`visual_generate`), never by tool (`comfyui_run_workflow`). Underscores are
used because dots are not accepted by every MCP client.

**Why.**
- If the core spoke MCP, the HyperFrames coupling would just become an MCP coupling.
- As an adapter, MCP is optional: `produce.py --mcp` adds it, and without it nothing changes.

**Tradeoffs.**
- The client is hand-written against the spec (revision 2025-06-18: initialize, initialized, tools/list,
  tools/call), about 100 lines, with no SDK dependency.
- Its only counterpart so far is our own server, so two pieces of our own code could agree on a mistake.
- **Not yet verified against an outside MCP implementation.** Checking it needs the `mcp` Python SDK or the MCP
  Inspector, which is a download.
- Files are passed as local paths, which only works while the server runs on this machine. A remote server needs an
  upload/download step in the adapter.

**Proof.**
- For the same RenderRequest and ShotRequest, the clip made through MCP is byte-identical to the one made in
  process: same `artifact_hash`, in `test_an_mcp_provider_gives_the_same_clip_as_the_local_one`.

**Next.**
- Wrap a real outside tool once one is usable at $0.
- Only then split servers by capability.
