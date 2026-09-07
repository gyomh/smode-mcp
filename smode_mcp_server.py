#!/usr/bin/env python3
"""Smode MCP Server — pilote Smode Compose via le pont HTTP embarque (smode_bridge.py)."""

import json
import urllib.error
import urllib.request

try:
    from mcp.server.fastmcp import FastMCP  # mcp SDK v1
except ModuleNotFoundError:
    from mcp.server.mcpserver import MCPServer as FastMCP  # mcp SDK v2

# ── Configuration ──────────────────────────────────────────────────────────────

BRIDGE_URL = "http://127.0.0.1:8891"

mcp = FastMCP("Smode")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _call_bridge(code: str) -> dict:
    """Envoie du code Python au pont embarque dans Smode et retourne sa reponse JSON."""
    data = json.dumps({"code": code}).encode("utf-8")
    req = urllib.request.Request(
        BRIDGE_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Impossible de joindre le pont Smode sur {BRIDGE_URL} — "
            f"verifie que smode_bridge.py tourne dans Smode ({e})"
        ) from e


# ── Outils MCP ─────────────────────────────────────────────────────────────────

@mcp.tool()
def smode_execute(code: str) -> str:
    """Execute du code Python arbitraire dans le contexte Oil/SmodeSDK de Smode Compose.

    Le code s'execute dans le meme contexte qu'un objet Script Smode : `Oil`, `SmodeSDK`
    et `script` (le Script du pont lui-meme) sont disponibles. Affecter une variable
    nommee `result` pour recuperer une valeur ; tout print() est aussi retourne.

    Args:
        code: Code Python a executer dans Smode.
    """
    response = _call_bridge(code)
    return json.dumps(response, indent=2, ensure_ascii=False)


# ── Entree ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
