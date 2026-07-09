# ------------------------------------------- . ----------------------------------------
# Filename : smode_bridge.py                  | Pont MCP cote Smode.                    |
#                                              | A coller dans un Script Smode.          |
#                                              | Launch Mode = "At Every Update"          |
#                                              | (obligatoire)                            |
#                                              | Le serveur HTTP tourne dans un thread    |
#                                              | separe mais NE FAIT QUE mettre les       |
#                                              | requetes en file d'attente. C'est le     |
#                                              | thread principal (via l'execution        |
#                                              | reguliere du Script) qui execute reelle- |
#                                              | ment le code Oil/SmodeSDK, en drainant   |
#                                              | la file a chaque frame.                  |
#                                              |                                          |
#                                              | Raison : executer du code Oil            |
#                                              | directement depuis le thread HTTP        |
#                                              | bloque (deadlock constate : connexions   |
#                                              | bloquees en CLOSE_WAIT, jamais de        |
#                                              | reponse).                                |
# Started  : 2026-07-07                        |                                        |
# ------------------------------------------- . ----------------------------------------

port: Oil.PositiveInteger(8891)

import contextlib
import io
import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

_EXEC_NAMESPACE = globals()

if "_SMODE_MCP_REQUEST_QUEUE" not in globals():
    _SMODE_MCP_REQUEST_QUEUE = queue.Queue()

def _safeRepr(value):
    try:
        return repr(value)
    except Exception:
        return "<unrepr-able>"

class SmodeBridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence le logging par defaut (Smode redirige deja stdout/stderr)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            payload = json.loads(body.decode("utf-8"))
            code = payload.get("code", "")
        except Exception as e:
            self._respond(400, {"success": False, "error": f"invalid JSON: {e}"})
            return

        doneEvent = threading.Event()
        requestBox = {"code": code, "result": None, "done": doneEvent}
        _SMODE_MCP_REQUEST_QUEUE.put(requestBox)

        # Attend que le thread principal (processQueue(), appele chaque frame) traite la requete.
        if not doneEvent.wait(timeout=15):
            self._respond(504, {"success": False, "error": "timeout: le thread principal Smode n'a pas repondu (Script bien en 'At Every Update' ?)"})
            return

        self._respond(200, requestBox["result"])

    def _respond(self, statusCode, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(statusCode)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def _startServer(p):
    server = HTTPServer(("127.0.0.1", p), SmodeBridgeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server

def _processQueue():
    """Vide la file de requetes en attente - execute sur le thread principal Smode.

    Utilise _EXEC_NAMESPACE comme unique namespace (globals ET locals), comme une
    vraie console/REPL persistante : les variables definies par une requete restent
    disponibles dans les requetes suivantes (ex: 'camera = ...' puis reutiliser
    'camera' dans un appel smode_execute ulterieur).
    """
    while not _SMODE_MCP_REQUEST_QUEUE.empty():
        req = _SMODE_MCP_REQUEST_QUEUE.get_nowait()
        stdoutCapture = io.StringIO()
        result = {"success": True, "output": "", "error": None}
        _EXEC_NAMESPACE.pop("result", None)  # evite qu'un vieux 'result' fuite d'un appel precedent
        try:
            with contextlib.redirect_stdout(stdoutCapture):
                exec(req["code"], _EXEC_NAMESPACE)
            if "result" in _EXEC_NAMESPACE:
                result["result"] = _safeRepr(_EXEC_NAMESPACE["result"])
        except Exception as e:
            result["success"] = False
            result["error"] = repr(e)
        result["output"] = stdoutCapture.getvalue()
        req["result"] = result
        req["done"].set()

# Demarrage du serveur (une seule fois, idempotent grace au namespace partage).
if "_SMODE_MCP_BRIDGE_SERVER" not in globals():
    _SMODE_MCP_BRIDGE_SERVER = _startServer(script.port.get())
    print(f"[smode_bridge] demarre sur 127.0.0.1:{script.port.get()}")

# Appele a chaque execution du Script (donc a chaque update si Launch Mode = "At Every Update").
_processQueue()
