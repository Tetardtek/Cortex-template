#!/usr/bin/env python3
"""La zone learning tient-elle ?

Le modèle de la zone projet, appliqué aux tracks. Tranché par l'owner
le 2/10 : **la fiche d'une track est son index et ses liens** — ce qu'elle porte,
et ce qu'elle nourrit, dans le brain ou dehors. Pas de fiches de tâches : ses
modules sont ses unités de progression.

    une track                `learning/<slug>/README.md`, `type: learning-track`
    son cycle de vie         `status:` dans seed · exploring · active · pause · close
    ce qu'elle nourrit       `feeds:` — des slugs qui EXISTENT : un projet
                             (`projets/<slug>.md`), une track, ou un élément de `vie/`
    ses liens                `liens:` — une URL, ou un chemin du brain qui existe
    sa machine               une fiche qui porte un CONSTAT SYSTÈME (un chemin `/etc/`,
                             `~/.config/`, un service, `ufw`, un paquet…) dit où il a été
                             pris : `mesure_sur:` en tête, ou `> 📍 mesuré sur …` par
                             section. Une track sans constat système n'a rien à
                             marquer, et ne rougit jamais.

Ce qui pourrirait en silence sans lui (mesuré le 2/10) : la table de
`learning/README.md`, écrite à la main, contredisait les fiches ; `feeds:` était
du texte libre — 5 cibles réelles sur 15 ; toutes les tracks disaient
`exploring`. La table est donc GÉNÉRÉE entre deux marqueurs :

    python3 tools/zone_learning.py --brain ~/Dev/Brain              # juger
    python3 tools/zone_learning.py --brain ~/Dev/Brain --ecrire     # régénérer la table
    python3 tools/zone_learning.py --brain ~/Dev/Brain --projet <slug>

`--projet` est la vue « tracks liées » d'un projet : DÉDUITE des `feeds:`, jamais
déclarée côté projet — deux déclarations, deux sources, une dérive.

Il s'éprouve avant de juger. Sortie 1 si la zone ne tient pas. Pas de
`learning/` : abstention.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

STATUTS = ("seed", "exploring", "active", "pause", "close")
DEBUT, FIN = "<!-- genere:tracks -->", "<!-- /genere:tracks -->"
URL = re.compile(r"^https?://")
# Un constat système : vrai sur UNE machine, faux lu sur l'autre — le 26/09,
# `/etc/sddm.conf.d` cherché deux fois sur le fixe ; il vivait sur le laptop.
CONSTAT_SYSTEME = re.compile(r"(?<![\w.])(/etc/|/usr/|/var/|/boot/|/proc/|/sys/|~/\.config/|"
                             r"systemctl\b|journalctl\b|\bufw\b|\bpacman -|\byay -|\.service\b|"
                             r"\bmkinitcpio\b|\bfstab\b)")
# Les noms de machine sont ceux de l'instance : on exige qu'il y en ait un, pas lequel.
MACHINE = re.compile(r"^mesure_sur:[ \t]*\S|^>[ \t]*📍[ \t]*mesuré sur \S", re.M)


def _meta(fichier: Path) -> dict:
    texte = fichier.read_text(encoding="utf-8")
    if not texte.startswith("---\n"):
        return {}
    fin = texte.find("\n---", 4)
    if fin < 0:
        return {}
    import yaml
    try:
        return yaml.safe_load(texte[4:fin]) or {}
    except yaml.YAMLError:
        return {}


def _liste(valeur) -> list[str]:
    if valeur is None:
        return []
    return [str(v) for v in (valeur if isinstance(valeur, list) else [valeur])]


def tracks(brain: Path) -> dict[str, dict]:
    """Les tracks : chaque dossier de `learning/` qui a sa fiche `README.md`."""
    racine = Path(brain) / "learning"
    return {d.name: _meta(d / "README.md") for d in sorted(racine.iterdir())
            if d.is_dir() and not d.name.startswith((".", "_")) and (d / "README.md").is_file()}


def fiches_de_learning(brain: Path) -> list[Path]:
    """Les `.md` de `learning/` que le dépôt suit — un `node_modules` ou un outil
    vendu dans un lab n'est pas une fiche. Hors dépôt git : tout, sauf les dossiers cachés."""
    import subprocess
    racine = Path(brain) / "learning"
    r = subprocess.run(["git", "-C", str(racine), "ls-files", "-z", "--", "*.md"],
                       capture_output=True, text=True)
    if r.returncode == 0 and (racine / ".git").exists():
        return sorted(racine / x for x in r.stdout.split("\0") if x)
    return sorted(f for f in racine.rglob("*.md")
                  if not any(p.startswith(".") or p == "node_modules" for p in f.relative_to(racine).parts))


def cible_existe(brain: Path, slug: str) -> bool:
    b = Path(brain)
    return ((b / "projets" / f"{slug}.md").is_file() or (b / "learning" / slug / "README.md").is_file()
            or (b / "vie" / f"{slug}.md").is_file() or (b / "vie" / slug).is_dir())


def juger(brain: Path) -> list[str]:
    brain = Path(brain)
    racine = brain / "learning"
    defauts = []
    # 1. une track a sa fiche, au bon endroit
    for d in sorted(racine.iterdir()):
        if d.is_dir() and not d.name.startswith((".", "_")) and not (d / "README.md").is_file():
            defauts.append(f"learning/{d.name}/ n'a pas de fiche README.md")
    for f in sorted(racine.glob("*.md")):
        if str(_meta(f).get("type")) == "learning-track":
            defauts.append(f"learning/{f.name} est une fiche de track à la racine — "
                           f"la ramener en learning/{f.stem}/README.md (et laisser un redirect)")
    # 2-4. ce que la fiche déclare
    for slug, m in tracks(brain).items():
        ou = f"learning/{slug}/README.md"
        if str(m.get("type")) != "learning-track":
            defauts.append(f"{ou} : `type: {m.get('type')}` — attendu learning-track")
        if str(m.get("status")) not in STATUTS:
            defauts.append(f"{ou} : `status: {m.get('status')}` — attendu {' · '.join(STATUTS)}")
        for cible in _liste(m.get("feeds")):
            if not cible_existe(brain, cible):
                defauts.append(f"{ou} : `feeds:` nomme « {cible} », qui n'est ni un projet, "
                               f"ni une track, ni un élément de vie/")
        for lien in _liste(m.get("liens")):
            if not URL.match(lien) and not (brain / lien).exists():
                defauts.append(f"{ou} : `liens:` « {lien} » n'est ni une URL ni un chemin du brain")
    # 5. la table générée dit ce que les fiches disent
    index = racine / "README.md"
    if index.is_file():
        texte = index.read_text(encoding="utf-8")
        if DEBUT in texte and FIN in texte:
            if bloc(texte) != table(brain):
                defauts.append("learning/README.md : la table des tracks ne dit plus ce que les "
                               "fiches disent — `--ecrire` pour la régénérer")
        elif tracks(brain):
            # Sans track, rien à tabler : un fork installé avant la table ne rougit pas.
            defauts.append(f"learning/README.md : pas de table générée ({DEBUT} … {FIN})")
    # 6. un constat système dit sur quelle machine il a été pris
    for f in fiches_de_learning(brain):
        if not f.is_file():
            continue
        texte = f.read_text(encoding="utf-8", errors="replace")
        constat = CONSTAT_SYSTEME.search(texte)
        if constat and not MACHINE.search(texte):
            defauts.append(f"learning/{f.relative_to(racine)} porte un constat système "
                           f"(« {constat.group(1)} ») sans dire sur quelle machine — "
                           f"`mesure_sur:` en tête, ou `> 📍 mesuré sur …` par section")
    return defauts


def table(brain: Path) -> str:
    lignes = ["| Track | Statut | Domaine | Nourrit |", "|-------|--------|---------|---------|"]
    for slug, m in tracks(brain).items():
        domaine = ", ".join(_liste(m.get("domain"))) or "—"
        feeds = ", ".join(_liste(m.get("feeds"))) or "—"
        lignes.append(f"| [{slug}]({slug}/) | {m.get('status')} | {domaine} | {feeds} |")
    return "\n".join(lignes)


def bloc(texte: str) -> str:
    return texte[texte.index(DEBUT) + len(DEBUT):texte.index(FIN)].strip("\n")


def tracks_de(brain: Path, projet: str) -> list[str]:
    """La vue « tracks liées » d'un projet — déduite, jamais déclarée."""
    return [s for s, m in tracks(brain).items() if projet in _liste(m.get("feeds"))]


def auto_epreuve() -> list[str]:
    def brain_jetable(tmp: Path, fiches: dict[str, str], racine: dict[str, str] | None = None,
                      sans_fiche: tuple = (), modules: dict[str, str] | None = None) -> Path:
        (tmp / "projets").mkdir()
        (tmp / "projets" / "mon-projet.md").write_text("---\nname: mon-projet\n---\n", encoding="utf-8")
        (tmp / "vie" / "un-terrain").mkdir(parents=True)
        (tmp / "learning").mkdir()
        for slug, tete in fiches.items():
            (tmp / "learning" / slug).mkdir()
            (tmp / "learning" / slug / "README.md").write_text(f"---\n{tete}\n---\n", encoding="utf-8")
        for nom, tete in (racine or {}).items():
            (tmp / "learning" / nom).write_text(f"---\n{tete}\n---\n", encoding="utf-8")
        for d in sans_fiche:
            (tmp / "learning" / d).mkdir()
        for chemin, texte in (modules or {}).items():
            (tmp / "learning" / chemin).write_text(texte, encoding="utf-8")
        (tmp / "learning" / "README.md").write_text(f"# idx\n{DEBUT}\n{FIN}\n", encoding="utf-8")
        (tmp / "learning" / "README.md").write_text(f"# idx\n{DEBUT}\n{table(tmp)}\n{FIN}\n", encoding="utf-8")
        return tmp

    sain = "type: learning-track\nstatus: exploring\nfeeds: [mon-projet, autre, un-terrain]\nliens: [https://x.example, projets/mon-projet.md]"
    autre = "type: learning-track\nstatus: seed"
    cas = {
        "un statut hors énumération": ({"t": sain.replace("exploring", "acquired"), "autre": autre}, None, ()),
        "un feeds qui ne désigne rien": ({"t": sain.replace("mon-projet,", "owl,"), "autre": autre}, None, ()),
        "un lien qui n'existe pas": ({"t": sain.replace("projets/mon-projet.md", "nulle/part.md"), "autre": autre}, None, ()),
        "une fiche de track à la racine": ({"t": sain, "autre": autre}, {"vieille.md": "type: learning-track"}, ()),
        "un dossier de track sans fiche": ({"t": sain, "autre": autre}, None, ("orpheline",)),
        "un type faux": ({"t": sain.replace("learning-track", "learning-module"), "autre": autre}, None, ()),
    }
    # L'incident d'origine, copié tel quel : un constat du laptop, lu sur le fixe.
    incident = ("---\nname: m07\ntype: learning-module\n---\n\n"
                "SDDM est en autologin dans `/etc/sddm.conf.d/` ; la règle `ufw` IGMP laisse passer le mDNS.\n")
    rates = []
    with tempfile.TemporaryDirectory(prefix="zone-learning-") as tmp:
        if not juger(brain_jetable(Path(tmp), {"t": sain, "autre": autre}, modules={"t/m07.md": incident})):
            rates.append("non vu : un constat système qui ne dit pas sa machine (l'incident d'origine)")
    with tempfile.TemporaryDirectory(prefix="zone-learning-") as tmp:
        b = brain_jetable(Path(tmp), {"t": sain, "autre": autre}, modules={
            "t/m07.md": incident.replace("type: learning-module", "type: learning-module\nmesure_sur: laptop"),
            "t/m09.md": "# m09\n\n## 1\n\n> 📍 mesuré sur le fixe\n\n`systemctl --user status`\n",
            "autre/pitch.md": "# Le pitch\n\nTrois phrases, une promesse, une preuve.\n"})
        if juger(b):
            rates.append(f"témoin négatif : un constat marqué, ou une track sans constat, rougit ({juger(b)[0]})")
    for nom, (fiches, racine, sans) in cas.items():
        with tempfile.TemporaryDirectory(prefix="zone-learning-") as tmp:
            if not juger(brain_jetable(Path(tmp), fiches, racine, sans)):
                rates.append(f"non vu : {nom}")
    with tempfile.TemporaryDirectory(prefix="zone-learning-") as tmp:
        b = brain_jetable(Path(tmp), {"t": sain, "autre": autre}, {"inbox.md": "type: inbox"})
        if juger(b):
            rates.append(f"témoin négatif : une zone saine rougit ({juger(b)[0]})")
        if tracks_de(b, "mon-projet") != ["t"]:
            rates.append("la vue d'un projet ne déduit pas ses tracks")
        idx = b / "learning" / "README.md"
        idx.write_text(idx.read_text(encoding="utf-8").replace("| seed |", "| exploring |"), encoding="utf-8")
        if not juger(b):
            rates.append("non vu : une table écrite à la main qui contredit les fiches")
        idx.write_text("# idx sans marqueurs\n", encoding="utf-8")
        if not juger(b):
            rates.append("non vu : des tracks sans table générée")
    with tempfile.TemporaryDirectory(prefix="zone-learning-") as tmp:
        vide = Path(tmp)
        (vide / "learning").mkdir()
        (vide / "learning" / "README.md").write_text("# un fork neuf\n", encoding="utf-8")
        if juger(vide):
            rates.append("témoin négatif : un learning/ sans track rougit")
    return rates


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    p.add_argument("--ecrire", action="store_true", help="régénérer la table de learning/README.md")
    p.add_argument("--projet", help="les tracks qui nourrissent ce projet")
    a = p.parse_args()
    brain = a.brain.expanduser().resolve()

    rates = auto_epreuve()
    if rates:
        print("\nLA ZONE LEARNING — l'auto-épreuve a échoué, rien n'est jugé :")
        for r in rates:
            print(f"  ❌ {r}")
        return 1
    if not (brain / "learning").is_dir():
        print(f"SKIP pas de `learning/` dans {brain} — pas de zone learning à juger")
        return 0
    if a.projet:
        liees = tracks_de(brain, a.projet)
        print(f"{a.projet} — nourri par : {', '.join(liees) if liees else 'aucune track'}")
        return 0
    if a.ecrire:
        index = brain / "learning" / "README.md"
        texte = index.read_text(encoding="utf-8")
        if DEBUT not in texte or FIN not in texte:
            print(f"  ❌ learning/README.md n'a pas les marqueurs {DEBUT} … {FIN}")
            return 1
        neuf = texte[:texte.index(DEBUT) + len(DEBUT)] + "\n" + table(brain) + "\n" + texte[texte.index(FIN):]
        index.write_text(neuf, encoding="utf-8")
        print("  ✍️  learning/README.md — la table régénérée")
    defauts = juger(brain)
    print("\nLA ZONE LEARNING\n")
    print("  auto-épreuve         9 défauts vus, une zone saine ne rougit pas")
    print(f"  tracks               {len(tracks(brain))}")
    if not defauts:
        print("\n  ✅ chaque track a sa fiche, un statut, des feeds et des liens qui désignent quelque chose ; chaque constat système dit sa machine")
        return 0
    for d in defauts[:14]:
        print(f"  ❌ {d}")
    if len(defauts) > 14:
        print(f"     … et {len(defauts) - 14} autre(s)")
    print("\nVERDICT: la zone learning ne tient pas")
    return 1


if __name__ == "__main__":
    sys.exit(main())
