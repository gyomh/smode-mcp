# Piloter Smode Compose avec Claude (MCP) — pont expérimental

*[English version](README.md)*

Un petit pont qui permet à un assistant IA (Claude, via le protocole **MCP** —
*Model Context Protocol*, le standard d'Anthropic pour connecter un LLM à des outils
externes) de manipuler une session Smode Compose en cours d'exécution, en langage
naturel plutôt qu'en éditant du code à la main.

Concrètement : je décris ce que je veux ("crée une caméra qui tourne autour d'un cube
fil de fer, avec une vitesse par axe réglable"), et Claude écrit et exécute directement
le code Python/Oil correspondant dans Smode, en observant les résultats (et les erreurs)
pour itérer jusqu'à ce que ça marche.

**Important : Smode Tech n'a pas encore publié de documentation d'API officielle.**
Tout ce qui suit vient d'introspection à la volée (`Oil.docMe()`, `dir()`, lecture de
scripts d'exemple fournis avec Smode) et de tâtonnement — pas d'une doc garantie. Ce
n'est pas un outil officiellement supporté par Smode Tech.

## Comment ça marche

Deux morceaux :

1. **`smode_bridge.py`** — un script Python à coller dans un objet **Script** de Smode.
   Il démarre un petit serveur HTTP local (`127.0.0.1:8891`) qui reçoit du code Python
   et l'exécute dans le contexte Oil/SmodeSDK de Smode (donc avec accès à toute la scène
   courante : layers, caméras, animations, paramètres...).

2. **`smode_mcp_server.py`** — un serveur MCP (Python, SDK officiel `mcp`) qui tourne
   côté Claude Code / Claude Desktop et expose un seul outil, `smode_execute(code)`. Cet
   outil relaie simplement le code reçu de Claude vers le pont HTTP dans Smode, et
   retourne la sortie (`print()`, valeur de `result`, erreurs).

```
Claude  --tool call-->  smode_mcp_server.py  --HTTP POST-->  smode_bridge.py (dans Smode)  --exec()-->  Oil / SmodeSDK
```

### Piège rencontré : ne pas exécuter le code reçu sur le thread HTTP

Première version : le serveur HTTP exécutait le code Python directement dans son
propre thread (comme le fait `execute_blender_code` de blender-mcp, par exemple).
Résultat : **deadlock total**, aucune requête ne recevait de réponse (confirmé via
`netstat`, connexions bloquées en `CLOSE_WAIT` indéfiniment). L'exécution de code
Oil semble devoir se faire sur le thread principal de Smode, pas depuis un thread
Python annexe.

Solution : le thread HTTP ne fait que déposer la requête dans une file d'attente
(`queue.Queue`) et attend un signal (`threading.Event`). C'est le Script lui-même,
réexécuté à chaque update par Smode (Launch Mode = **"At Every Update"**, PAS
`Manual`), qui vide la file et exécute réellement le code — donc toujours sur le
thread principal, jamais depuis le thread HTTP.

## Installation

**Prérequis** : Python 3.10+ avec le SDK MCP officiel :
```
pip install mcp
```

**Côté Smode** :
1. Crée un objet **Script** dans un projet Smode (peu importe la scène/compo).
2. Colle le contenu de `smode_bridge.py` dedans.
3. Change son **Launch Mode en "At Every Update"** (obligatoire, voir plus haut).
4. Compile. La console doit afficher `[smode_bridge] demarre sur 127.0.0.1:8891`.

**Côté Claude** (Claude Code ou Claude Desktop) : ajoute une entrée dans la config
MCP (`.mcp.json` pour Claude Code, `claude_desktop_config.json` pour Claude Desktop) :

```json
{
  "mcpServers": {
    "smode": {
      "command": "python",
      "args": ["/chemin/vers/smode_mcp_server.py"]
    }
  }
}
```

Redémarre Claude, l'outil `smode_execute` doit apparaître.

## ⚠️ Sécurité — à lire avant d'utiliser

`smode_execute` exécute **n'importe quel code Python arbitraire** reçu par le serveur
HTTP, sans authentification. Le serveur n'écoute que sur `127.0.0.1` (donc pas
accessible depuis le réseau), mais **n'importe quel processus tournant sur la même
machine** peut envoyer des requêtes à ce port pendant qu'il tourne.

- Ne laisse pas ce pont actif sur une machine partagée ou exposée.
- C'est un outil de bricolage/exploration personnelle, pas quelque chose à utiliser
  tel quel en contexte de spectacle/production sans y réfléchir à deux fois.
- Si tu veux une surface plus restreinte, remplace `smode_execute(code)` par des
  outils MCP dédiés et limités (ex: `list_scene()`, `create_layer(type)`,
  `set_parameter(path, value)`) plutôt que de l'exécution de code libre.

## Ce qu'on a réussi à construire avec (exemple)

Pour valider le pont, on a fait construire à Claude — par petites itérations,
questions/erreurs/corrections — un cube fil de fer avec une caméra orbitale :
- `GeometryLayer` + `BoxGeometryGenerator` + `ThickLinesGeometryRenderer` pour le cube
- `AffineCamera` avec `TargetOrientationDistance3dPlacement` (orbite native autour de
  l'origine, pas de trigonométrie à la main)
- 3 `FunctionCue(Angle)` en boucle (une par axe), liées à `orientation.x/y/z` de la
  caméra via des `ParameterLinkTarget`
- Un Parameter Bank exposant `Speed X/Y/Z` et un `Play/Pause` commun

Tout construit et corrigé en dialoguant avec Claude, sans documentation officielle —
juste par introspection (`Oil.docMe()`) et itération sur les erreurs réelles.
