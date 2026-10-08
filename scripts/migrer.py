#!/usr/bin/env python3
# brain-distribuable: oui
"""brain migrer — un brain git passe au paquet, une fois.

    brain migrer [<dossier>] [--a-blanc] [--sans-service] [--laisser-l-instance]
    brain migrer --annuler [<dossier>] [--sans-service]

Lancé DEPUIS le programme installé (`pipx install brain-cortex`), sur un brain cloné
par git (le dossier courant par défaut). Le programme quitte le dossier ; les
données restent, et le dossier devient un dépôt de données neuf, servi par le paquet.

**Avant de toucher quoi que ce soit, il refuse** (et dit pourquoi) :
- un dossier qui n'est pas un brain git, ou qui l'est déjà au paquet ;
- un paquet plus ancien que le clone (sa version, `brain-compose.yml`) ;
- du travail non commité, ou des commits non poussés, dans le clone ou un satellite
  (un dépôt git imbriqué) — un dépôt sans branche suivie se dit, il ne bloque pas :
  la copie garde toute son histoire ;
- une copie `<dossier>.avant-paquet` déjà là ;
- dans les entrées du programme (`scripts/`, `noyau/`, `brain-engine/`…) : un fichier
  qui DIFFÈRE de celui du paquet (une retouche locale) ; un fichier suivi que le
  paquet ne porte pas (un script de l'instance), ou un satellite qui y vit — ceux-là
  passent avec `--laisser-l-instance` : ils restent dans la copie, pas dans le brain.

**Puis, dans l'ordre :**
1. les unités systemd utilisateur du brain (`brain*`, `dolt-server`) : leurs fichiers et
   leur état gardés, puis arrêtées et désactivées (sauf `--sans-service`) ;
2. la copie : le dossier entier à côté, `<dossier>.avant-paquet`, avec son `.git` —
   rien n'y est jamais retiré ; `.migrer/` y garde l'état d'avant (unités, réglages de
   Claude Code qui pointent dans le dossier, la commande `brain`, l'empreinte) ;
3. le programme quitte le dossier : chaque entrée du programme, entière — ce qui
   n'est qu'un fichier du paquet, ou ce qu'un outil a généré (venv, caches) ;
   `brain-engine/.env.local` passe à la racine (`.env.local`), là où le paquet la lit ;
4. le dossier devient un dépôt de données neuf : un premier commit des fichiers que
   le clone suivait et qui restent — l'ancien `.git` est dans la copie ;
5. `brain init <nom> <dossier>` : le pointeur, la vue, la base Dolt (VIDE quand le
   clone n'avait pas de base à lui : la base d'avant était ailleurs), les unités,
   les hooks, le garde de lecture ;
6. la commande `brain` de `~/.local/bin`, si elle désignait le clone, désigne le paquet ;
   les hooks globaux de Claude Code qui visent un script disparu sont SIGNALÉS (pas
   retirés : c'est à toi de dire ce qu'ils deviennent) ;
7. `brain doctor` — sortie 0 seulement s'il est vert (sans service : la base et le moteur
   sont lancés le temps du doctor, aux ports de l'environnement, puis arrêtés).

`--a-blanc` : ce qui serait fait, et ce qui bloque — rien n'est touché.
`--annuler` : la copie reprend sa place (le dossier migré est renommé
`<dossier>.migre-<date>`, jamais supprimé), les unités d'avant reviennent dans
leur état ; sortie 0 si le clone rendu a l'empreinte d'avant la migration.

Sorties : 0 fait (ou à blanc : rien ne bloque) · 1 refusé, ou un pas a échoué ·
2 mauvais usage.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROGRAMME = Path(__file__).resolve().parent.parent
MARQUE = ".cortex-programme"
SUFFIXE_COPIE = ".avant-paquet"
ETAT = ".migrer"
# La config locale du moteur : à côté de lui dans un clone, à la racine des données
# quand le programme est installé à part (`donnees.env_local`).
CONFIG_MOTEUR = Path("brain-engine/.env.local")
# Ce qu'un brain d'avant a laissé dans le programme et qui est une BASE : signalée.
BASE_SQLITE = re.compile(r"^brain-engine/brain\.db(-shm|-wal)?$")
# Les clés de `.env.local` qui désignent une base AILLEURS : sans base au clone, la
# migration pose une base locale vide (tranché le 8/10) — elles ne la viseraient plus.
CLES_BASE_DISTANTE = ("BRAIN_DOLT_PORT", "BRAIN_DOLT_HOST")
NE_PAS_DESCENDRE = {".git", "node_modules", ".venv", "__pycache__", "brain-dolt"}
# Écrits à chaque rendu du gabarit (une date dedans) : celui du paquet fait foi, celui du
# clone n'est pas une retouche — `kernel.lock` porte `generated_at`.
GENERES_AU_RENDU = {"kernel.lock"}


def dire(msg: str = "") -> None:
    print(msg, flush=True)


def _vue(programme: Path):
    """`scripts/vue.py` du programme : la liste des entrées du programme, une seule fois."""
    spec = importlib.util.spec_from_file_location("_brain_vue", programme / "scripts" / "vue.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def entrees_du_programme(programme: Path | None = None) -> list[str]:
    """Les entrées que la vue relie dans un dossier de données — celles que le paquet porte."""
    programme = programme or PROGRAMME
    return [e for e in _vue(programme).ENTREES_PROGRAMME if (programme / e).exists()]


def version(fichier: Path) -> tuple[int, ...] | None:
    try:
        m = re.search(r'^version:\s*"?([0-9][0-9.]*)"?', fichier.read_text(encoding="utf-8"), re.M)
    except OSError:
        return None
    return tuple(int(x) for x in m.group(1).strip(".").split(".")) if m else None


def texte_version(v: tuple[int, ...] | None) -> str:
    return ".".join(map(str, v)) if v else "?"


def git(depot: Path, *args: str, ok: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(depot), *args], capture_output=True, text=True,
                          check=ok)


# ── Ce qui bloque ─────────────────────────────────────────────────────────────

def depots_imbriques(dossier: Path) -> list[Path]:
    """Les satellites : chaque dépôt git sous le dossier (hors le dossier lui-même)."""
    trouves = []
    for racine, dossiers, fichiers in os.walk(dossier):
        r = Path(racine)
        if r != dossier and (".git" in dossiers or ".git" in fichiers):
            trouves.append(r)
        dossiers[:] = [d for d in dossiers if d not in NE_PAS_DESCENDRE
                       and not (r / d).is_symlink()]
    return sorted(trouves)


def etat_du_depot(depot: Path) -> tuple[list[str], int | None]:
    """(les lignes non commitées, le nombre de commits non poussés — None sans branche suivie)."""
    sale = [l for l in git(depot, "status", "--porcelain", "--untracked-files=normal").stdout.splitlines() if l]
    amont = git(depot, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if amont.returncode != 0:
        return sale, None
    avance = git(depot, "rev-list", "--count", "@{u}..HEAD").stdout.strip()
    return sale, int(avance or 0)


def suivis(depot: Path) -> set[str]:
    r = git(depot, "ls-files", "-z")
    return {p for p in r.stdout.split("\0") if p}


def classer(dossier: Path, programme: Path | None = None,
            entrees: list[str] | None = None, satellites: list[Path] | None = None) -> dict:
    """Chaque chemin des entrées du programme, dans le dossier, rangé :
    `programme` (le même fichier que le paquet), `retouches` (suivi, il diffère),
    `instance` (suivi, absent du paquet), `satellites` (un dépôt git imbriqué),
    `generes` (ni suivi ni du paquet : venv, caches…), `liens`, `config` (.env.local),
    `bases` (une base SQLite laissée dans le moteur)."""
    programme = programme or PROGRAMME
    entrees = entrees_du_programme(programme) if entrees is None else entrees
    satellites = depots_imbriques(dossier) if satellites is None else satellites
    connus = suivis(dossier)
    c = {k: [] for k in ("programme", "retouches", "instance", "satellites", "generes",
                         "liens", "config", "bases")}

    def ranger(rel: str) -> None:
        f, p = dossier / rel, programme / rel
        if Path(rel) == CONFIG_MOTEUR:
            c["config"].append(rel)
        elif BASE_SQLITE.match(rel):
            c["bases"].append(rel)
        elif f.is_symlink():
            c["instance" if rel in connus else "liens"].append(rel)
        elif p.is_file() and not p.is_symlink() and (rel in GENERES_AU_RENDU
                                                     or f.read_bytes() == p.read_bytes()):
            c["programme"].append(rel)
        elif rel in connus:
            c["retouches" if p.exists() else "instance"].append(rel)
        else:
            c["generes"].append(rel)

    sat = {s.relative_to(dossier).as_posix() for s in satellites}
    for e in entrees:
        d = dossier / e
        if not d.exists() and not d.is_symlink():
            continue
        if d.is_symlink() or d.is_file():
            ranger(e)
            continue
        for racine, dossiers, fichiers in os.walk(d):
            r = Path(racine)
            rel_r = r.relative_to(dossier).as_posix()
            if rel_r in sat:
                c["satellites"].append(rel_r)
                dossiers[:] = []
                continue
            for n in list(dossiers):
                if (r / n).is_symlink():
                    ranger((r / n).relative_to(dossier).as_posix())
                    dossiers.remove(n)
            for n in fichiers:
                ranger((r / n).relative_to(dossier).as_posix())
    for k in c:
        c[k].sort()
    return c


def config_des_donnees(texte: str, base_locale: bool) -> tuple[str, list[str]]:
    """(le `.env.local` des données, les clés retirées). Sans base au clone, la base d'avant
    était AILLEURS (un tunnel, un autre hôte) : ses clés partent, la base locale neuve (VIDE,
    tranché le 8/10) prend les siennes à `brain init`. Le reste passe tel quel."""
    lignes = texte.splitlines()
    retirees = [] if base_locale else [l.split("=", 1)[0].strip() for l in lignes
                                       if l.split("=", 1)[0].strip() in CLES_BASE_DISTANTE]
    gardees = [l for l in lignes if l.split("=", 1)[0].strip() not in retirees]
    return "\n".join(gardees) + "\n", retirees


def a_reprendre(copie: Path, dossier: Path) -> list[str]:
    """Les fichiers que le dépôt neuf reprend : ceux que le clone suivait et qui restent —
    hors de ce qui vit dans un satellite, qui est à LUI : l'ajouter ici ferait un gitlink
    sans `.gitmodules` (un répertoire vide au clonage), et le clone le suivait parfois aussi."""
    sats = [s.relative_to(dossier).as_posix() + "/" for s in depots_imbriques(dossier)]
    return sorted(p for p in suivis(copie)
                  if ((dossier / p).exists() or (dossier / p).is_symlink())
                  and not any(p.startswith(s) for s in sats))


def empreinte(dossier: Path) -> tuple[str, int]:
    """(sha256 de tout l'arbre, nombre d'entrées) — chemins, liens (leur cible), bit
    exécutable et contenu ; `.migrer/` à la racine exclu. Les dates n'y sont pas : une
    copie fidèle a la même empreinte."""
    h, n = hashlib.sha256(), 0
    for racine, dossiers, fichiers in os.walk(dossier):
        r = Path(racine)
        if r == dossier and ETAT in dossiers:
            dossiers.remove(ETAT)
        liens = [d for d in dossiers if (r / d).is_symlink()]
        dossiers[:] = sorted(d for d in dossiers if d not in liens)
        for nom in sorted(fichiers + liens):
            f = r / nom
            rel = f.relative_to(dossier).as_posix()
            if f.is_symlink():
                h.update(f"L {rel} -> {os.readlink(f)}\n".encode())
            else:
                exe = "x" if os.access(f, os.X_OK) else "-"
                h.update(f"F {rel} {exe} ".encode())
                with open(f, "rb") as fh:
                    for bloc in iter(lambda: fh.read(1 << 20), b""):
                        h.update(bloc)
                h.update(b"\n")
            n += 1
    return h.hexdigest(), n


def nom_du_brain(dossier: Path) -> str:
    try:
        m = re.search(r"^\s*brain_name:\s*\"?([^\s\"#]+)", (dossier / "brain-compose.local.yml")
                      .read_text(encoding="utf-8"), re.M)
    except OSError:
        m = None
    return m.group(1) if m else dossier.name


def examiner(dossier: Path, laisser_l_instance: bool) -> tuple[list[str], list[str], dict]:
    """(ce qui bloque, ce qui se dit sans bloquer, le classement)."""
    bloque, notes = [], []
    if not (dossier / ".git").exists():
        return [f"{dossier} n'est pas un dépôt git — `brain migrer` reçoit un brain cloné"], notes, {}
    if (dossier / "scripts").is_symlink():
        return [f"{dossier} est déjà servi par un programme installé à part (scripts/ est un lien)"], notes, {}
    if not (dossier / "brain-compose.yml").is_file() or not (dossier / "scripts" / "brain").is_file():
        return [f"{dossier} n'est pas un brain (ni brain-compose.yml, ni scripts/brain)"], notes, {}

    v_clone, v_paquet = version(dossier / "brain-compose.yml"), version(PROGRAMME / "brain-compose.yml")
    if v_clone and v_paquet and v_paquet < v_clone:
        bloque.append(f"le paquet ({texte_version(v_paquet)}) est plus ancien que le clone "
                      f"({texte_version(v_clone)}) — installer la version du clone ou une plus récente")

    copie = dossier.with_name(dossier.name + SUFFIXE_COPIE)
    if copie.exists() or copie.is_symlink():
        bloque.append(f"{copie} existe déjà — une migration précédente ? Rien n'est écrasé")

    satellites = depots_imbriques(dossier)
    for depot in [dossier, *satellites]:
        nom = "le clone" if depot == dossier else f"le satellite {depot.relative_to(dossier)}"
        sale, avance = etat_du_depot(depot)
        if sale:
            bloque.append(f"{nom} a du travail non commité ({len(sale)}) : "
                          + ", ".join(l[3:] for l in sale[:4]) + (" …" if len(sale) > 4 else ""))
        if avance:
            bloque.append(f"{nom} a {avance} commit(s) non poussé(s)")
        if avance is None:
            notes.append(f"{nom} n'a pas de branche suivie — son histoire reste dans la copie")

    c = classer(dossier, satellites=satellites)
    for rel in c["retouches"][:8]:
        bloque.append(f"retouche locale (diffère du paquet) : {rel}")
    if len(c["retouches"]) > 8:
        bloque.append(f"… et {len(c['retouches']) - 8} autre(s) retouche(s)")
    propres = c["instance"] + [s + "/ (satellite)" for s in c["satellites"]]
    if propres:
        texte = (f"{len(propres)} chemin(s) de l'instance dans les entrées du programme, que le "
                 f"paquet ne porte pas : " + ", ".join(propres[:6]) + (" …" if len(propres) > 6 else ""))
        if laisser_l_instance:
            notes.append(texte + " — laissés à la copie (--laisser-l-instance)")
        else:
            bloque.append(texte + " — les laisser à la copie : --laisser-l-instance")
    if c["bases"]:
        notes.append("une base SQLite dans le moteur (" + ", ".join(c["bases"])
                     + ") — elle reste dans la copie ; le brain migré a sa base Dolt")
    return bloque, notes, c


# ── Ce qui tourne ─────────────────────────────────────────────────────────────

def dossier_des_unites() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"


def unites_du_brain(dossier: Path) -> list[Path]:
    """Les unités utilisateur de CE brain : un nom `brain*` (ou `dolt-server`), et un service
    dont le fichier désigne le dossier — un timer suit son service (`Unit=`, sinon le même
    nom). Le nom seul ne suffit pas : une machine qui porte deux brains (le fixe, qui forge,
    et un clone d'essai) verrait l'autre perdre ses services. Une unité qui ne cite pas le
    dossier (un tunnel ssh) n'est pas touchée."""
    d = dossier_des_unites()
    if not d.is_dir():
        return []
    noms = {str(dossier).rstrip("/"), str(dossier.resolve()).rstrip("/")}
    motif = re.compile("(?:" + "|".join(re.escape(n) for n in noms) + r""")(?=$|[/\s"'=:;])""", re.M)

    def lire(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    candidates = [p for p in d.iterdir() if p.is_file() and p.suffix in (".service", ".timer")
                  and (p.name.startswith("brain") or p.name == "dolt-server.service")]
    services = {p.name for p in candidates if p.suffix == ".service" and motif.search(lire(p))}

    def cible_du_timer(p: Path) -> str:
        m = re.search(r"^\s*Unit\s*=\s*(\S+)", lire(p), re.M)
        return m.group(1) if m else p.with_suffix(".service").name
    return sorted(p for p in candidates
                  if p.name in services or (p.suffix == ".timer" and cible_du_timer(p) in services))


def systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def lien_de_la_commande() -> Path:
    return Path.home() / ".local" / "bin" / "brain"


def commande_du_paquet() -> Path | None:
    """`brain` du venv qui porte ce programme (celui de pipx) : `<venv>/bin/brain`."""
    d = PROGRAMME
    while d != d.parent:
        if (d / "pyvenv.cfg").is_file():
            b = d / "bin" / "brain"
            return b if b.exists() else None
        d = d.parent
    return None


def hooks_globaux() -> list[str]:
    f = Path.home() / ".claude" / "settings.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cmds = []
    for liste in (d.get("hooks") or {}).values():
        for m in liste or []:
            for h in (m or {}).get("hooks", []):
                if h.get("command"):
                    cmds.append(h["command"])
    return cmds


def chemins_vises(commande: str, dossier: Path) -> list[str]:
    return [t.strip("\"'") for t in commande.split() if t.strip("\"'").startswith(str(dossier) + "/")]


def demarrer_le_temps_du_doctor(dossier: Path, env: dict) -> subprocess.Popen | None:
    """`--sans-service` : la base (si le brain en a une) et le moteur, lancés à la main."""
    dolt = None
    base = dossier / "brain-dolt"
    if (base / "config.yaml").is_file() and shutil.which("dolt"):
        dolt = subprocess.Popen(["dolt", "sql-server", "--config", "config.yaml"], cwd=base, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        m = re.search(r"^\s*port:\s*(\d+)", (base / "config.yaml").read_text(encoding="utf-8"), re.M)
        port = int(m.group(1)) if m else 3307
        import socket
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
    subprocess.run(["bash", str(PROGRAMME / "scripts" / "brain-engine.sh"), "start"], cwd=dossier, env=env,
                   capture_output=True, text=True)
    time.sleep(3)
    return dolt


def arreter_apres_le_doctor(dossier: Path, env: dict, dolt: subprocess.Popen | None) -> None:
    subprocess.run(["bash", str(PROGRAMME / "scripts" / "brain-engine.sh"), "stop"], cwd=dossier, env=env,
                   capture_output=True, text=True)
    if dolt is not None and dolt.poll() is None:
        dolt.terminate()
        try:
            dolt.wait(10)
        except subprocess.TimeoutExpired:
            dolt.kill()


# ── Migrer ────────────────────────────────────────────────────────────────────

def migrer(dossier: Path, a_blanc: bool, sans_service: bool, laisser: bool) -> int:
    if not (PROGRAMME / MARQUE).exists():
        dire(f"❌ brain migrer se lance depuis le programme installé (pipx install brain-cortex), "
             f"pas depuis un clone — {PROGRAMME} n'est pas marqué {MARQUE}.")
        return 1
    dire(f"── brain migrer {dossier}")
    dire(f"   programme : {PROGRAMME} ({texte_version(version(PROGRAMME / 'brain-compose.yml'))})")
    bloque, notes, c = examiner(dossier, laisser)
    for n in notes:
        dire(f"   ℹ️  {n}")
    if c:
        dire(f"   le programme quitte le dossier : {len(c['programme'])} fichier(s) du paquet, "
             f"{len(c['generes'])} généré(s), {len(c['liens'])} lien(s)"
             + (f" ; {len(c['instance']) + len(c['satellites'])} de l'instance, laissés à la copie"
                if laisser and (c['instance'] or c['satellites']) else ""))
    if bloque:
        dire("❌ refusé — rien n'a été touché :")
        for b in bloque:
            dire(f"   · {b}")
        return 1
    copie = dossier.with_name(dossier.name + SUFFIXE_COPIE)
    if a_blanc:
        dire(f"✅ à blanc : rien ne bloque. La copie irait à {copie} ; le dossier deviendrait un "
             f"dépôt de données neuf, servi par le paquet.")
        return 0

    # 1. Les unités : leurs fichiers et leur état, puis arrêtées.
    unites = []
    for u in unites_du_brain(dossier):
        etat = {"nom": u.name, "active": False, "enabled": False}
        if not sans_service:
            etat["active"] = systemctl("is-active", u.name).stdout.strip() == "active"
            etat["enabled"] = systemctl("is-enabled", u.name).stdout.strip() == "enabled"
            systemctl("disable", "--now", u.name)
        unites.append(etat)
    if unites:
        dire(f"  ✅ 1. unités du brain {'notées (sans service)' if sans_service else 'arrêtées et désactivées'} : "
             + ", ".join(u["nom"] for u in unites))
    else:
        dire("  ✅ 1. aucune unité du brain sur cette machine")

    # 2. La copie, et l'état d'avant.
    signature, nombre = empreinte(dossier)
    if subprocess.run(["cp", "-a", "--", str(dossier), str(copie)]).returncode != 0:
        dire(f"❌ 2. la copie vers {copie} a échoué — le dossier n'est pas touché ; les unités "
             f"arrêtées se relancent par systemctl --user start, ou retirer la copie partielle.")
        return 1
    if empreinte(copie)[0] != signature:
        dire(f"❌ 2. la copie {copie} n'est pas fidèle au dossier — rien d'autre n'est touché. "
             f"La retirer à la main après l'avoir regardée.")
        return 1
    etat_dir = copie / ETAT
    (etat_dir / "systemd").mkdir(parents=True)
    for u in unites_du_brain(dossier):
        shutil.copy2(u, etat_dir / "systemd" / u.name)
    reglages = Path.home() / ".claude" / "settings.json"
    if reglages.is_file() and str(dossier) in reglages.read_text(encoding="utf-8", errors="replace"):
        shutil.copy2(reglages, etat_dir / "claude-settings.json")
    lien = lien_de_la_commande()
    pointeur = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "brain-cortex" / "brain"
    (etat_dir / "etat.json").write_text(json.dumps({
        "dossier": str(dossier), "copie": str(copie), "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "empreinte": signature, "entrees": nombre, "unites": unites,
        "lien_brain": os.readlink(lien) if lien.is_symlink() else None,
        "pointeur": pointeur.read_text(encoding="utf-8") if pointeur.is_file() else None,
        "programme": str(PROGRAMME), "sans_service": sans_service,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dire(f"  ✅ 2. la copie : {copie} ({nombre} entrées, empreinte {signature[:12]}…, identique)")

    # 3. Le programme quitte le dossier — chaque entrée entière ; la config du moteur passe à la racine.
    config = dossier / CONFIG_MOTEUR
    if config.is_file() and not (dossier / ".env.local").exists():
        lignes, retirees = config_des_donnees(config.read_text(encoding="utf-8"),
                                              (dossier / "brain-dolt" / ".dolt").is_dir())
        if retirees:
            dire(f"     .env.local : {', '.join(retirees)} retirée(s) — la base d'avant était "
                 f"ailleurs, le brain migré a la sienne")
        (dossier / ".env.local").write_text(lignes, encoding="utf-8")
    for e in entrees_du_programme():
        d = dossier / e
        if d.is_symlink() or d.is_file():
            d.unlink()
        elif d.is_dir():
            shutil.rmtree(d)
    reste = [e for e in entrees_du_programme() if (dossier / e).exists() or (dossier / e).is_symlink()]
    if reste:
        dire(f"❌ 3. des entrées du programme restent : {', '.join(reste)} — `brain migrer --annuler`")
        return 1
    dire("  ✅ 3. le programme a quitté le dossier (la copie le garde)")

    # 4. Un dépôt de données neuf : ce que le clone suivait, et qui reste.
    shutil.rmtree(dossier / ".git")
    git(dossier, "init", "-q", ok=True)
    gi = dossier / ".gitignore"
    # Sondé par un chemin DANS la base : `brain-dolt/` (règle de dossier) ne prend pas un
    # chemin qui n'existe pas encore, sondé seul.
    regles = [r for r, sonde in (("/.env.local", ".env.local"), ("/brain-dolt/", "brain-dolt/.dolt"))
              if git(dossier, "check-ignore", "-q", "--no-index", sonde).returncode != 0]
    if regles:
        with open(gi, "a", encoding="utf-8") as f:
            f.write("\n# brain migrer — la config locale et la base ne se versionnent pas\n"
                    + "\n".join(regles) + "\n")
    garder = a_reprendre(copie, dossier)
    if gi.exists() and ".gitignore" not in garder:
        garder.append(".gitignore")
    liste = copie / ETAT / "suivis.txt"
    liste.write_text("\0".join(garder), encoding="utf-8")
    ident = []
    if not git(dossier, "config", "user.email").stdout.strip():
        nom = git(copie, "config", "user.name").stdout.strip() or "brain migrer"
        courriel = git(copie, "config", "user.email").stdout.strip() or "brain@localhost"
        ident = ["-c", f"user.name={nom}", "-c", f"user.email={courriel}"]
    if garder:
        r = subprocess.run(["git", "-C", str(dossier), "add", "-f", "--pathspec-from-file", str(liste),
                            "--pathspec-file-nul"], capture_output=True, text=True)
        if r.returncode != 0:
            dire(f"❌ 4. git add : {r.stderr.strip()[:300]} — `brain migrer --annuler`")
            return 1
    r = subprocess.run(["git", "-C", str(dossier), *ident, "commit", "-q", "--no-verify", "--allow-empty",
                        "-m", f"config: les données du brain, reprises de son clone ({copie.name})"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        dire(f"❌ 4. le premier commit : {r.stderr.strip()[:300]} — `brain migrer --annuler`")
        return 1
    dire(f"  ✅ 4. un dépôt de données neuf : {len(garder)} fichier(s) suivis repris ; "
         f"l'histoire d'avant est dans {copie.name}/.git")

    # 5. Ce que `brain init` pose pour un dossier existant.
    args = ["bash", str(PROGRAMME / "scripts" / "brain-init.sh"), nom_du_brain(dossier), str(dossier)]
    if sans_service:
        args.append("--sans-service")
    env = {k: v for k, v in os.environ.items() if k != "BRAIN_ROOT"}
    journal = copie / ETAT / "init.log"
    with open(journal, "w", encoding="utf-8") as f:
        code = subprocess.run(args, cwd=dossier, env=env, stdout=f, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL).returncode
    if code != 0:
        dire(f"❌ 5. brain init a échoué (code {code}) — {journal} ; `brain migrer --annuler`")
        return 1
    dire(f"  ✅ 5. brain init : le pointeur, la vue, la base, les hooks ({journal})")

    # 6. La commande `brain`, et les hooks globaux de Claude Code.
    cible = commande_du_paquet()
    if lien.is_symlink() and os.readlink(lien).startswith(str(dossier) + "/") and cible:
        lien.unlink()
        lien.symlink_to(cible)
        dire(f"  ✅ 6. la commande {lien} désignait le clone — elle désigne le paquet ({cible})")
    else:
        dire(f"  ✅ 6. la commande {lien} : laissée telle quelle")
    morts = sorted({p for cmd in hooks_globaux() for p in chemins_vises(cmd, dossier)
                    if not Path(p).exists()})
    for p in morts:
        dire(f"     ⚠️  un hook global de Claude Code (~/.claude/settings.json) vise {p}, qui n'existe "
             f"plus — à retirer ou à remplacer (la copie de tes réglages : {ETAT}/claude-settings.json)")

    # 7. Le doctor. Sans service, rien ne tourne : la base et les portes sont lancées le temps
    # du doctor (aux ports de l'environnement), puis arrêtées — un verdict, pas une abstention.
    env_d = {**env, "BRAIN_ROOT": str(dossier)}
    lances = demarrer_le_temps_du_doctor(dossier, env_d) if sans_service else None
    try:
        r = subprocess.run(["bash", str(PROGRAMME / "scripts" / "brain"), "doctor"], cwd=dossier,
                           env=env_d, capture_output=True, text=True)
    finally:
        if lances is not None:
            arreter_apres_le_doctor(dossier, env_d, lances)
    (copie / ETAT / "doctor.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    if r.returncode != 0:
        rouges = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith("❌")][:6]
        dire(f"❌ 7. le doctor n'est pas vert (code {r.returncode}) — {copie / ETAT / 'doctor.log'}")
        for l in rouges:
            dire(f"     {l[:140]}")
        dire("   Revenir au clone : brain migrer --annuler")
        return 1
    dire("  ✅ 7. le doctor est vert")
    dire(f"\n✅ {dossier} est servi par le paquet. La copie {copie} reste jusqu'à ce que tu la retires.")
    return 0


# ── Annuler ───────────────────────────────────────────────────────────────────

def annuler(dossier: Path, sans_service: bool) -> int:
    copie = dossier.with_name(dossier.name + SUFFIXE_COPIE)
    etat_f = copie / ETAT / "etat.json"
    if not etat_f.is_file():
        dire(f"❌ rien à annuler : pas de copie migrée à {copie} ({ETAT}/etat.json absent).")
        return 1
    etat = json.loads(etat_f.read_text(encoding="utf-8"))
    dire(f"── brain migrer --annuler {dossier}")
    if not sans_service:
        for u in unites_du_brain(dossier):
            systemctl("disable", "--now", u.name)
    migre = None
    if dossier.exists() or dossier.is_symlink():
        migre = dossier.with_name(f"{dossier.name}.migre-{time.strftime('%Y%m%d-%H%M%S')}")
        dossier.rename(migre)
        dire(f"  ✅ le dossier migré est mis de côté : {migre}")
    copie.rename(dossier)
    garde = (migre or dossier.with_name(f"{dossier.name}.annule-{time.strftime('%Y%m%d-%H%M%S')}"))
    garde.mkdir(exist_ok=True)
    (dossier / ETAT).rename(garde / (ETAT + "-annule"))
    etat_dir = garde / (ETAT + "-annule")
    dire(f"  ✅ la copie reprend sa place : {dossier}")

    unites = dossier_des_unites()
    sauvees = sorted((etat_dir / "systemd").glob("*")) if (etat_dir / "systemd").is_dir() else []
    if sauvees:
        unites.mkdir(parents=True, exist_ok=True)
        for u in sauvees:
            shutil.copy2(u, unites / u.name)
    if not sans_service:
        systemctl("daemon-reload")
        for u in etat.get("unites", []):
            if u.get("enabled"):
                systemctl("enable", u["nom"])
            if u.get("active"):
                systemctl("start", u["nom"])
    dire(f"  ✅ les unités d'avant : {len(sauvees)} fichier(s) remis"
         + ("" if sans_service else ", leur état rétabli"))

    lien = lien_de_la_commande()
    if etat.get("lien_brain") and (lien.is_symlink() or not lien.exists()):
        if lien.is_symlink():
            lien.unlink()
        lien.parent.mkdir(parents=True, exist_ok=True)
        lien.symlink_to(etat["lien_brain"])
    pointeur = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "brain-cortex" / "brain"
    if etat.get("pointeur") is not None:
        pointeur.write_text(etat["pointeur"], encoding="utf-8")
    elif pointeur.is_file() and pointeur.read_text(encoding="utf-8").strip() == str(dossier):
        pointeur.unlink()

    signature, nombre = empreinte(dossier)
    if signature != etat.get("empreinte"):
        dire(f"❌ le clone rendu n'a pas l'empreinte d'avant la migration ({signature[:12]}… / "
             f"{str(etat.get('empreinte'))[:12]}…) — regarder {dossier}")
        return 1
    dire(f"\n✅ le clone est rendu à l'identique ({nombre} entrées, empreinte {signature[:12]}…). "
         f"Le dossier migré reste à {garde}.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="brain migrer", description=__doc__.splitlines()[0])
    p.add_argument("dossier", nargs="?", type=Path, help="le brain cloné (défaut : le dossier courant)")
    p.add_argument("--a-blanc", action="store_true", help="dire ce qui serait fait — rien n'est touché")
    p.add_argument("--annuler", action="store_true", help="rendre le clone d'avant la migration")
    p.add_argument("--sans-service", action="store_true", help="sans systemd (conteneur, essai)")
    p.add_argument("--laisser-l-instance", action="store_true",
                   help="laisser à la copie ce que l'instance a dans les entrées du programme")
    a = p.parse_args()
    dossier = (a.dossier or Path.cwd()).expanduser().absolute()
    if a.annuler:
        return annuler(dossier, a.sans_service)
    if not dossier.is_dir():
        dire(f"❌ {dossier} n'est pas un dossier.")
        return 2
    return migrer(dossier.resolve(), a.a_blanc, a.sans_service, a.laisser_l_instance)


if __name__ == "__main__":
    sys.exit(main())
