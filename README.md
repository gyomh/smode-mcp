# Controlling Smode Compose with an LLM (MCP) — experimental bridge

*[Version française](README.fr.md)*

A small bridge that lets an AI assistant (Claude, or any client speaking
**MCP** — *Model Context Protocol*, Anthropic's open standard for connecting
an LLM to external tools) manipulate a running Smode Compose session in
natural language, instead of hand-editing code.

Concretely: you describe what you want ("create a camera orbiting a wireframe
cube, with a per-axis speed control"), and the LLM writes and directly
executes the corresponding Python/Oil code inside Smode, observing the
results (and errors) to iterate until it works.

**Important: Smode Tech has not published an official API documentation.**
Everything below comes from on-the-fly introspection (`Oil.docMe()`, `dir()`,
reading example scripts shipped with Smode) and trial and error — not from
guaranteed documentation. This is not an officially supported Smode Tech
tool.

## How it works

Two pieces:

1. **`smode_bridge.py`** — a Python script to paste into a Smode **Script**
   object. It starts a small local HTTP server (`127.0.0.1:8891`) that
   receives Python code and executes it in Smode's Oil/SmodeSDK context (so
   with access to the entire current scene: layers, cameras, animations,
   parameters...).

2. **`smode_mcp_server.py`** — an MCP server (Python, official `mcp` SDK)
   that runs on the assistant side (Claude Code / Claude Desktop, or any
   other MCP-compatible client) and exposes a single tool, `smode_execute`.
   This tool simply relays the code received from the LLM to the HTTP bridge
   inside Smode, and returns the output (`print()`, the value of `result`,
   errors).

```
LLM host  --tool call-->  smode_mcp_server.py  --HTTP POST-->  smode_bridge.py (inside Smode)  --exec()-->  Oil / SmodeSDK
```

### Pitfall encountered: don't execute the received code on the HTTP thread

First version: the HTTP server executed the received Python code directly on
its own thread (the way `execute_blender_code` does in blender-mcp, for
example). Result: **total deadlock**, no request ever got a response
(confirmed via `netstat`, connections stuck in `CLOSE_WAIT` indefinitely).
Executing Oil code apparently has to happen on Smode's main thread, not from
a secondary Python thread.

Solution: the HTTP thread only drops the request into a queue
(`queue.Queue`) and waits on a signal (`threading.Event`). It's the Script
itself, re-run on every update by Smode (Launch Mode = **"At Every
Update"**, NOT `Manual`), that drains the queue and actually executes the
code — always on the main thread, never from the HTTP thread.

## Installation

**Requirements**: Python 3.10+ with the official MCP SDK:
```
pip install mcp
```

**On the Smode side**:
1. Create a **Script** object in a Smode project (any scene/compo works).
2. Paste the contents of `smode_bridge.py` into it.
3. Change its **Launch Mode to "At Every Update"** (mandatory, see above).
4. Compile. The console should print `[smode_bridge] demarre sur
   127.0.0.1:8891`.

**On the LLM client side** (Claude Code, Claude Desktop, or any other
MCP-compatible client such as Cursor, Windsurf, Continue, LM Studio...): add
an entry to the MCP config (`.mcp.json` for Claude Code,
`claude_desktop_config.json` for Claude Desktop, or the equivalent for your
client):

```json
{
  "mcpServers": {
    "smode": {
      "command": "python",
      "args": ["/path/to/smode_mcp_server.py"]
    }
  }
}
```

Restart the client — the `smode_execute` tool should show up.

## ⚠️ Security — read before use

`smode_execute` runs **arbitrary Python code** received by the HTTP server,
with no authentication. The server only listens on `127.0.0.1` (so it's not
reachable over the network), but **any process running on the same
machine** can send requests to that port while it's running.

- Don't leave this bridge running on a shared or exposed machine.
- This is a tinkering/exploration tool, not something to use as-is in a
  live production/show context without thinking twice.
- If you want a narrower surface, replace `smode_execute(code)` with
  dedicated, restricted MCP tools (e.g. `list_scene()`, `create_layer(type)`,
  `set_parameter(path, value)`) instead of free code execution.

## What we managed to build with it (example)

To validate the bridge, we had the LLM build — through small iterations,
questions/errors/corrections — a wireframe cube with an orbiting camera:
- `GeometryLayer` + `BoxGeometryGenerator` + `ThickLinesGeometryRenderer` for
  the cube
- `AffineCamera` with `TargetOrientationDistance3dPlacement` (native orbit
  around the origin, no manual trigonometry)
- 3 looping `FunctionCue(Angle)` (one per axis), linked to the camera's
  `orientation.x/y/z` via `ParameterLinkTarget`
- A Parameter Bank exposing `Speed X/Y/Z` and a shared `Play/Pause`

All built and debugged by dialoguing with the LLM, with no official
documentation — just introspection (`Oil.docMe()`) and iterating on real
errors.
