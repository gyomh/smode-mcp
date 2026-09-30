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
1. Créez un objet **Script** dans un projet Smode (peu importe la scène/compo).
2. Collez-y le contenu de `smode_bridge.py`.
3. Changez son **Launch Mode en "At Every Update"** (obligatoire, voir plus haut).
4. Compilez. La console doit afficher `[smode_bridge] demarre sur 127.0.0.1:8891`.

**Côté Claude** (Claude Code ou Claude Desktop) : ajoutez une entrée dans la config
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

Redémarrez Claude : l'outil `smode_execute` doit apparaître.

## Déclencher vos propres Scripts depuis un bouton (Stream Deck, Chataigne, tout client HTTP)

Le pont ne sert pas qu'au LLM : il peut aussi lancer des Scripts Smode que vous avez
préparés, depuis n'importe quoi capable d'envoyer une requête HTTP.

**Slots.** Le Script du pont expose 8 slots (`slot1` … `slot8`). Glissez-y d'autres
Scripts Smode (un Script déposé dans un slot est automatiquement forcé en Launch Mode
= **Manual**, il ne tourne donc que lorsqu'on le déclenche). Envoyez ensuite un payload
court :

| Payload (`code`)            | Effet                                                        |
|-----------------------------|--------------------------------------------------------------|
| `run_script("mon_script")`  | Lance le Script nommé `mon_script` présent dans un des slots |
| `run_slot(1)`               | Lance le Script du `slot1`                                   |
| `list_slots()`              | Renvoie le contenu de chaque slot                            |

Le payload peut être envoyé en JSON (`{"code": "run_script('mon_script')"}`), en
form-urlencoded (`code=run_script("mon_script")` — ce qu'envoie le module HTTP de
Chataigne), ou en query string `?code=`, sur `POST http://127.0.0.1:8891`.
Exemple : un Script « nouvelle scène » qui crée une Scene prête à l'emploi, déclenché
par un bouton Stream Deck via Chataigne.

### Réglage de Smode

![Paramètres du Script smode_bridge dans Smode](docs/smode-bridge-parameters.png)

Dans le panneau **Parameters** du Script `smode_bridge` :
- **Launch Mode** doit rester sur **At Every Update**.
- **Port** doit correspondre à l'adresse saisie dans Chataigne (8891 par défaut).
- **Slot 1** à **Slot 8** reçoivent les Scripts à déclencher (glissez-les depuis le
  navigateur de Smode, ou choisissez-les dans le menu). Ici, `nouvelle_scene` est dans le
  slot 1 et `uniforms_timeline` dans le slot 2 : `run_script("nouvelle_scene")` ou
  `run_slot(1)` lance le premier, `run_slot(2)` le second.
- **Restart Server** : voir plus bas.

### Réglage de Chataigne

![Module HTTP et consequence dans Chataigne](docs/chataigne-http-module.png)

1. Ajoutez un module **HTTP** et réglez sa **Base Address** sur `http://127.0.0.1:8891`
   (le port du paramètre `port` du Script bridge).
2. Créez une consequence **HTTP > Request** avec **Method** = `POST` et **Address** = `/`.
3. Dans **Arguments**, ajoutez un argument nommé `code` dont la valeur est le payload,
   par exemple `run_script("mon_script")` ou `run_slot(1)`.
4. Reliez cette consequence à une condition (par exemple l'appui sur un bouton Stream
   Deck). Le bouton **Trigger** du *Command Tester* permet de la tester sans le Stream Deck.

Deux façons de désigner le Script à lancer, au choix dans l'argument `code` :

- `run_slot(1)` : par numéro de slot (première capture ci-dessus). Simple, mais il faut
  penser à le modifier si vous réorganisez les slots.
- `run_script("nouvelle_scene")` : par nom de Script (capture ci-dessous). Plus lisible, et
  insensible à l'ordre des slots. C'est la méthode conseillée.

![Consequence Chataigne avec run_script](docs/chataigne-run-script.png)

**Case `restartServer`.** Smode garde le namespace Python d'un Script en vie d'un
recollage à l'autre : après une mise à jour de `smode_bridge.py`, le serveur HTTP
conserverait donc son *ancien* gestionnaire de requêtes, et les fonctions retirées du
code resteraient appelables jusqu'au redémarrage de Smode. Cocher `restartServer` (elle
se décoche toute seule) purge les fonctions qui ne sont plus dans le source et relance
le serveur HTTP avec le gestionnaire actuel. Effet de bord : les fonctions définies à la
volée via `smode_execute` sont aussi purgées.

**Pièges appris à la dure**
- Une exception non rattrapée dans un Script « At Every Update » l'arrête complètement :
  le pont répond alors `504` à toutes les requêtes. Entourez tout code exécuté à chaque
  frame d'un `try/except`.
- `getUniqueIdentifier()` est inutilisable depuis Python (`juce::Uuid` non convertible) :
  il lève un `TypeError`.
- Un Script placé dans un slot se lance avec `tool.execute.trig()` (`execute` est un
  objet `Trigger`, pas un appelable).

## ⚠️ Sécurité — à lire avant d'utiliser

`smode_execute` exécute **n'importe quel code Python arbitraire** reçu par le serveur
HTTP, sans authentification. Le serveur n'écoute que sur `127.0.0.1` (donc pas
accessible depuis le réseau), mais **n'importe quel processus tournant sur la même
machine** peut envoyer des requêtes à ce port pendant qu'il tourne.

- Ne laissez pas ce pont actif sur une machine partagée ou exposée.
- C'est un outil de bricolage/exploration personnelle, pas quelque chose à utiliser
  tel quel en contexte de spectacle/production sans y réfléchir à deux fois.
- Si vous voulez une surface plus restreinte, remplacez `smode_execute(code)` par des
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
