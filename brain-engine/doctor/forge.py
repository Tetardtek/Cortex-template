#!/usr/bin/env python3
"""La forge d'un dépôt, choisie par son adresse — `pour(depot).call(...)`.

Les outils du backlog (`kanban.py`, `backlog_issues.py`) parlent à la forge par
un seul geste, `call(méthode, chemin, corps) -> (code HTTP, json)`, avec les
chemins de l'API Gitea (`/repos/o/n/pulls`, `…/merge {"Do": …}`, …). Ils le
tenaient d'un outil de l'instance d'origine, chargé par son chemin : un brain
qui n'avait pas cet outil, ou une autre forge, n'avait rien.

Ce module choisit la forge par l'ADRESSE du dépôt, telle que la fiche projet la
déclare (`repo: <hôte>/<owner>/<nom>`) :

    github.com/<o>/<n>     `gh api` — son authentification ; aucun jeton lu ici
    <hôte>/<o>/<n>         la forge que `satellites.yml` déclare pour cet hôte
    <o>/<n>                la forge déclarée, si elle est seule ; sinon refus
    autre                  refus : « déclare ta forge dans satellites.yml (forges:) »

── Déclarer une forge Gitea — `satellites.yml`, clé `forges:` ──────────────

    forges:
      git.exemple.org:                   # l'hôte, tel que l'écrit `repo:`
        type: gitea                      # seul type connu aujourd'hui
        url: https://git.exemple.org     # la racine (l'API est sous /api/v1)
        jeton: GITEA_TOKEN               # le NOM de la clé dans MYSECRETS
        jeton_autonome: GITEA_TOKEN_AUTONOME   # facultatif : le compte des agents

`forges:` au pluriel, et une table par hôte : `forge:` (au singulier) existe
déjà dans ce fichier, une URL où cloner les satellites — deux sens sous une
clé, c'est une valeur que l'un des deux lecteurs prend de travers.

Le jeton est lu dans `<brain>/brain-secrets/MYSECRETS`, une clé à la fois,
comme du texte (le fichier n'est jamais exécuté). Il ne passe ni par argv, ni
par l'environnement, ni par une sortie : il ne vit que dans l'en-tête
`Authorization` de la requête.

── Le mode autonome (`BRAIN_FORGE_AUTONOME=1`, ou `autonome=True`) ──────────

    Gitea déclarée   le jeton de `jeton_autonome:` — jamais de repli sur celui
                     de l'humain : sans lui, refus
    GitHub           les PR s'ouvrent ; toute FUSION est refusée, et le refus
                     le dit — c'est l'humain qui fusionne

── Ce qui se traduit pour GitHub (et seulement pour les appels des outils) ──

    POST …/pulls/N/merge {"Do": m}    PUT …/pulls/N/merge {"merge_method": m}
    {"Do": "fast-forward-only"}       GitHub ne fusionne pas une PR en avance
                                      rapide : la base est AVANCÉE sur la tête de
                                      la PR (`PATCH git/refs/heads/<base>`,
                                      `force: false` — GitHub refuse, 422, ce qui
                                      n'est pas une avance rapide). La PR se voit
                                      alors fusionnée.
    limit=N                           per_page=N
    /issues?type=issues               GitHub rend aussi les PR : celles qui portent
                                      `pull_request` sont retirées. Retirer dans une
                                      page en fausserait la pagination (une page
                                      courte dit « fin ») : la liste est lue en
                                      entier une fois, puis servie par pages.
    compare/a...b                     identique (`total_commits`,
                                      `commits[].commit.message`)

Le code HTTP vient de `gh api --include` : sa première ligne (`HTTP/x 404 …`),
puis les en-têtes, une ligne vide, le corps — même quand `gh` sort en 1.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fiches import adresse  # noqa: E402 — l'adresse d'un dépôt, lue au même endroit que les fiches

GITHUB = "github.com"

#: Ce que l'outil rend quand GitHub dépasse ce qu'il lit en entier — jamais un
#: « rien » : la liste incomplète ferait croire à des issues « à créer ».
TROP = 507
PAGES_GITHUB = 30          # × 100 : au-delà, la liste n'est pas lue en entier


class ForgeRefus(Exception):
    """La forge ne se choisit pas, ou le mode le refuse — le message dit quoi faire."""


class ForgeInjoignable(Exception):
    """La forge ne répond pas (réseau, `gh` absent) : rien n'est mesuré."""


def autonome_par_defaut() -> bool:
    return os.environ.get("BRAIN_FORGE_AUTONOME") == "1"


# ── La déclaration : satellites.yml, forges: ───────────────────────────────

def declarees(brain: Path) -> dict[str, dict]:
    """`{hôte: déclaration}` — vide sans fichier ni clé. Illisible : refus nommé."""
    f = Path(brain) / "satellites.yml"
    if not f.is_file():
        return {}
    import yaml
    try:
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ForgeRefus(f"satellites.yml illisible ({type(exc).__name__}) — "
                         f"aucune forge ne se lit") from None
    forges = d.get("forges") if isinstance(d, dict) else None
    if forges is None:
        return {}
    if not isinstance(forges, dict) or not all(isinstance(v, dict) for v in forges.values()):
        raise ForgeRefus("satellites.yml : `forges:` attend une table par hôte "
                         "(`<hôte>: {type: gitea, url: …, jeton: <NOM>}`)")
    return {str(h).lower(): v for h, v in forges.items()}


def _cle_de_mysecrets(brain: Path, cle: str) -> str | None:
    """La valeur d'UNE clé de MYSECRETS, lue comme du texte — ou None. Jamais
    affichée, jamais mise dans l'environnement."""
    chemin = Path(brain) / "brain-secrets" / "MYSECRETS"
    try:
        lignes = chemin.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for ligne in lignes:
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", ligne)
        if m and m.group(1) == cle:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            return v or None
    return None


# ── Gitea ──────────────────────────────────────────────────────────────────

class Gitea:
    def __init__(self, brain: Path, hote: str, decl: dict, autonome: bool):
        if str(decl.get("type") or "gitea").lower() != "gitea":
            raise ForgeRefus(f"forge `{hote}` : type `{decl.get('type')}` inconnu — seul `gitea` se déclare")
        url = str(decl.get("url") or f"https://{hote}").rstrip("/")
        cle = decl.get("jeton_autonome") if autonome else decl.get("jeton")
        if not cle:
            raise ForgeRefus(
                f"forge `{hote}` : mode autonome sans `jeton_autonome:` déclaré — il ne se rabat "
                f"JAMAIS sur le jeton de l'humain" if autonome else
                f"forge `{hote}` : `jeton:` (le NOM de la clé dans MYSECRETS) n'est pas déclaré")
        self.hote, self.url, self.autonome = hote, url, autonome
        self._brain, self._cle = Path(brain), str(cle)
        if not self._jeton():
            raise ForgeRefus(
                f"`{self._cle}` absent de MYSECRETS — " +
                ("le mode autonome ne se rabat JAMAIS sur le jeton de l'humain ; "
                 if autonome else "") +
                "à poser par l'humain dans le fichier, jamais via le chat")

    def __repr__(self) -> str:
        return f"<forge gitea {self.hote}{' autonome' if self.autonome else ''}>"

    def _jeton(self) -> str | None:
        return _cle_de_mysecrets(self._brain, self._cle)

    def call(self, methode: str, chemin: str, corps=None):
        data = json.dumps(corps).encode() if corps is not None else None
        req = urllib.request.Request(f"{self.url}/api/v1{chemin}", data=data, method=methode)
        req.add_header("Authorization", f"token {self._jeton()}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"null")
            except ValueError:
                return e.code, None
        except (urllib.error.URLError, OSError) as e:
            raise ForgeInjoignable(f"forge {self.hote} injoignable : "
                                   f"{getattr(e, 'reason', type(e).__name__)}") from None


# ── GitHub, par gh ─────────────────────────────────────────────────────────

class GitHub:
    def __init__(self, autonome: bool):
        self.hote, self.autonome = GITHUB, autonome
        self._listes: dict[str, list] = {}

    def __repr__(self) -> str:
        return f"<forge github{' autonome' if self.autonome else ''}>"

    def _gh(self, methode: str, chemin: str, corps=None):
        argv = ["gh", "api", "--hostname", GITHUB, "--include", "-X", methode, chemin.lstrip("/")]
        if corps is not None:
            argv += ["--input", "-"]
        try:
            # Sans corps, l'entrée est VIDE — jamais celle de l'appelant : lancé
            # par un service ou un hook, c'est un tube que personne ne ferme.
            r = subprocess.run(argv, input=json.dumps(corps) if corps is not None else "",
                               capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            raise ForgeInjoignable("`gh` introuvable — GitHub se parle par `gh` (et son `gh auth login`)") from None
        except subprocess.TimeoutExpired:
            raise ForgeInjoignable("`gh api` : délai dépassé") from None
        return _reponse_gh(r.stdout, r.stderr)

    def _refus_autonome(self, n) -> tuple[int, dict]:
        return 403, {"message": f"mode autonome sur GitHub : la fusion de la PR #{n} est refusée — "
                                "elle reste ouverte, c'est l'humain qui fusionne",
                     "refus_autonome": True}

    def call(self, methode: str, chemin: str, corps=None):
        methode = methode.upper()
        base, _, requete = chemin.partition("?")
        q = urllib.parse.parse_qs(requete, keep_blank_values=True)
        m = re.fullmatch(r"(/repos/[^/]+/[^/]+)/pulls/(\d+)/merge", base)
        if m and methode in ("POST", "PUT"):
            if self.autonome:
                return self._refus_autonome(m.group(2))
            style = (corps or {}).get("Do") or (corps or {}).get("merge_method") or "merge"
            if style == "fast-forward-only":
                return self._avance_rapide(m.group(1), m.group(2))
            if style not in ("merge", "squash", "rebase"):
                return 422, {"message": f"style de fusion `{style}` inconnu de GitHub"}
            return self._gh("PUT", base, {"merge_method": style})
        if q.get("limit"):
            q["per_page"] = q.pop("limit")
        if re.fullmatch(r"/repos/[^/]+/[^/]+/issues", base) and methode == "GET" \
                and q.get("type") == ["issues"]:
            q.pop("type")
            return self._page_d_issues(base, q)
        q.pop("type", None)
        chemin = base + (f"?{urllib.parse.urlencode(q, doseq=True)}" if q else "")
        return self._gh(methode, chemin, corps)

    def _avance_rapide(self, depot: str, n: str):
        """La base de la PR avance sur sa tête, sans commit de fusion — ou rien ne bouge."""
        code, pr = self._gh("GET", f"{depot}/pulls/{n}")
        if code != 200 or not isinstance(pr, dict):
            return code, pr
        base, tete = (pr.get("base") or {}).get("ref"), (pr.get("head") or {}).get("sha")
        if not base or not tete:
            return 422, {"message": f"PR #{n} : base ou tête illisible"}
        return self._gh("PATCH", f"{depot}/git/refs/heads/{base}", {"sha": tete, "force": False})

    def _page_d_issues(self, base: str, q: dict):
        """Une page d'ISSUES seules : la liste entière lue une fois, PR retirées."""
        par_page = int((q.pop("per_page", None) or ["30"])[0])
        page = int((q.pop("page", None) or ["1"])[0])
        filtre = sorted(q.items())
        cle = base + "?" + urllib.parse.urlencode(filtre, doseq=True)
        if cle not in self._listes:
            tout = []
            for p in range(1, PAGES_GITHUB + 1):
                params = urllib.parse.urlencode(filtre + [("per_page", "100"), ("page", str(p))],
                                                doseq=True)
                code, d = self._gh("GET", f"{base}?{params}")
                if code >= 300:
                    return code, d
                if not isinstance(d, list):
                    return 502, {"message": "GitHub ne rend pas une liste d'issues"}
                tout += [x for x in d if "pull_request" not in x]
                if len(d) < 100:
                    break
            else:
                return TROP, {"message": f"plus de {PAGES_GITHUB * 100} éléments sur {base} : "
                                         f"la liste n'est pas lue en entier"}
            self._listes[cle] = tout
        tout = self._listes[cle]
        return 200, tout[(page - 1) * par_page: page * par_page]


def _reponse_gh(sortie: str, erreur: str) -> tuple[int, object]:
    """`(code, json)` d'une sortie de `gh api --include`."""
    texte = sortie.replace("\r\n", "\n")
    m = re.match(r"HTTP/\S+ (\d{3})", texte)
    if not m:
        m2 = re.search(r"\(HTTP (\d{3})\)", erreur or "")
        if not m2:
            raise ForgeInjoignable(f"`gh api` sans réponse HTTP : {(erreur or '').strip()[:200]}")
        return int(m2.group(1)), None
    _, _, corps = texte.partition("\n\n")
    try:
        return int(m.group(1)), json.loads(corps) if corps.strip() else None
    except ValueError:
        return int(m.group(1)), None


# ── Le choix ───────────────────────────────────────────────────────────────

def pour(depot: str, brain: Path | None = None, autonome: bool | None = None):
    """La forge du dépôt `depot` (`<hôte>/<owner>/<nom>`, ou `<owner>/<nom>`).

    `ForgeRefus` si elle ne se choisit pas ; le message dit quoi déclarer."""
    autonome = autonome_par_defaut() if autonome is None else bool(autonome)
    a = adresse(depot)
    if a is None:
        raise ForgeRefus(f"`{depot}` ne désigne pas un dépôt (<hôte>/<owner>/<nom>)")
    hote, _ = a
    if hote == GITHUB:
        return GitHub(autonome)
    forges = declarees(brain) if brain else {}
    if hote is None:
        if len(forges) != 1:
            raise ForgeRefus(
                f"`{depot}` ne dit pas son hôte, et satellites.yml déclare "
                f"{len(forges)} forge(s) — écris `<hôte>/{a[1]}`, ou déclare ta forge "
                f"dans satellites.yml (forges:)")
        hote = next(iter(forges))
    if hote not in forges:
        raise ForgeRefus(f"forge `{hote}` inconnue — déclare ta forge dans satellites.yml "
                         f"(forges: {hote}: {{type: gitea, url: …, jeton: <NOM>}})")
    return Gitea(Path(brain), hote, forges[hote], autonome)
