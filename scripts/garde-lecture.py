#!/usr/bin/env python3
# brain-distribuable: oui
"""Le garde de lecture — hook Claude Code `PreToolUse` : aucun sous-agent ne lit le personnel.

L'écriture d'un worker se juge sur le diff de sa PR (`zone-du-diff.py`) ; une lecture, elle, ne laisse aucune
trace dans un diff.
La règle : le personnel ne se lit jamais hors de la session — ni par le worker, ni par un sous-agent lancé en
session (un Explore, un general-purpose) : tous travaillent sans qu'on voie ce qu'ils lisent. La session, elle,
c'est l'humain présent ; son type et sa posture la gardent.

    python3 scripts/garde-lecture.py hook                    ← l'entrée du hook (JSON sur stdin)
    python3 scripts/garde-lecture.py juger <outil> '<json>'  ← l'entrée d'un outil, jugée comme un sous-agent
    python3 scripts/garde-lecture.py brancher [--brain <d>]  ← le poser dans `.claude/settings.json`
    python3 scripts/garde-lecture.py etat [--brain <d>]      ← posé ? sortie 0 oui, 1 non

── Le branchement ──────────────────────────────────────────────────────────

`brancher` ajoute son hook au `.claude/settings.json` du brain — le crée s'il
manque, n'ajoute que cette entrée, laisse tout le reste (un hook `PreToolUse` à
toi reste à côté : Claude Code les joue tous, un refus suffit). Deux fois, rien
de plus. Un fichier qui n'est pas du JSON n'est jamais réécrit : sortie 2.
`brain-setup.sh` et `brain maj` le lancent ; `brain doctor` dit s'il manque.

── Qui il tient ────────────────────────────────────────────────────────────

Un appel d'outil venu d'un sous-agent porte `agent_type` dans l'entrée du hook ; un
appel de la session n'en porte pas. Mesuré le 6/10 sur Claude Code 2.1.282 — non
documenté : si une version le retire, le garde ne voit plus personne, et son
témoin (`TestGardeLecture`) ne le saura pas. Le rejouer après une mise à jour.

── Ce qu'il refuse ─────────────────────────────────────────────────────────

Les chemins de `zone_personal` et de `zone_aucune` (`NIVEAUX.yml`) — illisibles,
ceux du 6/10 par défaut :

    Read                le fichier, liens résolus
    Grep, Glob          un `path` dans le personnel, ou un motif qui le nomme
    Bash                un mot qui mène dans le personnel, qu'il le nomme ou non — ou
                        qui le nomme sans qu'il puisse trancher (plus bas)

── Bash : où mènent les chemins ───────────────────────────────────

Le texte ne suffit pas : refuser toute commande qui NOMME un préfixe arrêtait
du travail qui ne lit rien du brain (un motif de grep, un message de commit, un
rendu dans /tmp, un heredoc écrit ailleurs). La commande est découpée — quotes
(`$'…'` compris), `&&` `;` `||` `|`, `( … )`, heredocs — et chaque mot est jugé
selon son rôle, après avoir été développé comme bash le ferait avant d'exécuter :
les accolades d'un mot non quoté (`{a,b}`, imbriquées, `{1..3}`, `{a..c}`), puis
ses globs (`*`, `?`, `[…]`), depuis chaque cwd suivi — des noms, jamais un
contenu. Un glob qui ne trouve rien se juge littéralement, comme bash le passe ;
avec un cwd inconnu, un glob relatif aussi. Au-delà de 1024 formes pour un mot
(`{1..5000}`), il est refusé : « je ne peux pas trancher ».
Un `$(…)` ou des backticks (non quotés ou entre doubles quotes, quel que soit le
rôle du mot qui les porte) se jugent comme une commande, depuis le même cwd —
jusqu'à 8 niveaux d'imbrication, au-delà : refusé.

    un chemin (`~` développé, `cd` littéraux     refusé s'il tombe dans le personnel
      suivis, liens résolus, `git -C`,           du brain, qu'il le nomme ou non (un
      `--opt=…`, `HEAD:…`, une redirection) —    relatif après un `cd`, un lien) ;
      tout mot qui n'a pas un autre rôle         passe s'il mène ailleurs (un rendu,
                                                 un bac, /tmp/…, le brain lui-même)
    le motif d'un grep/rg/git grep (le premier   passe
      argument non-option, ou celui de `-e`)
    l'argument de `-f` (grep), de `-F` (commit)  un fichier : un chemin
    le message de `git commit`/`git tag` (`-m`)  passe
    le corps d'un heredoc que `cat >`/`>>`/`tee` passe
      écrit dans un fichier hors du personnel
    s'il NOMME le personnel : `$VAR`, `${…}`,   refusé : « je ne peux pas trancher : … »
      `$(…)`, backticks (refusés avant même
      d'être jugés comme commande), `eval`,
      le code de `python -c`/`bash -c`/`node -e`
      /`perl -e`…, un heredoc ou un `<<<` donné
      à un autre programme (ou que `cat` passe à
      un tube), un chemin relatif après un `cd`
      inconnu (`cd -`, `cd $X`)
    une commande qui ne se découpe pas (quote    refusée, en le disant
      ouverte)

Un `cd` peut échouer ou ne pas tourner : le cwd d'avant reste possible, sauf
quand il ouvre une liste vers un dossier qui existe, ou pour la suite de la
chaîne `&&` qu'il ouvre. Un `cd` dans un tube, en arrière-plan ou entre
parenthèses ne change rien après.

── Ce qu'il ne voit pas, et le dit ─────────────────────────────────────────

- Un Grep lancé plus haut (la racine) : il ne descend pas dans le personnel —
  ripgrep saute ce que `.gitignore` écarte, et le personnel l'est (mesuré).
- Un Glob lancé plus haut avec `**` : il LISTE les noms du personnel (Glob ne
  lit pas `.gitignore`, mesuré) — des noms, jamais un contenu. Le refuser
  arrêterait chaque recherche d'un sous-agent à la racine.
- Bash : un script qui lit pour elle ; le code de `python -c`/`bash -c`/`eval`…
  qui ne nomme pas le personnel ; le programme d'un `awk`/`sed` (jugé comme un
  chemin, pas comme du code) ; un `find -exec`, un `xargs`, un alias. Une
  variable (`$X`, `$X/*.md`) ne se développe pas : elle ne compte que si elle
  NOMME le personnel. Un `$(…)` dans le corps d'un heredoc au délimiteur non
  quoté n'est pas jugé comme commande. Après un `cd` qu'il ne résout pas
  (`cd -`, `cd $X`), un relatif qui ne nomme rien passe — sinon tout serait
  refusé ensuite. Une exclusion (`--exclude-dir=brain-secrets`,
  `':!vie/'`, `-path … -prune`) ne compte pas : elle nomme pour ne pas lire. Ce n'est pas un pare-feu : c'est la règle présente
  au moment du geste.

Sa propre erreur laisse passer, en le disant : un garde qui plante ne doit pas
arrêter tout le travail.
"""

from __future__ import annotations

import glob
import itertools
import json
import os
import re
import sys
from pathlib import Path


def _racine_des_donnees(env_d_abord: bool = False) -> Path:
    """La data de ce script, par `brain-engine/donnees.py` du programme : sans la
    marque d'un programme installé à part, la position (et `BRAIN_ROOT` si `env_d_abord`),
    comme avant. Un banc qui ne copie que ce script n'a pas `donnees.py` : la position."""
    import os as _os
    ici = Path(__file__).resolve().parent.parent
    src = ici / "brain-engine" / "donnees.py"
    if not src.is_file():
        return Path(_os.environ.get("BRAIN_ROOT") or ici) if env_d_abord else ici
    import importlib.util
    spec = importlib.util.spec_from_file_location("_brain_donnees", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        return mod.trouver_donnees(ici, env_d_abord=env_d_abord)[0]
    except RuntimeError as exc:
        raise SystemExit(f"❌ {exc}")


BRAIN = _racine_des_donnees()   # la data
PAR_DEFAUT = ('profil/identity/', 'profil/capital*', 'vie/', 'brain-secrets/')
OUTILS = {'Read', 'Grep', 'Glob', 'Bash'}


def prefixes(brain: Path = BRAIN) -> tuple[str, ...]:
    """`zone_personal` et `zone_aucune` de `NIVEAUX.yml` — sans dépendance : deux listes de haut niveau."""
    try:
        lignes = (brain / 'NIVEAUX.yml').read_text(encoding='utf-8').splitlines()
    except OSError:
        return PAR_DEFAUT
    trouves, cle = [], None
    for ligne in lignes:
        if re.match(r'^(zone_personal|zone_aucune):\s*$', ligne):
            cle = ligne
            continue
        if cle and (m := re.match(r'^\s+-\s+(\S+)', ligne)):
            trouves.append(m.group(1).strip('\'"'))
        elif cle and ligne.strip() and not ligne.lstrip().startswith('#'):
            cle = None
    return tuple(trouves) or PAR_DEFAUT


def dans(rel: str, prefixe: str) -> bool:
    """`rel` (relatif au brain) tombe-t-il sous `prefixe` ? `capital*` : le préfixe nu."""
    if prefixe.endswith('*'):
        return rel.startswith(prefixe[:-1])
    base = prefixe.rstrip('/')
    return rel == base or rel.startswith(base + '/')


def personnel(chemin: str, cwd: Path, brain: Path, prefs) -> str | None:
    """Le chemin, s'il est personnel — relatif au brain, liens résolus."""
    if not chemin:
        return None
    p = Path(os.path.expanduser(chemin))
    p = p if p.is_absolute() else cwd / p
    try:
        rel = os.path.relpath(os.path.realpath(p), os.path.realpath(brain))
    except ValueError:
        return None
    if rel.startswith('..'):
        return None
    rel = rel.replace(os.sep, '/')
    return rel if any(dans(rel, x) for x in prefs) else None


# Une EXCLUSION nomme un chemin pour ne PAS le lire : la règle d'audit veut même qu'on exclue
# `brain-secrets/` explicitement. Le 6/10, l'orchestrator, en sous-agent, s'est vu refuser
# `grep -rn … --exclude-dir=brain-secrets` — le garde punissait le bon geste. Ces formes sont
# retirées de la commande avant de la juger ; ce qu'elle lit ailleurs se juge toujours.
EXCLUSIONS = re.compile(
    r"""--exclude(?:-dir)?(?:=|\s+)(?:"[^"]*"|'[^']*'|\S+)"""   # grep --exclude-dir=…, --exclude …
    r"""|--glob(?:=|\s+)['"]?!\S+"""                          # rg --glob '!…'
    r"""|-g\s+['"]?!\S+"""                                     # rg -g '!…'
    r"""|['"]:(?:!|\(exclude\))[^'"]*['"]"""                   # git pathspec ':!…', ':(exclude)…'
    r"""|-path\s+\S+\s+-prune""")                             # find … -path … -prune


def sans_exclusions(commande: str) -> str:
    return EXCLUSIONS.sub(' ', commande)


def nomme(texte: str, prefs) -> str | None:
    """Un texte (commande, motif) qui nomme un chemin personnel."""
    for x in prefs:
        base = re.escape(x.rstrip('*').rstrip('/'))
        suite = '' if x.endswith('*') else r'(?=/|[\s\'"]|$)'
        if m := re.search(r'(?:^|(?<=[\s\'"=:/(]))' + base + suite, texte):
            return m.group(0)
    return None


# ── Bash : où mènent les chemins ────────────────────────────────────
# Le garde refusait toute commande qui NOMMAIT un préfixe personnel : un motif de grep, un message
# de commit, un rendu dans /tmp, un heredoc écrit ailleurs. Il découpe maintenant la commande et
# juge chaque mot selon son rôle, qu'il nomme le personnel ou non (la docstring dit la règle) :
# un chemin se développe (accolades, globs) et se résout (cwd suivi, `~`, liens) ; un motif, un
# message, un texte écrit hors du personnel passent ; un `$(…)` se juge comme une commande ; ce
# qu'il ne sait pas résoudre (une expansion, du code, un heredoc donné à un programme) n'est
# refusé que s'il nomme le personnel — en le disant.
#
# Le découpage est fait main, pas par `shlex` : `shlex` ne distingue pas `'|'` d'un tube, ni
# `'$HOME'` (littéral) de `$HOME` (expansé), et ne connaît pas les heredocs.

INDECIS = 'je ne peux pas trancher'
OPERATEURS = ('<<<', '&&', '||', ';;', '>>', '<<', '>&', '<&', '&>', '>|', '|&',
              ';', '|', '&', '(', ')', '<', '>', '\n')
SEPARATEURS = {'&&', '||', ';', ';;', '|', '|&', '&', '\n'}
REDIRECTIONS = {'>', '>>', '<', '>|', '&>', '>&', '<&'}
ECRITURES = {'>', '>>', '>|', '&>'}
MOTS_CLES = {'if', 'then', 'elif', 'else', 'do', 'while', 'until', '!', '{', '}', 'time'}
ENVELOPPES = {'sudo', 'env', 'nohup', 'command', 'exec', 'nice', 'stdbuf'}
# Programmes dont un argument est du CODE : le garde ne le lit pas.
CODE = {'python': 'c', 'bash': 'c', 'sh': 'c', 'zsh': 'c', 'dash': 'c', 'ksh': 'c', 'fish': 'c',
        'node': 'ep', 'perl': 'eE', 'ruby': 'e'}
CODE_LONG = {'node': ('--eval', '--print')}
# Les options qui prennent un argument — pour trouver le motif (premier argument non-option).
GREP = ('efmABCdD', ('regexp', 'file', 'max-count', 'after-context', 'before-context', 'context',
                     'include', 'exclude', 'exclude-dir', 'exclude-from', 'label', 'binary-files',
                     'devices', 'directories'))
RG = ('efgtTmABCrjMEd', ('regexp', 'file', 'glob', 'iglob', 'type', 'type-not', 'max-count',
                        'after-context', 'before-context', 'context', 'replace', 'threads',
                        'max-columns', 'encoding', 'max-depth', 'max-filesize', 'sort', 'sortr',
                        'type-add', 'type-clear', 'pre', 'pre-glob', 'colors', 'context-separator',
                        'path-separator', 'ignore-file', 'engine'))
GIT_GREP = ('efABCmO', ('regexp', 'file', 'max-depth', 'context', 'after-context', 'before-context',
                        'max-count', 'open-files-in-pager', 'threads'))
GIT_MESSAGE = {'commit': ('mFcCt', ('message', 'file', 'reuse-message', 'reedit-message', 'template',
                                    'author', 'date', 'fixup', 'squash', 'cleanup', 'trailer')),
               'tag': ('mFu', ('message', 'file', 'local-user', 'cleanup', 'trailer'))}


class Jeton:
    """Un opérateur (`&&`, `>`, `(`…) ou un mot (sans ses quotes). `indecis` : le mot porte une
    expansion que le garde ne résout pas (`$VAR`, `${…}`, `$(…)`, backticks). `quotes` : pour
    chaque caractère de `val`, s'il était quoté (ni accolade ni glob ne s'y développent).
    `sous` : le texte des `$(…)` et backticks du mot — des commandes, jugées à leur tour."""
    __slots__ = ('op', 'val', 'indecis', 'corps', 'quotes', 'sous')

    def __init__(self, op, val, indecis=False, quotes=None, sous=None):
        self.op, self.val, self.indecis, self.corps = op, val, indecis, None
        self.quotes = quotes if quotes is not None else [True] * len(val)
        self.sous = sous or []


def _fermant(texte: str, i: int, ouvre: str, ferme: str) -> int:
    """L'indice qui ferme `ouvre` (texte[i] == ouvre), quotes sautées ; ValueError s'il manque."""
    prof, j = 0, i
    while j < len(texte):
        c = texte[j]
        if c == '\\':
            j += 2
            continue
        if c == "'" and ouvre != "'":
            k = texte.find("'", j + 1)
            if k < 0:
                raise ValueError('quote ouverte')
            j = k + 1
            continue
        if c == ouvre:
            prof += 1
        elif c == ferme:
            prof -= 1
            if prof == 0:
                return j
        j += 1
    raise ValueError(f'{ouvre} sans {ferme}')


ANSI_C = {'n': '\n', 't': '\t', 'r': '\r', 'a': '\a', 'b': '\b', 'e': '\x1b', 'E': '\x1b', 'f': '\f',
          'v': '\v', '\\': '\\', "'": "'", '"': '"', '?': '?'}


def _ansi_c(texte: str, i: int) -> tuple[str, int]:
    """`$'…'` (texte[i] == `'`) : son contenu littéral, échappements faits, et l'indice d'après."""
    j, sortie = i + 1, ''
    while True:
        if j >= len(texte):
            raise ValueError("quote $'…' ouverte")
        c = texte[j]
        if c == "'":
            return sortie, j + 1
        if c == '\\' and j + 1 < len(texte):
            d = texte[j + 1]
            if d in ANSI_C:
                sortie, j = sortie + ANSI_C[d], j + 2
                continue
            if m := re.match(r'x([0-9A-Fa-f]{1,2})|([0-7]{1,3})', texte[j + 1:]):
                sortie += chr(int(m.group(1), 16) if m.group(1) else int(m.group(2), 8))
                j += 1 + len(m.group(0))
                continue
        sortie, j = sortie + c, j + 1


def decouper(texte: str) -> list[Jeton]:
    """La commande en jetons, à la manière de bash ; ValueError si elle ne se découpe pas."""
    jetons: list[Jeton] = []
    attente: list[int] = []            # les `<<` dont le corps commence à la prochaine fin de ligne
    mot, marques, sous, indecis, quote = None, [], [], False, False
    i, n = 0, len(texte)

    def ajouter(t: str, quote_: bool):
        nonlocal mot
        mot = (mot or '') + t
        marques.extend([quote_] * len(t))

    def pousser():
        nonlocal mot, marques, sous, indecis, quote
        if mot is not None:
            jetons.append(Jeton(False, mot, indecis, marques, sous))
        mot, marques, sous, indecis, quote = None, [], [], False, False

    def corps_des_heredocs(i):
        for p in attente:
            if p + 1 >= len(jetons) or jetons[p + 1].op:
                raise ValueError('heredoc sans délimiteur')
            fin, tabs = jetons[p + 1].val, jetons[p].val == '<<-'
            lignes = []
            while i < n:
                j = texte.find('\n', i)
                ligne = texte[i:] if j < 0 else texte[i:j]
                i = n if j < 0 else j + 1
                if (ligne.lstrip('\t') if tabs else ligne) == fin:
                    break
                lignes.append(ligne)
            jetons[p].corps = '\n'.join(lignes)
        attente.clear()
        return i

    while i < n:
        c = texte[i]
        if c in ' \t\r':
            pousser()
            i += 1
        elif c == '\\':
            if texte[i + 1:i + 2] == '\n':
                i += 2
                continue
            ajouter(texte[i + 1:i + 2], True)
            i += 2
        elif c == "'":
            j = texte.find("'", i + 1)
            if j < 0:
                raise ValueError('quote simple ouverte')
            ajouter(texte[i + 1:j], True)
            quote, i = True, j + 1
        elif c == '$' and texte[i + 1:i + 2] == "'":
            litteral, i = _ansi_c(texte, i + 1)        # `$'…'` : une quote, pas une expansion
            ajouter(litteral, True)
            quote = True
        elif c == '"':
            j, morceau = i + 1, ''
            while True:
                if j >= n:
                    raise ValueError('quote double ouverte')
                d = texte[j]
                if d == '"':
                    break
                if d == '\\' and texte[j + 1:j + 2] in ('$', '`', '"', '\\', '\n'):
                    morceau += texte[j + 1]
                    j += 2
                    continue
                if d == '$' and texte[j + 1:j + 2] == '(':
                    k = _fermant(texte, j + 1, '(', ')')
                    sous.append(texte[j + 2:k])
                    morceau, indecis, j = morceau + texte[j:k + 1], True, k + 1
                    continue
                if d == '`':
                    k = texte.find('`', j + 1)
                    if k < 0:
                        raise ValueError('backtick ouvert')
                    sous.append(texte[j + 1:k])
                    morceau, indecis, j = morceau + texte[j:k + 1], True, k + 1
                    continue
                if d == '$' and re.match(r'[A-Za-z_{0-9@*#?!$-]', texte[j + 1:j + 2]):
                    indecis = True
                morceau += d
                j += 1
            ajouter(morceau, True)
            quote, i = True, j + 1
        elif c == '`':
            k = texte.find('`', i + 1)
            if k < 0:
                raise ValueError('backtick ouvert')
            sous.append(texte[i + 1:k])
            ajouter(texte[i:k + 1], True)
            indecis, i = True, k + 1
        elif c == '$' and texte[i + 1:i + 2] in ('(', '{'):
            k = _fermant(texte, i + 1, texte[i + 1], ')' if texte[i + 1] == '(' else '}')
            if texte[i + 1] == '(':
                sous.append(texte[i + 2:k])
            ajouter(texte[i:k + 1], True)
            indecis, i = True, k + 1
        elif c == '$' and re.match(r'[A-Za-z_0-9@*#?!$-]', texte[i + 1:i + 2]):
            ajouter(c, True)
            indecis, i = True, i + 1
        elif c == '#' and mot is None:
            j = texte.find('\n', i)
            i = n if j < 0 else j
        elif c in '();<>|&\n':
            op = next(o for o in OPERATEURS if texte.startswith(o, i))
            i += len(op)
            if op == '<<' and texte[i:i + 1] == '-':
                op, i = '<<-', i + 1
            # `2>`, `2>&1` : le chiffre est un descripteur, pas un argument.
            if op[0] in '<>&' and mot is not None and mot.isdigit() and not quote:
                mot = None
            pousser()
            jetons.append(Jeton(True, op))
            if op in ('<<', '<<-'):
                attente.append(len(jetons) - 1)
            if op == '\n' and attente:
                i = corps_des_heredocs(i)
        else:
            ajouter(c, False)
            i += 1
    pousser()
    if attente:
        corps_des_heredocs(n)
    return jetons


# ── Le développement d'un mot, comme bash avant d'exécuter : accolades, puis globs ──
BORNE = 1024        # formes d'un mot, au-delà : refusé, « je ne peux pas trancher »


class Trop(Exception):
    """Un mot qui se développe au-delà de BORNE formes."""


def _sequence(dedans: str) -> list[str] | None:
    """`1..3`, `01..10..2`, `a..e` : la séquence ; None si ce n'en est pas une."""
    if m := re.fullmatch(r'(-?\d+)\.\.(-?\d+)(?:\.\.(-?\d+))?', dedans):
        a, b = int(m.group(1)), int(m.group(2))
        pas = abs(int(m.group(3) or 1)) or 1
        if abs(b - a) // pas + 1 > BORNE:
            raise Trop
        largeur = max(len(m.group(1)), len(m.group(2))) \
            if re.match(r'-?0\d', m.group(1)) or re.match(r'-?0\d', m.group(2)) else 0
        r = range(a, b + 1, pas) if a <= b else range(a, b - 1, -pas)
        return [str(x).zfill(largeur) for x in r]
    if m := re.fullmatch(r'([A-Za-z])\.\.([A-Za-z])(?:\.\.(-?\d+))?', dedans):
        a, b = ord(m.group(1)), ord(m.group(2))
        pas = abs(int(m.group(3) or 1)) or 1
        r = range(a, b + 1, pas) if a <= b else range(a, b - 1, -pas)
        return [chr(x) for x in r]
    return None


def _accolades(car: list) -> list[list]:
    """Les formes d'un mot — `car` : [(caractère, quoté)] ; seules les accolades non quotées
    comptent, imbriquées, `{a,b}` et `{1..3}`. Trop au-delà de BORNE."""
    debut = 0
    while True:
        i = next((k for k in range(debut, len(car)) if car[k] == ('{', False)), None)
        if i is None:
            return [car]
        prof, virgules, j = 0, [], None
        for k in range(i, len(car)):
            if car[k][1]:
                continue
            if car[k][0] == '{':
                prof += 1
            elif car[k][0] == '}':
                prof -= 1
                if prof == 0:
                    j = k
                    break
            elif car[k][0] == ',' and prof == 1:
                virgules.append(k)
        if j is None:
            return [car]
        if virgules:
            bornes = [i] + virgules + [j]
            choix = [car[bornes[x] + 1:bornes[x + 1]] for x in range(len(bornes) - 1)]
        else:
            dedans = car[i + 1:j]
            seq = None if any(q for _, q in dedans) else _sequence(''.join(c for c, _ in dedans))
            if seq is None:
                debut = i + 1                       # `{a}`, `{}` : littéral, on cherche plus loin
                continue
            choix = [[(c, False) for c in x] for x in seq]
        formes = []
        for x in choix:
            formes += _accolades(car[:i] + x + car[j + 1:])
            if len(formes) > BORNE:
                raise Trop
        return formes


def _globs(car: list, cwd: Path | None) -> list[str]:
    """Une forme, ses globs non quotés développés depuis `cwd` — des noms, jamais un contenu.
    Rien ne correspond, ou cwd inconnu pour un relatif : la forme littérale (comme bash)."""
    litteral = ''.join(c for c, _ in car)
    if not any(c in '*?[' and not q for c, q in car):
        return [litteral]
    motif = ''.join(c if not q else glob.escape(c) for c, q in car)
    motif = os.path.expanduser(motif) if car and car[0] == ('~', False) else motif
    if not os.path.isabs(motif) and cwd is None:
        return [litteral]
    trouves = list(itertools.islice(
        glob.iglob(motif, root_dir=None if os.path.isabs(motif) else str(cwd)), BORNE + 1))
    if len(trouves) > BORNE:
        raise Trop
    return trouves or [litteral]


def developper(m: Jeton, cwd: Path | None) -> list[str]:
    """Les mots qu'un jeton devient pour bash, depuis `cwd` : accolades, puis globs."""
    formes = []
    for f in _accolades(list(zip(m.val, m.quotes))):
        formes += _globs(f, cwd)
        if len(formes) > BORNE:
            raise Trop
    return formes


def _options(args: list[Jeton], debut: int, courtes: str, longues) -> tuple[dict, list[int], set]:
    """Les options d'une commande : {indice: (option, valeur)} pour celles qui prennent un argument,
    les indices des positionnels, et ceux des mots qui SONT l'argument d'une option."""
    vues, positionnels, pris = {}, [], set()
    i, fin_options = debut, False
    while i < len(args):
        v = args[i].val
        if fin_options or not v.startswith('-') or v == '-':
            positionnels.append(i)
        elif v == '--':
            fin_options = True
        elif v.startswith('--'):
            nom, egal, valeur = v[2:].partition('=')
            if nom in longues:
                if egal:
                    vues[i] = (nom, valeur)
                elif i + 1 < len(args):
                    vues[i + 1] = (nom, args[i + 1].val)
                    pris.add(i + 1)
                    i += 1
        else:
            for k, ch in enumerate(v[1:], 1):
                if ch in courtes:
                    reste = v[k + 1:]
                    if reste:
                        vues[i] = (ch, reste)
                    elif i + 1 < len(args):
                        vues[i + 1] = (ch, args[i + 1].val)
                        pris.add(i + 1)
                        i += 1
                    break
        i += 1
    return vues, positionnels, pris


def _roles(prog: str, sous: str, args: list[Jeton], debut: int) -> dict:
    """{indice: 'motif' | 'message' | 'code' | ('chemin', valeur)} — les autres mots sont des chemins."""
    roles: dict = {}
    base = re.sub(r'[0-9.]+$', '', prog)          # python3.12 → python
    if prog in ('grep', 'egrep', 'fgrep', 'rg') or (prog == 'git' and sous == 'grep'):
        courtes, longues = RG if prog == 'rg' else GIT_GREP if prog == 'git' else GREP
        vues, positionnels, pris = _options(args, debut, courtes, longues)
        motif_en_option = False
        for i, (opt, valeur) in vues.items():
            if opt in ('e', 'regexp'):
                roles[i], motif_en_option = 'motif', True
            elif opt in ('f', 'file'):
                roles[i], motif_en_option = ('chemin', valeur), True
            elif i not in pris:
                roles[i] = ('chemin', valeur)
        if not motif_en_option and positionnels:
            roles[positionnels[0]] = 'motif'
    elif prog == 'git' and sous in GIT_MESSAGE:
        vues, _, pris = _options(args, debut, *GIT_MESSAGE[sous])
        for i, (opt, valeur) in vues.items():
            roles[i] = 'message' if opt in ('m', 'message') else ('chemin', valeur)
    elif prog == 'eval':
        roles.update({i: 'code' for i in range(debut, len(args))})
    elif base in CODE:
        for i in range(debut, len(args)):
            v = args[i].val
            if v in CODE_LONG.get(base, ()) or (v.startswith('-') and not v.startswith('--')
                                                 and v[-1] in CODE[base]):
                if i + 1 < len(args):
                    roles[i + 1] = 'code'
                break
            if not v.startswith('-'):
                break                               # le script : ses arguments sont à lui
    return roles


def _candidats(valeur: str):
    """Ce qu'un mot peut désigner : lui-même, ce qui suit `=` (`--opt=…`, `X=…`), ce qui suit
    le dernier `:` (`HEAD:chemin`)."""
    yield valeur
    if '=' in valeur:
        yield valeur.split('=', 1)[1]
    if ':' in valeur:
        yield valeur.rsplit(':', 1)[1]


def _chemin(valeur: str, cwds: set, brain: Path, prefs) -> str | None:
    for cand in _candidats(valeur):
        absolu = cand.startswith(('/', '~'))
        for cwd in cwds:
            if cwd is None and not absolu:
                # Un cwd inconnu (`cd -`, `cd $X`) : seul ce qui nomme le personnel est refusé —
                # sinon tout relatif le serait après un `cd $X`.
                if nomme(cand, prefs):
                    return f'{INDECIS} : « {cand} » après un `cd` que je ne résous pas'
                continue
            if trouve := personnel(cand, cwd or brain, brain, prefs):
                return trouve
    return None


PROFONDEUR = 8     # `$(…)` imbriqués, au-delà : refusé, « je ne peux pas trancher »


def _mot_chemin(m: Jeton, valeur: str, cwds: set, brain: Path, prefs) -> str | None:
    """Un mot jugé comme un chemin, développé (accolades, globs) depuis chaque cwd possible.
    `valeur` : la part qui est un chemin (`-fx` → `x`). Au-delà de BORNE formes : refusé."""
    prefixe = m.val[:len(m.val) - len(valeur)] if valeur != m.val and m.val.endswith(valeur) else ''
    for cwd in cwds:
        try:
            formes = developper(m, cwd)
        except Trop:
            return f'{INDECIS} : « {m.val} » se développe en plus de {BORNE} formes'
        for forme in formes:
            if prefixe and forme.startswith(prefixe):
                forme = forme[len(prefixe):]
            if trouve := _chemin(forme, {cwd}, brain, prefs):
                return trouve
    return None


def _substitutions(m: Jeton, cwds: set, brain: Path, prefs, profondeur: int) -> str | None:
    """Les `$(…)` et backticks d'un mot : des commandes, jugées comme telles, depuis le même cwd."""
    for texte in m.sous:
        if profondeur >= PROFONDEUR:
            return f'{INDECIS} : des `$(…)` imbriqués au-delà de {PROFONDEUR} niveaux'
        for cwd in cwds:
            if trouve := juger_bash(texte, cwd, brain, prefs, profondeur + 1):
                return trouve
    return None


def _juger_commande(mots, redirs, heredocs, cwds, suivant, brain, prefs, profondeur=0) -> str | None:
    """Une commande simple. `mots` : ses mots ; `redirs` : [(op, Jeton)] ; `heredocs` : [Jeton]."""
    i = 0
    while i < len(mots) and (mots[i].val in MOTS_CLES or mots[i].val in ENVELOPPES
                             or re.match(r'^[A-Za-z_]\w*=', mots[i].val)
                             or (i and mots[i - 1].val in ENVELOPPES and mots[i].val.startswith('-'))):
        i += 1
    prog = os.path.basename(mots[i].val) if i < len(mots) else ''
    debut = i + 1
    cwds_cmd, sous = cwds, ''
    if prog == 'git':                               # git -C <d> …, puis la sous-commande
        j = debut
        while j < len(mots) and mots[j].val.startswith('-'):
            if mots[j].val in ('-C', '-c') and j + 1 < len(mots):
                if mots[j].val == '-C':
                    if trouve := _mot_chemin(mots[j + 1], mots[j + 1].val, cwds_cmd, brain, prefs):
                        return trouve             # jugé d'où il part, pas d'où il mène
                    cwds_cmd = _destinations(mots[j + 1], cwds_cmd)
                j += 1
            j += 1
        sous, debut = (mots[j].val if j < len(mots) else ''), j + 1
    roles = _roles(prog, sous, mots, debut) if prog else {}
    for k, m in enumerate(mots):
        role = roles.get(k)
        valeur = role[1] if isinstance(role, tuple) else m.val
        inerte = role in ('motif', 'message')       # ils ne mènent nulle part
        nommant = nomme(m.val, prefs) or nomme(valeur, prefs)
        if not inerte and (role == 'code' or m.indecis) and nommant:   # le garde ne les résout pas
            quoi = f'du code ({prog})' if role == 'code' else 'une expansion'
            return f'{INDECIS} : {quoi} qui nomme le personnel — « {m.val} »'
        # Un `$(…)` tourne quel que soit le rôle du mot qui le porte : il se juge à son tour.
        if trouve := _substitutions(m, cwds_cmd, brain, prefs, profondeur):
            return trouve
        if inerte or role == 'code' or m.indecis:
            continue
        # Tout autre mot se juge comme un chemin, qu'il nomme le personnel ou non : un `cd`
        # suivi d'un relatif, un lien, un glob, des accolades y mènent sans le nommer.
        if trouve := _mot_chemin(m, valeur, cwds_cmd, brain, prefs):
            return trouve
    cibles = []
    for op, m in redirs:
        if m.indecis and nomme(m.val, prefs):
            return f'{INDECIS} : une expansion qui nomme le personnel — « {m.val} »'
        if trouve := _substitutions(m, cwds_cmd, brain, prefs, profondeur):
            return trouve
        if not m.indecis and (trouve := _mot_chemin(m, m.val, cwds_cmd, brain, prefs)):
            return trouve
        if op in ECRITURES:
            cibles.append(m)
    if prog == 'tee':
        cibles += [m for m in mots[debut:] if not m.val.startswith('-')]
    for h in heredocs:
        if trouve := _substitutions(h, cwds_cmd, brain, prefs, profondeur):   # `<<< "$(…)"`
            return trouve
        if not nomme(h.corps or '', prefs):
            continue
        ecrit_ailleurs = prog in ('cat', 'tee') and cibles and suivant not in ('|', '|&')
        if not ecrit_ailleurs:
            donne = (f'que « {prog} » passe à un tube' if prog in ('cat', 'tee') and suivant in ('|', '|&')
                     else f'donné à « {prog or "?"} »')
            return f'{INDECIS} : un heredoc {donne} qui nomme le personnel'
    return None


def _vers(cible: str | None, cwds: set) -> set:
    """Les cwd possibles après être allé à `cible` (None : inconnue)."""
    if cible is None:
        return {None}
    if cible.startswith(('/', '~')):
        return {Path(os.path.expanduser(cible))}
    return {None if c is None else c / cible for c in cwds}


def _destinations(cible: Jeton | str | None, cwds: set) -> set:
    """Les cwd possibles après être allé à `cible` : développée depuis chaque cwd (accolades,
    globs) ; inconnue (None) si elle ne donne pas UN seul dossier, ou porte une expansion."""
    if cible is None or isinstance(cible, str):
        return _vers(cible, cwds)
    if cible.indecis:
        return {None}
    resultat = set()
    for c in cwds:
        try:
            formes = developper(cible, c)
        except Trop:
            formes = []
        resultat |= _vers(formes[0], {c}) if len(formes) == 1 else {None}
    return resultat


def _cd(mots) -> tuple[bool, Jeton | str | None]:
    """(est-ce un cd, sa cible) — cible None : inconnue (`cd -`, `cd $X`, `popd`)."""
    if not mots or mots[0].val not in ('cd', 'pushd', 'popd'):
        return False, None
    if mots[0].val == 'popd':
        return True, None
    args = [m for m in mots[1:] if not (m.val.startswith('-') and m.val != '-')]
    if not args:
        return True, '~'
    if args[0].val == '-' or args[0].indecis:
        return True, None
    return True, args[0]


def juger_bash(commande: str, cwd: Path | None, brain: Path, prefs, profondeur: int = 0) -> str | None:
    """La raison du refus d'une commande Bash, ou None."""
    texte = sans_exclusions(commande)
    try:
        jetons = decouper(texte)
    except ValueError as exc:
        if n := nomme(texte, prefs):
            return f'{INDECIS} : une commande que je ne sais pas découper ({exc}) nomme le personnel ({n})'
        return None
    cwds: set = {cwd}
    repli: set | None = None           # le cwd d'avant un `cd … &&`, si ce cd peut échouer
    pile: list = []
    mots, redirs, heredocs = [], [], []
    precedent = None
    jetons.append(Jeton(True, '\n'))
    k = 0
    while k < len(jetons):
        j = jetons[k]
        if not j.op:
            mots.append(j)
        elif j.val in REDIRECTIONS or j.val == '<<<':
            if k + 1 < len(jetons) and not jetons[k + 1].op:
                if j.val == '<<<':
                    h = Jeton(False, '', sous=jetons[k + 1].sous)
                    h.corps = jetons[k + 1].val
                    heredocs.append(h)
                else:
                    redirs.append((j.val, jetons[k + 1]))
                k += 1
        elif j.val in ('<<', '<<-'):
            heredocs.append(j)
            k += 1                                   # le délimiteur n'est pas un chemin
        elif j.val in SEPARATEURS or j.val in ('(', ')'):
            suivant = j.val
            if mots or redirs or heredocs:
                if trouve := _juger_commande(mots, redirs, heredocs, cwds, suivant, brain, prefs,
                                             profondeur):
                    return trouve
                est_cd, cible = _cd(mots)
                en_tube = precedent in ('|', '|&') or suivant in ('|', '|&', '&')
                if est_cd and not en_tube:
                    # Un cd peut échouer, ou ne pas tourner : le cwd d'avant reste possible, sauf
                    # pour la suite d'une chaîne `&&` qu'il ouvre, ou s'il est sûr (en tête de
                    # liste, vers un dossier qui existe).
                    nouveaux = _destinations(cible, cwds)
                    en_tete = precedent in (None, ';', ';;', '\n', '&', '(')
                    if precedent == '||':
                        cwds = cwds | nouveaux
                    elif en_tete and all(c is not None and c.is_dir() for c in nouveaux):
                        cwds = nouveaux
                    elif suivant == '&&':
                        repli, cwds = (repli or set()) | cwds, nouveaux
                    else:
                        cwds = cwds | nouveaux
            if suivant in (';', ';;', '\n', '||', '&') and repli:
                cwds, repli = cwds | repli, None
            if suivant == '(':
                pile.append((cwds, repli))
            elif suivant == ')' and pile:
                cwds, repli = pile.pop()
            mots, redirs, heredocs = [], [], []
            precedent = suivant
        k += 1
    return None


def juger(outil: str, entree: dict, cwd: Path, brain: Path = BRAIN) -> str | None:
    """La raison du refus, ou None."""
    prefs = prefixes(brain)
    if outil == 'Read':
        return personnel(entree.get('file_path', ''), cwd, brain, prefs)
    if outil in ('Grep', 'Glob'):
        trouve = personnel(entree.get('path') or '', cwd, brain, prefs)
        if trouve:
            return trouve
        for cle in ('pattern', 'glob') if outil == 'Glob' else ('glob',):
            # `!vie/**` : un motif d'exclusion ne lit rien.
            if entree.get(cle) and not str(entree[cle]).startswith('!') \
                    and (n := nomme(entree[cle], prefs)):
                return n
        return None
    if outil == 'Bash':
        return juger_bash(entree.get('command') or '', cwd, brain, prefs)
    return None


def hook() -> int:
    """L'entrée du hook : JSON sur stdin, un refus sur stdout, toujours code 0."""
    try:
        entree = json.load(sys.stdin)
        outil = entree.get('tool_name')
        if not entree.get('agent_type') or outil not in OUTILS:
            return 0
        cwd = Path(entree.get('cwd') or os.getcwd())
        trouve = juger(outil, entree.get('tool_input') or {}, cwd)
    except Exception as exc:              # noqa: BLE001 — un garde qui plante ne bloque rien
        print(json.dumps({'systemMessage': f'garde de lecture : erreur ({type(exc).__name__}) — '
                                           f'lecture non jugée'}, ensure_ascii=False))
        return 0
    if trouve:
        motif = (f'{trouve} — un sous-agent ne lit pas le personnel' if trouve.startswith(INDECIS)
                 else f'un sous-agent ne lit pas le personnel ({trouve})')
        print(json.dumps({'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': (
                f'🛑 garde de lecture : {motif} — '
                f'profil/identity/, profil/capital*, vie/, brain-secrets/ se lisent en session, '
                f'par l\'humain présent. Rapporte ce qui te manque au lieu de le chercher.'),
        }}, ensure_ascii=False))
    return 0


COMMANDE = 'python3 "$CLAUDE_PROJECT_DIR/scripts/garde-lecture.py" hook'
MATCHER = 'Read|Grep|Glob|Bash'


def reglages(brain: Path) -> Path:
    return brain / '.claude' / 'settings.json'


def lire_reglages(brain: Path) -> dict:
    """Les réglages du brain — `{}` s'ils n'existent pas ; ValueError s'ils ne sont pas du JSON."""
    f = reglages(brain)
    if not f.is_file():
        return {}
    d = json.loads(f.read_text(encoding='utf-8') or '{}')
    if not isinstance(d, dict):
        raise ValueError('pas un objet JSON')
    return d


def branche(d: dict) -> bool:
    """Le garde est-il dans ces réglages ?"""
    for entree in ((d.get('hooks') or {}).get('PreToolUse') or []):
        for h in (entree.get('hooks') or []) if isinstance(entree, dict) else []:
            if isinstance(h, dict) and 'garde-lecture.py' in str(h.get('command', '')):
                return True
    return False


def brancher(brain: Path) -> int:
    try:
        d = lire_reglages(brain)
    except ValueError as e:
        print(f'⛔ {reglages(brain)} n\'est pas lisible ({e}) — rien n\'est écrit ; le garde n\'est pas posé.')
        return 2
    if branche(d):
        print('✅ garde de lecture déjà branché')
        return 0
    d.setdefault('hooks', {}).setdefault('PreToolUse', []).append(
        {'matcher': MATCHER, 'hooks': [{'type': 'command', 'command': COMMANDE}]})
    f = reglages(brain)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix('.json.garde')
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(f)
    print(f'✅ garde de lecture branché — {f}')
    return 0


def etat(brain: Path) -> int:
    try:
        ok = branche(lire_reglages(brain))
    except ValueError as e:
        print(f'⛔ {reglages(brain)} illisible ({e})')
        return 1
    print('✅ garde de lecture branché' if ok
          else '❌ garde de lecture absent — python3 scripts/garde-lecture.py brancher')
    return 0 if ok else 1


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == 'hook':
        return hook()
    if len(sys.argv) >= 4 and sys.argv[1] == 'juger':
        trouve = juger(sys.argv[2], json.loads(sys.argv[3]), Path.cwd())
        print(f'refusé : {trouve}' if trouve else 'passe')
        return 1 if trouve else 0
    if len(sys.argv) >= 2 and sys.argv[1] in ('brancher', 'etat'):
        brain = Path(sys.argv[sys.argv.index('--brain') + 1]) if '--brain' in sys.argv else BRAIN
        return (brancher if sys.argv[1] == 'brancher' else etat)(brain.expanduser().resolve())
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
