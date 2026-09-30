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
slot1: Oil.createObject("WeakPointer(PythonScriptTool)")  # glisser ici un Script a declencher
slot2: Oil.createObject("WeakPointer(PythonScriptTool)")
slot3: Oil.createObject("WeakPointer(PythonScriptTool)")
slot4: Oil.createObject("WeakPointer(PythonScriptTool)")
slot5: Oil.createObject("WeakPointer(PythonScriptTool)")
slot6: Oil.createObject("WeakPointer(PythonScriptTool)")
slot7: Oil.createObject("WeakPointer(PythonScriptTool)")
slot8: Oil.createObject("WeakPointer(PythonScriptTool)")
restartServer: Oil.Boolean(False)  # cocher = redemarrage a chaud du serveur HTTP (se decoche tout seul)

import contextlib
import io
import json
import queue
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

_EXEC_NAMESPACE = globals()

N_SLOTS = 8

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

    def do_GET(self):
        self._handleRequest()

    def do_POST(self):
        self._handleRequest()

    def _handleRequest(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        code = None
        # 1) corps JSON classique : {"code": "..."} (pont smode-mcp cote MCP Claude)
        if body:
            try:
                payload = json.loads(body.decode("utf-8"))
                code = payload.get("code", "")
            except Exception:
                code = None
        # 2) corps form-urlencoded "code=..." -- format REEL envoye par le module HTTP
        #    de Chataigne (Content-Type: application/x-www-form-urlencoded, User-Agent:
        #    juce), confirme par capture live le 2026-09-20 avec un bouton Stream Deck.
        #    Piste "query string dans l'URL" essayee avant : fausse piste, c'etait
        #    juste Chataigne qui AFFICHE son erreur reseau sous forme adresse+params,
        #    la requete reelle envoie bien les Arguments dans le corps.
        if code is None and body:
            try:
                params = urllib.parse.parse_qs(body.decode("utf-8"))
                if "code" in params:
                    code = params["code"][0]
            except Exception:
                code = None
        # 3) fallback query string dans l'URL, au cas ou (inoffensif a garder)
        if code is None:
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            if "code" in params:
                code = params["code"][0]

        if code is None:
            self._respond(400, {"success": False, "error": "no 'code' found in JSON body, form body, or query string"})
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

# ------------------------------------------------------------------------------
# Slots : glisser des Scripts (Launch Mode = Manual) dans slot1..slot8, puis les
# declencher depuis Chataigne / Stream Deck avec un payload court :
#     code=run_slot(1)            ou            code=run_script("nouvelle_scene")
# (run_script cherche par nom du Script glisse dans un slot.)
# ------------------------------------------------------------------------------

def _slots():
    return [(i, getattr(script, f"slot{i}")) for i in range(1, N_SLOTS + 1)]

def _labelOf(tool):
    lab = tool.label
    return str(lab.get() if hasattr(lab, "get") else lab)

def run_slot(n):
    """Execute le Script glisse dans slotN (equivalent du bouton Execute)."""
    tool = getattr(script, f"slot{int(n)}").get()
    if tool is None:
        raise RuntimeError(f"slot{n} est vide")
    tool.execute.trig()
    return _labelOf(tool)

def run_script(name):
    """Execute le Script glisse dans un slot dont le nom vaut `name`."""
    for i, slot in _slots():
        tool = slot.get()
        if tool is not None and _labelOf(tool) == name:
            tool.execute.trig()
            return name
    raise RuntimeError(f"aucun slot ne contient un Script nomme {name!r}")

def list_slots():
    return {i: (_labelOf(s.get()) if s.get() is not None else None) for i, s in _slots()}

def _armSlots():
    """Force Launch Mode = Manual (0) sur chaque Script glisse dans un slot.

    Sans ca, un Script laisse en 'At Every Update' tournerait tout seul au lieu
    d'attendre son declenchement. try/except : une erreur ici ne doit jamais
    arreter le pont (un Script Smode en erreur cesse de s'executer).
    """
    for i, slot in _slots():
        try:
            tool = slot.get()
            if tool is not None and tool.launchMode.get() != 0:
                tool.launchMode.set(0)
        except Exception as e:
            print(f"[smode_bridge] slot{i}: {e!r}")

def _purgeStale():
    """Supprime de la memoire les fonctions qui ne sont plus dans le code du Script.

    Le namespace survit a un collage de script : une fonction retiree du code reste
    appelable jusqu'au redemarrage de Smode. On garde les fonctions definies au niveau
    racine du code actuel, plus tout ce qui n'est pas une fonction (variables
    du REPL, modules importes). Les fonctions creees a la volee via smode_execute sont
    donc aussi purgees.
    """
    import ast
    import types
    keep = set()
    for node in ast.parse(script.script.sourceCode.get()).body:
        if isinstance(node, ast.FunctionDef):
            keep.add(node.name)
    purged = []
    for name, value in list(_EXEC_NAMESPACE.items()):
        if isinstance(value, types.FunctionType) and name not in keep and not name.startswith("__"):
            del _EXEC_NAMESPACE[name]
            purged.append(name)
    return purged

def _restartServer():
    """Relance le serveur HTTP avec le gestionnaire courant (SmodeBridgeHandler).

    Necessaire apres avoir recolle le script : le serveur n'est cree qu'une fois par
    session Smode et garde sinon l'ancien gestionnaire en memoire. Fait dans un thread
    car shutdown() attend la fin de serve_forever, qui peut attendre ce thread principal.
    """
    global _SMODE_MCP_BRIDGE_SERVER
    old = _SMODE_MCP_BRIDGE_SERVER
    p = script.port.get()
    def _do():
        global _SMODE_MCP_BRIDGE_SERVER
        old.shutdown()
        old.server_close()
        _SMODE_MCP_BRIDGE_SERVER = _startServer(p)
    threading.Thread(target=_do, daemon=True).start()

# Appele a chaque execution du Script (donc a chaque update si Launch Mode = "At Every Update").
if script.restartServer.get():
    script.restartServer.set(False)
    _purgeStale()
    _restartServer()
_armSlots()
_processQueue()
