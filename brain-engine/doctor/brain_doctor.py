#!/usr/bin/env python3
"""`brain doctor` — rendre la dérive visible

Le mode de défaillance a un nom : **démyélinisation**. Le programme est édité
hors de son overlay, rien ne casse, tout dégrade. Un registre s'éloigne de sa
source, un cache sert des données de mars, un champ garde la valeur d'une
décision annulée — et personne ne le voit, parce qu'aucune de ces choses ne
lève une erreur.

Précédent : le template avait cinq mois de retard et rien ne le disait.

Chaque contrôle répond à une seule question — **qu'est-ce qui pourrirait en
silence sans lui ?** Le verdict n'est pas « test passé », c'est « cette dérive-là
est sous surveillance, ou elle ne l'est pas ».

    python3 tools/brain_doctor.py --brain ~/Dev/Brain
    python3 tools/brain_doctor.py --brain ~/Dev/Brain --complet   # + briques (lent)

Sortie 1 si un contrôle échoue. Un contrôle qui **ne peut pas** s'exercer —
Ollama absent, jeton manquant, backend sqlite — s'abstient et le dit : un vert
qui ne mesure rien est pire qu'un rouge.

## Le contrat d'un contrôle — ce que le doctor attend de lui

    code de sortie   0 vert · non-nul rouge. C'est LUI qui fait le verdict,
                     rien d'autre.
    `SKIP…`          une ligne commençant par SKIP, avec une sortie 0 : le
                     contrôle s'abstient, et cette ligne est son résumé.
    `VERDICT: …`      **la ligne que le doctor affichera** — à préférer, parce que
                     sans elle il la devine, et il peut se tromper.

Un contrôle qui ne déclare pas son `VERDICT:` reste valide : le doctor se rabat
sur son heuristique d'origine, et le pied de page compte combien sont dans ce
cas. `--temoin` éprouve les deux chemins.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
OUTILS = Path(__file__).resolve().parent

#: Un controle declare sa ligne de verdict au lieu de la laisser deviner
#: Le doctor la prefere a toute heuristique. Absent, il se rabat exactement sur
#: le comportement d avant, et c est temoigne.
MARQUEUR = "VERDICT:"


def resumer(lignes: list[str], echec: bool) -> tuple[str, str]:
    """La ligne qui resume un controle, et d ou elle vient.

    Retourne `(resume, origine)` — origine `declare` ou `devine`.

    **Pourquoi ce n est plus une heuristique seule**. Le doctor
    choisissait le dernier `✅` au vert, et au rouge la premiere famille de
    marqueurs trouvee. Deux fois ca lui a fait afficher autre chose que le
    verdict :

    - au **vert**, tout controle porte une auto-epreuve dont chaque cas imprime
      un `✅` : le dernier est donc un NOM DE TEST, sauf si l auteur pense a
      reimprimer son verdict apres. Trois rustines manuelles en un jour.
    - au **rouge**, un controle qui n imprime aucun marqueur tombe sur
      `or lignes` et se resume par sa DERNIERE ligne, quelle qu elle soit.
      Trouve le 26/09 sur `backlog_issues.py --check` : il annonçait
      « Rien n'a ete ecrit. `--apply` pour deriver vraiment » — un mode d emploi
      — alors que la derive reelle etait 20 items ouverts sans issue sur la
      forge. La fiche avait classe ce cas « indeterminable » et s en
      etait tenue la ; c etait le seul endroit ou le defaut vivait encore.

    Le marqueur ne decide **que du resume**. Le verdict reste celui du code de
    sortie : un outil qui declare « tout va bien » et sort en 1 reste rouge.

    ⚠️ **Le dernier marqueur gagne, et c est un risque assume.** Trois controles
    lancent d autres outils en sous-processus (`test_controles_rougissent`,
    `test_interruption_controles`, `test_concurrence_controles`). Verifie le
    26/09 : aucun ne reemet la sortie capturee, il n y a donc pas de
    contamination aujourd hui. Mais celui qui le ferait verrait le `VERDICT:` de
    l outil lance devenir le sien. Un controle qui relaie la sortie d un autre
    doit la filtrer, ou declarer son propre verdict APRES.
    """
    declares = [l for l in lignes if l.startswith(MARQUEUR)]
    if declares:
        return declares[-1][len(MARQUEUR):].strip(), "declare"

    if not echec:
        candidates = [l for l in lignes if "✅" in l] or lignes
    else:
        # En echec, on veut la ligne qui dit POURQUOI, pas la derniere venue.
        candidates = ([l for l in lignes if "❌" in l]
                      or [l for l in lignes if l.startswith(("FAILED", "ERROR", "FAIL"))]
                      or [l for l in lignes if "⚠️" in l]
                      or lignes)
    return (candidates[-1] if candidates else ""), "devine"


_LIGNE_DE_SECRET = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def cle_de_mysecrets(brain: Path, cle: str) -> str | None:
    """La valeur d'UNE clé de MYSECRETS, lue comme du texte — ou None.

    Le fichier n'est jamais exécuté (`source` exécute chaque ligne : une valeur
    en `$(…)` tournerait, et ses lignes s'afficheraient). On lit `CLE=valeur`,
    `export` et guillemets tolérés, et on ne rend que la clé demandée. La valeur
    ne s'affiche nulle part : elle passe dans l'environnement du seul contrôle
    qui en a besoin. Tranché par l'owner le 30/09.
    """
    chemin = brain / "brain-secrets" / "MYSECRETS"
    try:
        lignes = chemin.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for ligne in lignes:
        # Un commentaire ne correspond jamais : le motif exige un nom de clé en
        # tête de ligne (un `#` n'en est pas un).
        m = _LIGNE_DE_SECRET.match(ligne)
        if m and m.group(1) == cle:
            v = m.group(2)
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            return v or None
    return None


#: Les contrôles qui jugent CETTE instance — son backlog, son wiki, sa forge, ses
#: machines, ses outils propres. Ils ne partent pas avec le doctor du gabarit, et
#: `--portee gabarit` ne les joue pas. Tranché par l'owner le 2/10 : la portée
#: de chaque contrôle est décidée, pas devinée.
INSTANCE = frozenset({
    "registre des projets", "statuts de projet", "les chiffres de la doc",
    "le replica est alignable", "index du backlog", "index des décisions",
    "issues dérivées du backlog", "ancre du programme", "marqueurs distribuables",
    "doc du gabarit", "le wiki dit vrai", "les pages d'instance disent vrai",
    "rapports de clôture", "discipline d'écriture Dolt", "Dolt vs disque",
    "les jetons du moteur en service", "les satellites à jour", "fondation du CORE",
    "chaque session a son claim",
})


class Controle:
    """Un contrôle, et la dérive qu'il empêche de passer inaperçue."""

    def __init__(self, nom: str, protege: str, commande: list[str],
                 *, cwd: Path | None = None, lent: bool = False,
                 env_extra: dict[str, str] | None = None):
        self.nom, self.protege, self.commande = nom, protege, commande
        self.instance = nom in INSTANCE
        self.cwd, self.lent = cwd, lent
        #: Ajouté à l'environnement de CE contrôle seulement — jamais affiché.
        self.env_extra = env_extra or {}
        #: D ou vient le resume du dernier passage : `declare`, `devine`, ou ""
        #: quand le controle s est abstenu ou n a pas tourne. Lu par le pied de
        #: page pour rendre la migration mesurable au lieu de supposee.
        self.origine = ""

    def jouer(self) -> tuple[str, str, float]:
        """(verdict, résumé, durée). Verdict : vert · rouge · abstenu.

        **Un rouge est rejoué une fois avant d'être déclaré.** Mesuré les 06 et
        07/09 : trois rouges en deux jours ont disparu à la relecture, tous
        causés par une mesure prise pendant une écriture — le hook `post-commit`
        dérive les registres de façon asynchrone, `embed.py` réindexe en cron.

        Un état transitoire disparaît au second passage ; une vraie dérive
        persiste. C'est la seule chose qui les distingue de l'extérieur.

        ⚠️ **Ça ne masque rien** : un contrôle qui passe à la seconde tentative
        est marqué « instable » et le dit. Cacher une dérive intermittente serait
        pire que le fantôme — mais un rouge qu'on apprend à ignorer ne protège
        plus rien non plus, et trois en deux jours suffisent à l'apprendre.
        """
        verdict, resume, duree = self._une_fois()
        if verdict != "rouge":
            return verdict, resume, duree
        verdict2, resume2, duree2 = self._une_fois()
        if verdict2 == "rouge":
            return verdict2, resume2, duree + duree2
        return verdict2, f"instable — rouge puis {verdict2} : {resume[:60]}", duree + duree2

    def _une_fois(self) -> tuple[str, str, float]:
        debut = time.perf_counter()
        try:
            r = subprocess.run(self.commande, capture_output=True, text=True,
                               cwd=self.cwd, timeout=900,
                               env={**os.environ, **self.env_extra} if self.env_extra else None)
        except FileNotFoundError as exc:
            return "abstenu", f"outil introuvable : {exc.filename}", 0.0
        except subprocess.TimeoutExpired:
            return "rouge", "délai dépassé (900 s)", time.perf_counter() - debut
        duree = time.perf_counter() - debut

        sortie = _ANSI.sub("", (r.stdout or "") + (r.stderr or ""))
        lignes = [l.strip() for l in sortie.splitlines() if l.strip()]

        # L'abstention doit etre DECLAREE, en debut de ligne, et sur une sortie
        # nulle. Un simple `"SKIP" in sortie` classait la suite de tests comme
        # abstenue parce qu'un de ses cas s'appelle `HELLOWORLD_SKIP` — et
        # masquait donc un echec reel. Un detecteur de derive qui cache un rouge
        # est pire que pas de detecteur.
        declaree = next((l for l in lignes if l.startswith("SKIP")), None)
        if declaree and r.returncode == 0:
            return "abstenu", declaree[:96], duree

        resume, self.origine = resumer(lignes, r.returncode != 0)
        for signe in ("✅", "❌", "⚠️"):
            resume = resume.replace(signe, "")
        return ("vert" if r.returncode == 0 else "rouge"), resume.strip()[:96], duree


def sante_du_service(brain: Path) -> Controle:
    """Les routes vitales répondent-elles ? Le seul contrôle qui exerce le brain vivant."""
    script = OUTILS / "_routes_vitales.py"
    return Controle("routes vitales",
                    "une route qui tombe sans que rien ne le dise",
                    [sys.executable, str(script), "--brain", str(brain)])


def controles(brain: Path, complet: bool) -> list[Controle]:
    moteur = brain / "brain-engine"
    liste = [
        Controle("manifests de session",
                 "une clé hors contrat, invisible parce qu'aucun code ne les parse",
                 [sys.executable, str(OUTILS / "session_manifests.py"),
                  "--brain", str(brain), "--check"]),
        Controle("registre des agents",
                 "CATALOG.yml et le frontmatter qui s'éloignent",
                 [sys.executable, str(OUTILS / "agent_registry.py"),
                  "--brain", str(brain), "--check"]),
        Controle("registre des projets",
                 "les fiches et la table Dolt qui divergent",
                 [sys.executable, str(OUTILS / "project_registry.py"),
                  "--brain", str(brain), "--check"]),
        # Le slug est la clé (l'owner, 29/09) : fiche, dossier de liste, préfixe,
        # palier et dépôt tiennent ensemble — ou le défaut est nommé.
        Controle("la zone projet",
                 "un dossier de liste sans projet, deux listes au même préfixe",
                 [sys.executable, str(OUTILS / "zone_projet.py"),
                  "--brain", str(brain)]),
        Controle("statuts de projet",
                 "un champ d'état qui redevient un journal",
                 [sys.executable, str(OUTILS / "normalize_status.py"), "--brain", str(brain)]),
        Controle("index vs corpus",
                 "le RAG qui sert ce que le corpus a laissé tomber",
                 [sys.executable, str(OUTILS / "index_purge.py"), "--brain", str(brain),
                  "--check"]),
        Controle("témoin du corpus",
                 "un signal de fraîcheur qui ne discrimine plus",
                 [sys.executable, str(OUTILS / "test_index_corpus.py"),
                  "--brain", str(brain)]),
        Controle("le RAG retrouve",
                 "une recherche qui ne rend plus ce qu'elle a indexé",
                 [sys.executable, str(OUTILS / "test_rag_retrouve.py"),
                  "--brain", str(brain)]),
        Controle("cache de matrice",
                 "un cache qui ne voit pas les suppressions",
                 [sys.executable, str(OUTILS / "test_cache_matrice.py"),
                  "--brain", str(brain)]),
        Controle("cohérence du claim BSI",
                 "un agent qui décrit un mécanisme aboli",
                 [sys.executable, str(OUTILS / "bsi_coherence.py"), "--brain", str(brain)]),
        Controle("contextes de session",
                 "un boot qui charge moins que ce qu'il annonce, sans le dire",
                 [sys.executable, str(OUTILS / "contextes_de_session.py"),
                  "--brain", str(brain)]),
        Controle("niveaux déclarés",
                 "une chose qui apparaît sans se déclarer",
                 [sys.executable, str(OUTILS / "niveaux.py"),
                  "--brain", str(brain), "--check"]),
        # Un brain migré lit ses agents par une vue que git ignore : ce qui s'y
        # écrit à côté des liens est lu partout et commité nulle part.
        Controle("la vue des agents",
                 "un agent écrit dans la vue, que git ne voit pas",
                 [sys.executable, str(OUTILS / "vue_juste.py"), "--brain", str(brain)]),
        # Un cycle d'unités ne lève aucune erreur : systemd supprime une unité au
        # boot. Dolt ne démarrait plus chez l'owner le 3/10, après un fork.
        Controle("les unités sans cycle",
                 "une unité que le boot supprime en silence",
                 [sys.executable, str(OUTILS / "unites_sans_cycle.py"), "--brain", str(brain)]),
        Controle("compteurs hors vecteurs",
                 "un compteur logé dans la table la plus lourde du schéma",
                 [sys.executable, str(OUTILS / "hits_hors_table.py"),
                  "--brain", str(brain)]),
        Controle("convention de commit",
                 "une règle chargée à chaque boot que rien ne vérifie",
                 [sys.executable, str(OUTILS / "convention_commits.py"),
                  "--brain", str(brain)]),
        Controle("état du BSI",
                 "un mécanisme qui ferme les sessions vivantes comme des oublis",
                 [sys.executable, str(OUTILS / "bsi_etat.py"),
                  "--brain", str(brain)]),
        Controle("registres en base",
                 "un registre qui vit dans une base que rien ne sauvegarde",
                 [sys.executable, str(OUTILS / "registres_en_base.py"),
                  "--brain", str(brain)]),
        Controle("registre des secrets",
                 "un registre de secrets qui derive vers la fiction",
                 [sys.executable, str(OUTILS / "registre_des_secrets.py"),
                  "--brain", str(brain)]),
        Controle("contrat des capacites",
                 "une porte qui s'ouvre ou se ferme sans que le contrat le dise",
                 [sys.executable, str(OUTILS / "parite_capacites.py"),
                  "--brain", str(brain)]),
        # Les deux outils nes le 10/09 tournaient a la main, donc quand on y
        # pensait. Un controle que rien n'appelle ne controle rien — c'est
        # exactement le reproche fait ce jour-la au « slot garanti » et aux deux
        # registres de secrets. Ils entrent ici.
        Controle("le contrat des capacites refuse",
                 "un contrat qui a cesse de savoir dire non",
                 [sys.executable, str(OUTILS / "test_parite_capacites.py")]),
        Controle("la porte MCP repond",
                 "un outil qui se charge et ne rend rien",
                 [sys.executable, str(OUTILS / "eprouver_porte_mcp.py"),
                  "--brain", str(brain)]),
        Controle("la porte HTTP repond",
                 "une route qui ne se verifie qu'en la mettant en service",
                 [sys.executable, str(OUTILS / "eprouver_porte_http.py"),
                  "--brain", str(brain)]),
        Controle("les deux chemins d'un outil",
                 "un repli qui montre un autre monde que la source",
                 [sys.executable, str(OUTILS / "deux_chemins_meme_monde.py"),
                  "--brain", str(brain)]),
        Controle("le socle du boot",
                 "un boot qui charge un fichier disparu sans se plaindre",
                 [sys.executable, str(OUTILS / "socle_du_boot.py"),
                  "--brain", str(brain)]),
        Controle("la file de reindexation tient",
                 "une reindexation qui n'a jamais lieu",
                 [sys.executable, str(OUTILS / "eprouver_file_reindex.py"),
                  "--brain", str(brain)]),
        Controle("la porte BSI passe par le moteur",
                 "un repli qui reussit sans le dire",
                 [sys.executable, str(OUTILS / "eprouver_porte_bsi_claim.py"),
                  "--brain", str(brain)]),
        Controle("sentinelle jamais envoyee",
                 "une branche d erreur qui ne s executera jamais",
                 [sys.executable, str(OUTILS / "sentinelle_jamais_envoyee.py"),
                  "--brain", str(brain)]),
        Controle("peer muet n est pas peer vide",
                 "une machine eteinte qui ressemble a une machine au repos",
                 [sys.executable, str(OUTILS / "peer_muet_nest_pas_peer_vide.py"),
                  "--brain", str(brain)]),
        Controle("le lock dit les peers muets",
                 "un mutex distribue qui se croit global sans avoir joint personne",
                 [sys.executable, str(OUTILS / "lock_dit_les_peers_muets.py"),
                  "--brain", str(brain)]),
        Controle("close-stale ferme sa liste",
                 "une commande qui liste selon un critere et ferme selon un autre",
                 [sys.executable, str(OUTILS / "close_stale_ferme_sa_liste.py"),
                  "--brain", str(brain)]),
        Controle("l etat annonce vs la forge",
                 "un document d etat qui reclame un travail deja fusionne",
                 [sys.executable, str(OUTILS / "annonce_vs_forge.py"),
                  "--brain", str(brain)]),
        Controle("le BSI d avant BRAIN-042",
                 "un agent qui ordonne un geste sur des claims/*.yml disparus depuis mars",
                 [sys.executable, str(OUTILS / "bsi_d_avant_042.py"),
                  "--brain", str(brain)]),
        Controle("l archivage a tourne",
                 "un archivage qui echoue chaque dimanche dans un journal que personne ne lit",
                 [sys.executable, str(OUTILS / "archivage_a_tourne.py"),
                  "--brain", str(brain)]),
        Controle("l instantane a tourne",
                 "un instantane Dolt refuse a chaque passage dans un journal que personne ne lit",
                 [sys.executable, str(OUTILS / "instantane_a_tourne.py"),
                  "--brain", str(brain)]),
        Controle("les chiffres de la doc",
                 "un chiffre ecrit dans une doc que le commit suivant a rendu faux",
                 [sys.executable, str(OUTILS / "chiffres_de_la_doc.py"),
                  "--brain", str(brain)]),
        Controle("la fraicheur des fiches",
                 "une fiche qu on croit tenue parce qu elle a l air recente",
                 [sys.executable, str(OUTILS / "fraicheur_des_fiches.py"),
                  "--brain", str(brain)]),
        # « le front rotatif est actif » retiré le 4/10 : le boot ne sert plus de
        # front — la table `intentions` est retirée, « en cours » se calcule des
        # PR fusionnées (`brain-engine/fiches_en_cours.py`).
        Controle("statuts conformes a l enum",
                 "une fiche que la base refusera d ecrire, et qu on decouvre en ecrivant",
                 [sys.executable, str(OUTILS / "statuts_conformes.py"),
                  "--brain", str(brain)]),
        # Deux fiches pour un même projet : une copie renommée, une faute de
        # frappe devenue une seconde fiche. Né dans le générateur du menu d'une
        # instance, qui le portait seul : il mesure le brain.
        Controle("pas de doublon de projet",
                 "un projet ecrit a deux endroits, dont la moitie des decisions va dans la mauvaise",
                 [sys.executable, str(OUTILS / "doublons_de_projets.py"),
                  "--brain", str(brain)]),
        Controle("le replica est alignable",
                 "un replica qui a cesse de suivre son master, et que personne ne voit decrocher",
                 [sys.executable, str(OUTILS / "replica_alignable.py"),
                  "--brain", str(brain)]),
        Controle("routes sous garde",
                 "une porte d'ecriture qui ignore le mode de l'instance",
                 [sys.executable, str(OUTILS / "routes_sous_garde.py"),
                  "--brain", str(brain)]),
        Controle("les gardes d'ecriture refusent",
                 "une zone protegee sur le papier et ouverte en pratique",
                 [sys.executable, str(OUTILS / "eprouver_gardes_ecriture.py"),
                  "--brain", str(brain)]),
        Controle("le garde de zone du hook refuse",
                 "le garde des ecritures DURABLES, eteint sans que personne le voie",
                 [sys.executable, str(OUTILS / "eprouver_garde_zone_hook.py"),
                  "--brain", str(brain)]),
        Controle("le CORE tient debout seul",
                 "un CORE qui reprend une dependance au moteur qu'il remplace",
                 [sys.executable, str(OUTILS / "core_isole.py")]),
        Controle("le CORE est atteignable",
                 "une dependance qui tient a une installation, et se perd sans bruit",
                 [sys.executable, str(OUTILS / "core_atteignable.py"),
                  "--brain", str(brain)]),
        Controle("frontmatter valide",
                 "une metadonnee perdue par une porte et lue par l'autre",
                 [sys.executable, str(OUTILS / "frontmatter_valide.py"),
                  "--brain", str(brain)]),
        Controle("les branchements du CORE tiennent",
                 "une porte qui repasse a une implementation locale",
                 [sys.executable, str(OUTILS / "branchements_du_core.py"),
                  "--brain", str(brain)]),
        Controle("les deux chemins de recherche",
                 "un repli sans numpy qui ne classe pas comme le chemin nominal",
                 [sys.executable, str(OUTILS / "equivalence_recherche.py"),
                  "--brain", str(brain)]),
        Controle("sauvegarde restaurable",
                 "une sauvegarde qu'on n'a jamais rechargée",
                 [sys.executable, str(OUTILS / "sauvegarde_restaurable.py"),
                  "--brain", str(brain)]),
        Controle("les contrôles interrompus",
                 "un garde-fou qui laisse une trace quand on le tue",
                 [sys.executable, str(OUTILS / "test_interruption_controles.py"),
                  "--brain", str(brain)], lent=True),
        Controle("les contrôles sous concurrence",
                 "un garde-fou qui accuse quand on le lance deux fois",
                 [sys.executable, str(OUTILS / "test_concurrence_controles.py"),
                  "--brain", str(brain)], lent=True),
        Controle("les contrôles refusent",
                 "un garde-fou qui a cessé de savoir dire non",
                 [sys.executable, str(OUTILS / "test_controles_rougissent.py"),
                  "--brain", str(brain)]),
        # Le temoin du doctor gardait le verdict des 66 autres controles — et
        # rien ne le lançait. Trouve le 26/09 en cherchant qui exerçait `--temoin`
        # : personne. Un garde-fou qu on doit penser a invoquer n en est pas un,
        # c est la lecon que ce depot repete. `--temoin` ne joue aucun controle,
        # il fabrique de faux outils : pas de recursion.
        Controle("le verdict du doctor",
                 "l instrument qui juge les 66 autres, et que personne n exerce",
                 [sys.executable, str(OUTILS / "brain_doctor.py"), "--temoin"]),
        Controle("le template debout",
                 "un fork qui reçoit du code sans ce dont il dépend",
                 [sys.executable, str(OUTILS / "template_autonome.py"),
                  "--brain", str(brain)]),
        Controle("dérive du lock",
                 "un noyau dont l'empreinte décrit un état révolu",
                 [sys.executable, str(OUTILS / "derive_du_lock.py"),
                  "--brain", str(brain)]),
        Controle("hooks git installés",
                 "un hook écrit à la main, absent ailleurs, ou un garde qui ne voit pas la base",
                 [sys.executable, str(OUTILS / "hooks_installes.py"), "--brain", str(brain)]),
        Controle("garde de lecture",
                 "un sous-agent qui lit le personnel sans que rien ne l'arrête — ou un Claude Code plus récent que la dernière épreuve du garde",
                 [sys.executable, str(OUTILS / "garde_de_lecture.py"), "--brain", str(brain)]),
        Controle("index du backlog",
                 "un index écrit à la main, qui ne dit plus ce que les fiches disent",
                 [sys.executable, str(OUTILS / "index_backlog.py"),
                  "--brain", str(brain), "--tous", "--check"]),
        Controle("index des décisions",
                 "un index d'ADR écrit à la main, arrêté à 052 quand le répertoire allait à 079",
                 [sys.executable, str(OUTILS / "index_decisions.py"),
                  "--brain", str(brain), "--check"]),
        Controle("issues dérivées du backlog",
                 "un dérivé qui s'éloigne de sa source, encore",
                 [sys.executable, str(OUTILS / "backlog_issues.py"),
                  "--brain", str(brain), "--tous", "--check"]),
        Controle("ancre du programme",
                 "une version déclarée qui ne désigne aucun état",
                 [sys.executable, str(OUTILS / "overlay.py"),
                  "--brain", str(brain), "--check"]),
        Controle("versions du kernel",
                 "un numero de version que chaque copie dit differemment",
                 [sys.executable, str(OUTILS / "versions_du_kernel.py"),
                  "--brain", str(brain)]),
        Controle("schéma vs base",
                 "une colonne déclarée qui n'atteint jamais la base",
                 [sys.executable, str(OUTILS / "schema_vs_base.py"),
                  "--brain", str(brain)]),
        Controle("schéma versionné",
                 "une base dont la structure n'existe que sur cette machine",
                 ["bash", str(brain / "scripts" / "dolt-schema-gen.sh"), "--check"]),
        Controle("règle des zones",
                 "deux déclarations de la même règle, qui divergeront",
                 [sys.executable, str(OUTILS / "regle_des_zones.py"),
                  "--brain", str(brain)]),
        Controle("schéma du repli",
                 "un fork qui reçoit un moteur amputé de la moitié de ses tables",
                 [sys.executable, str(brain / "scripts" / "schema-sqlite-gen.py"),
                  "--check"]),
        Controle("niveaux vs scopes",
                 "une donnée non distribuable servie au rôle le moins privilégié",
                 [sys.executable, str(OUTILS / "niveaux_vs_scopes.py"),
                  "--brain", str(brain)]),
        Controle("niveaux vs corpus",
                 "un invariant que le brain ne peut pas se relire",
                 [sys.executable, str(OUTILS / "niveaux_vs_corpus.py"),
                  "--brain", str(brain)]),
        Controle("niveaux vs git",
                 "une donnée dont personne ne sait si le dépôt la garde",
                 [sys.executable, str(OUTILS / "niveaux_vs_git.py"),
                  "--brain", str(brain)]),
        Controle("liens morts",
                 "un chemin cité qui ne mène plus nulle part, sans erreur",
                 [sys.executable, str(OUTILS / "liens_morts.py"),
                  "--brain", str(brain)]),
        Controle("marqueurs distribuables",
                 "un chemin ou un domaine de cette instance, chez les autres",
                 [sys.executable, str(OUTILS / "marqueurs_distribuables.py"),
                  "--brain", str(brain)]),
        Controle("doc du gabarit",
                 "une doc qui décrit un produit qui n'existe plus",
                 [sys.executable, str(OUTILS / "doc_du_gabarit.py"),
                  "--brain", str(brain)]),
        # Le wiki ne part pas avec le gabarit : rien ne le jugeait. Le 29/09,
        # 270 affirmations fausses sur 35 pages, et une procédure qui écrasait
        # `~/.claude/settings.json`.
        Controle("le wiki dit vrai",
                 "un wiki qui décrit un système disparu",
                 [sys.executable, str(OUTILS / "wiki_juste.py"),
                  "--brain", str(brain)]),
        # Les pages d'instance de la skill disent aux sessions comment on
        # travaille ici. Le 29/09 elles avaient dérivé : `docs-verite` savait
        # les juger, rien ne le lançait.
        Controle("les pages d'instance disent vrai",
                 "une page qui dit comment on travaille ici, sur une machine disparue",
                 [sys.executable, str(OUTILS / "skill_instance_juste.py"),
                  "--brain", str(brain)]),
        Controle("rattachement des scripts",
                 "un script que plus rien n'appelle, et que personne n'assume",
                 [sys.executable, str(OUTILS / "rattachement_scripts.py"),
                  "--brain", str(brain)]),
        Controle("rapports de clôture",
                 "un item soldé sans dire ce qu'il a mesuré ni ce qui le tient",
                 [sys.executable, str(OUTILS / "cloture_backlog.py"),
                  "--brain", str(brain), "--tous"]),
        Controle("conventions temporelles",
                 "une horloge locale qui rentre par le schéma",
                 [sys.executable, str(OUTILS / "test_conventions_temporelles.py"),
                  "--brain", str(brain)]),
        Controle("discipline d'écriture Dolt",
                 "un commit qui emporte ce qu'il ne décrit pas",
                 [sys.executable, str(OUTILS / "test_dolt_discipline.py"), "--brain", str(brain)]),
        Controle("Dolt vs disque",
                 "un registre qui s'éloigne du système de fichiers",
                 ["bash", str(brain / "scripts" / "brain-validate.sh")]),
        # `brain-validate` compare agents, projets et décisions — pas les
        # handoffs. Et `--check` existait sans que rien ne l'appelle, en datant
        # un journal au lieu de mesurer la base : un `pull` divergent laissait un
        # handoff hors de la base sans que personne le voie.
        # Un service déclaré pour charger MYSECRETS qui n'en a rien reçu s'ouvre
        # en grand sans le dire (`check_auth` sans jeton = accès complet).
        # Les NOMS des variables du processus, jamais leurs valeurs.
        Controle("les jetons du moteur en service",
                 "un moteur qui charge MYSECRETS sans en avoir reçu les jetons — ouvert sans le dire",
                 [sys.executable, str(OUTILS / "jetons_en_service.py"), "--brain", str(brain)]),
        Controle("la base suit les handoffs",
                 "un handoff sur le disque que la base n'a jamais reçu",
                 ["bash", str(brain / "scripts" / "brain-db-sync.sh"), "--check"]),
        # `handoffs/` est pour une AUTRE session ; rien ne disait qu'un handoff
        # avait été repris : le 2/10, 43 sur 45 étaient `active`. Seuil tranché
        # le 2/10 : 14 jours. Les candidats de `scratch/` sont affichés, pas
        # jugés (tranché le même jour).
        # Le modèle de la zone projet, appliqué aux tracks : la fiche d'une track
        # est son index et ses liens ; `feeds:` ne nomme que ce qui existe ; la
        # table de learning/README.md est générée. Mesuré le 2/10 : 5 cibles
        # réelles sur 15, une table qui contredisait les fiches.
        Controle("la zone learning",
                 "une track qui nourrit un projet qui n'existe pas, une table écrite à la main",
                 [sys.executable, str(OUTILS / "zone_learning.py"), "--brain", str(brain)]),
        Controle("les handoffs disent s'ils sont attendus",
                 "un handoff actif que plus personne ne reprendra, ou sans statut",
                 [sys.executable, str(OUTILS / "handoffs_vivants.py"), "--brain", str(brain)]),
        # « Ouvrir le claim avant toute réponse de travail » est la loi du boot, et
        # rien ne la vérifiait : `bsi_coherence` contrôle que le TEXTE la nomme. Ici,
        # les sessions Claude Code vivantes du brain contre les claims ouverts.
        Controle("chaque session a son claim",
                 "une session qui travaille sans claim — invisible aux sessions parallèles",
                 [sys.executable, str(brain / "scripts" / "claims-orphelins.py"), "--sans-claim"]),
        # `helloWorld` présentait `profil/session-types.md`, déprécié depuis le
        # 20/03, comme une source : aucun lien n'était mort, le fichier existe.
        Controle("les renvois du noyau",
                 "un agent du noyau qui envoie la session lire un fichier déprécié",
                 [sys.executable, str(OUTILS / "renvois_deprecies.py"), "--brain", str(brain)]),
        # Rien ne tenait les satellites à jour hors de l'installation : le
        # laptop a booté avec un `profil/` en retard de 30 commits. Ici, sur le
        # fixe, le danger est l'inverse — un satellite DEVANT son amont, des
        # commits que l'autre machine ne verra jamais. Lecture seule
        # (`ls-remote`) ; forge injoignable → abstention.
        # Le TTL d'un type ne dépendait que de l'appelant : des sessions `pilote`
        # ouvertes à 4 h au lieu de 12. `bsi-claim.sh` lit désormais le
        # manifeste ; ceci vérifie que ce qui est ouvert le suit.
        Controle("le TTL des claims suit leur type",
                 "une session longue fermée à tort, faute du bon TTL",
                 [sys.executable, str(OUTILS / "ttl_des_claims.py"), "--brain", str(brain)]),
        Controle("les satellites à jour",
                 "une machine qui travaille sur un état que l'autre n'a pas",
                 [sys.executable, str(brain / "scripts" / "brain-satellites.py"),
                  "--brain", str(brain), "--check"]),
        Controle("suite de tests",
                 "un test qui n'exerce plus ce qu'il annonce",
                 [sys.executable, "test_brain_engine.py"], cwd=moteur),
        sante_du_service(brain),
    ]
    if complet:
        # `brick_test` exerce des routes protégées : il lui faut le jeton owner.
        # La session ne le voit pas (c'est voulu) — le doctor le lit, pour ce
        # seul contrôle, et ne l'affiche jamais. Sans lui, brick_test s'arrête
        # en le disant, plutôt que de mesurer des 401.
        jeton = os.environ.get("BRAIN_TOKEN_OWNER") or cle_de_mysecrets(brain, "BRAIN_TOKEN_OWNER")
        liste.append(Controle("fondation du CORE",
                              "une brique qui devient indispensable sans qu'on l'ait décidé",
                              [sys.executable, str(OUTILS / "brick_test.py"),
                               "--brain", str(brain), "--all"], lent=True,
                              env_extra={"BRAIN_TOKEN_OWNER": jeton} if jeton else None))
    return liste



#: Ce que des outils de portée gabarit lisent À CÔTÉ de `tools/` (leur
#: `RACINE`) : le doctor distribué les emporte au même endroit relatif.
RESSOURCES_GABARIT = ("contrat/capacites.yml",)


def fichiers_du_gabarit() -> list[str]:
    """Ce que le doctor distribué emporte, en chemins relatifs à la racine de ce
    dépôt : lui, les outils de ses contrôles de portée gabarit, ce qu'ils
    IMPORTENT, et leurs ressources. Pas ce qu'ils citent par leur nom —
    `test_controles_rougissent` éprouve des outils d'instance, et ses cas
    s'abstiennent quand l'outil n'est pas là."""
    locaux = {p.stem for p in OUTILS.glob("*.py")}
    a_voir = ["brain_doctor"]
    # Un brain qui n'existe pas : `complet=True` y cherche le jeton owner, et une
    # liste de fichiers n'a pas à lire MYSECRETS, même sans l'afficher.
    tous = controles(Path("/nulle-part/brain-du-listage"), complet=True)
    # `INSTANCE` nomme des contrôles : un renommage en ferait un contrôle de
    # portée gabarit, en silence, et il partirait chez les forks. Refus.
    inconnus = sorted(INSTANCE - {c.nom for c in tous})
    if inconnus:
        raise SystemExit("INSTANCE nomme des contrôles qui n'existent plus : "
                         + ", ".join(inconnus))
    for c in tous:
        if c.instance:
            continue
        for morceau in c.commande:
            p = Path(morceau)
            if p.suffix == ".py" and p.parent == OUTILS:
                a_voir.append(p.stem)
    # Un import se résout dans `tools/`, puis dans `bench/` — où certains outils
    # vont chercher un module (`parite_capacites` → `bench/parite_portes.py`,
    # importé paresseusement, dans une fonction). L'oubli a laissé le contrôle
    # du contrat sans son module chez un fork (2/10).
    banc = OUTILS.parent / "bench"
    # Le chemin publié (`tools/…`, relatif au dépôt) n'est pas toujours celui
    # du disque : livré, le doctor vit dans `brain-engine/doctor/`, pas dans
    # `tools/`. On LIT donc là où le fichier est vraiment.
    def chemin(m: str) -> tuple[str, Path] | None:
        if m in locaux:
            return f"tools/{m}.py", OUTILS / f"{m}.py"
        if (banc / f"{m}.py").is_file():
            return f"bench/{m}.py", banc / f"{m}.py"
        return None
    vus: dict[str, str] = {}
    while a_voir:
        m = a_voir.pop()
        c = chemin(m)
        if m in vus or c is None:
            continue
        vus[m] = c[0]
        texte = c[1].read_text(encoding="utf-8")
        a_voir += re.findall(r"^\s*(?:from|import)\s+([a-z_]+)", texte, re.M)
    return sorted(vus.values()) + list(RESSOURCES_GABARIT)


def temoin() -> int:
    """Vérifie le verdict de l'outil sur lui-même.

    Le premier jet classait la suite de tests « abstenue » parce que sa sortie
    contient `HELLOWORLD_SKIP` — et masquait donc un échec réel, en sortant en 0.
    Un détecteur de dérive qui cache un rouge est pire que pas de détecteur ;
    c'est le seul défaut de cet outil qu'on ne peut pas se permettre.
    """
    import tempfile

    cas = [
        ("abstention déclarée",
         'print("SKIP: backend sqlite — sans objet")', "abstenu"),
        ("SKIP au milieu, sortie 0",
         'print("HELLOWORLD_SKIP contient focus.md")\nprint("OK")', "vert"),
        ("SKIP au milieu, sortie 1",
         'print("HELLOWORLD_SKIP ...")\nprint("FAILED (failures=1)")\n'
         'import sys; sys.exit(1)', "rouge"),
        ("rouge franc",
         'print("3 écarts")\nimport sys; sys.exit(1)', "rouge"),
    ]
    # Le resume, pas seulement le verdict. L ancien temoin AFFICHAIT
    # `resume` sans jamais l asserter : le defaut vivait sous les yeux du temoin
    # qui aurait du l attraper. Le premier cas est l incident du 26/09, copie
    # mot pour mot.
    INCIDENT = '''\
print("BACKLOG -> ISSUES — 105 entrees, 20 ouvertes")
print("  a creer     20")
print("     Rien n'a ete ecrit. `--apply` pour deriver vraiment.")
import sys
sys.exit(1)
'''

    cas_resume = [
        ("l incident du 26/09", INCIDENT, "rouge",
         "Rien n'a ete ecrit. `--apply` pour deriver vraiment."),

        ("le meme, marqueur pose", INCIDENT.replace(
            'print("     Rien',
            'print("VERDICT: 20 item(s) ouvert(s) sans issue sur la forge")\n'
            'print("     Rien'), "rouge",
         "20 item(s) ouvert(s) sans issue sur la forge"),

        ("marqueur apres une auto-epreuve", '''\
print("✅ le cache sert")
print("✅ le cache sert, et il voit les deux sens")
print("VERDICT: 147 valides, 0 derive")
''', "vert", "147 valides, 0 derive"),

        ("sans marqueur au vert", '''\
print("✅ un cas de l auto-epreuve")
print("✅ 100 % conformes sur 572 commit(s) juges")
''', "vert", "100 % conformes sur 572 commit(s) juges"),

        ("sans marqueur au rouge", '''\
print("du detail avant")
print("❌ 3 ecarts")
print("une ligne apres le verdict")
import sys
sys.exit(1)
''', "rouge", "3 ecarts"),

        ("le marqueur ne rend pas vert", '''\
print("VERDICT: tout va bien")
import sys
sys.exit(1)
''', "rouge", "tout va bien"),

        ("deux marqueurs, le dernier gagne", '''\
print("VERDICT: cas fabrique par une auto-epreuve")
print("VERDICT: le vrai verdict de l outil")
''', "vert", "le vrai verdict de l outil"),

        ("l abstention garde la main", '''\
print("SKIP brain.db absent — ce controle ne mesure que SQLite.")
print("VERDICT: 29 tables, 4 index")
''', "abstenu", "SKIP brain.db absent — ce controle ne mesure que SQLite."),
    ]

    echecs = []
    print("\nTÉMOIN — le verdict de brain_doctor\n")
    with tempfile.TemporaryDirectory() as dossier:
        faux = Path(dossier) / "faux_controle.py"
        for nom, corps, attendu in cas:
            faux.write_text(corps, encoding="utf-8")
            verdict, resume, _ = Controle(nom, "", [sys.executable, str(faux)]).jouer()
            juste = verdict == attendu
            if not juste:
                echecs.append(nom)
            print(f"  {'✅' if juste else '❌'} {nom:<26} → {verdict:<8} "
                  f"attendu {attendu:<8} « {resume[:34]} »")

        print("\nTÉMOIN — le résumé, et d'où il vient\n")
        for nom, corps, att_verdict, att_resume in cas_resume:
            faux.write_text(corps, encoding="utf-8")
            verdict, resume, _ = Controle(nom, "", [sys.executable, str(faux)]).jouer()
            juste = verdict == att_verdict and resume == att_resume
            if not juste:
                echecs.append(nom)
                print(f"  ❌ {nom:<34} → {verdict} « {resume} »")
                print(f"     {'':<34}   attendu {att_verdict} « {att_resume} »")
            else:
                print(f"  ✅ {nom:<34} → {verdict:<8} « {resume[:46]} »")

    total = len(cas) + len(cas_resume)
    if echecs:
        print(f"\nVERDICT: {len(echecs)} cas sur {total} — " + ", ".join(echecs))
        print(f"\n  ❌ {', '.join(echecs)}\n")
    else:
        print(f"\nVERDICT: verdict et résumé fiables — {total} cas, "
              f"dont l'incident du 26/09")
        print("\n  ✅ le verdict et le résumé sont fiables\n")
    return 1 if echecs else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--brain", type=Path, required=False)
    parser.add_argument("--portee", choices=("tout", "gabarit"), default="tout",
                        help="gabarit : seulement les contrôles qui jugent un brain "
                             "générique — ce que le doctor distribué joue")
    parser.add_argument("--lister-gabarit", action="store_true",
                        help="les fichiers du doctor distribué, un par ligne")
    parser.add_argument("--complet", action="store_true",
                        help="ajouter les contrôles lents (test de fondation)")
    parser.add_argument("--temoin", action="store_true",
                        help="vérifier le verdict de l'outil sur lui-même")
    args = parser.parse_args()

    if args.temoin:
        return temoin()
    if args.lister_gabarit:
        for f in fichiers_du_gabarit():
            print(f)
        return 0

    if not args.brain:
        parser.error("--brain est requis (sauf avec --temoin)")
    brain = args.brain.expanduser().resolve()
    if not (brain / "brain-engine").is_dir():
        print(f"FAIL: {brain} ne ressemble pas à un brain", file=sys.stderr)
        return 2

    reference = subprocess.run(["git", "-C", str(brain), "log", "--format=%h %s", "-1"],
                               capture_output=True, text=True)
    print(f"\nBRAIN DOCTOR — {brain}")
    if reference.returncode == 0:
        print(f"  {reference.stdout.strip()[:88]}")
    print()

    resultats = []
    tous = controles(brain, args.complet)
    joues = [c for c in tous if args.portee == "tout" or not c.instance]
    if len(joues) < len(tous):
        print(f"  portée gabarit — {len(tous) - len(joues)} contrôle(s) propres à "
              "l'instance d'origine ne sont pas joués\n")
    for controle in joues:
        verdict, resume, duree = controle.jouer()
        resultats.append((controle, verdict, resume))
        marque = {"vert": "✅", "rouge": "❌", "abstenu": "⏭️"}[verdict]
        print(f"  {marque} {controle.nom:<28} {duree:>5.1f}s  {resume}")

    rouges = [(c, r) for c, v, r in resultats if v == "rouge"]
    abstenus = [c for c, v, _ in resultats if v == "abstenu"]

    print()

    # La migration se compte, elle ne se suppose pas. Un controle qui
    # ne declare pas son verdict laisse le doctor le deviner, et le defaut ne se
    # voit qu au hasard : les trois premieres occurrences ont ete trouvees en
    # faisant verdir un controle, la quatrieme en lisant le code par hasard.
    # Cette ligne ne bloque rien — elle rend le reste a migrer visible.
    devines = [c.nom for c, v, _ in resultats if c.origine == "devine"]
    declares = [c.nom for c, v, _ in resultats if c.origine == "declare"]
    # ⚠️ Cette ligne s imprime TOUJOURS, y compris quand plus rien n est devine.
    # Une mesure qui disparait au vert rend la meme chose que son absence : on ne
    # distingue plus « tout est migre » de « le pied de page est casse ». C est le
    # defaut que ce correctif vient de corriger, applique a lui-meme.
    print(f"  📋 résumés — {len(declares)} déclaré(s) · {len(devines)} deviné(s)")
    if devines:
        print("     Un résumé deviné peut afficher autre chose que le verdict "
              ".\n")
    else:
        print("     Tous déclarent le leur — le doctor ne devine plus rien.\n")

    if abstenus:
        print(f"  ⏭️  {len(abstenus)} contrôle(s) abstenu(s) — "
              f"{', '.join(c.nom for c in abstenus)}")
        print("     Un vert qui ne mesure rien serait pire qu'un rouge.\n")
    if not rouges:
        print(f"  ✅ aucune dérive — {len(resultats) - len(abstenus)} contrôle(s) au vert\n")
        return 0

    print(f"  ❌ {len(rouges)} dérive(s) — ce qui se dégrade en silence :\n")
    for controle, resume in rouges:
        print(f"     {controle.nom}")
        print(f"       sans lui : {controle.protege}")
        print(f"       constat  : {resume}")
    print("\n  Démyélinisation : rien ne casse, tout dégrade. C'est pour ça que ces")
    print("  contrôles existent — aucune de ces dérives ne lève une erreur toute seule.\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
