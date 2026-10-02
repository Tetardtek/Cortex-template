#!/usr/bin/env python3
"""`close-stale` ferme-t-il exactement ce qu'il a liste ? — ne le 15/09.

Ce qui pourrirait en silence sans lui : **une session vivante fermee sous les
pieds de qui travaille dedans.**

`cmd_close_stale` pose deux requetes — une qui LISTE les claims oublies, une
qui les FERME. Tant qu'elles portent chacune leur propre critere temporel,
rien ne garantit qu'elles designent le meme ensemble, et une divergence ne
leve aucune erreur : la commande annonce ce qu'elle a liste, et ferme autre
chose.

    python3 tools/close_stale_ferme_sa_liste.py --brain ~/Dev/Brain

── Ce qui l'a fait naitre ───────────────────────────────────────────────────

Mesure du 15/09, en instruisant :

    SELECT  TIMESTAMPDIFF(HOUR, COALESCE(expires_at, opened_at+ttl), now) > seuil
    UPDATE  TIMESTAMPDIFF(HOUR, opened_at,                           now) > seuil

Le SELECT mesurait depuis l'EXPIRATION — la correction du 04/09, qui a donne
son role a `expires_at` : repousse par `touch` a chaque commit, il est le signe
de vie d'une session. L'UPDATE mesurait depuis l'OUVERTURE, ce que le
commentaire du meme fichier decrit comme le defaut corrige. **Seule la premiere
requete avait recu la correction.**

Une session ouverte depuis 20 h mais touchee il y a cinq minutes n'etait donc
pas listee — son `expires_at` est dans le futur — et etait fermee quand meme.
C'est exactement ce que le commentaire de `brain-close-stale.service` dit
vouloir eviter : *« Fermer un claim sous les pieds de qui travaille dedans
fausse sa duree et le declare mort a tort. »*

Le defaut n'a jamais frappe — l'UPDATE ne part que si le SELECT a trouve au
moins un claim, et les 21 fermetures `stale-auto-closed` de la base sont toutes
anterieures au 04/09. **Un zero mesure, pas une innocuite** : le timer tourne
tous les jours a 06:00.

── L'invariant que ce controle tient ────────────────────────────────────────

    le SELECT  porte le critere temporel — c'est lui qui DECIDE
    l UPDATE   ferme par `sess_id`       — il ne decide de rien

Fermer par identifiants supprime la divergence PAR CONSTRUCTION : il n'y a plus
deux criteres a tenir d'accord, il n'y en a qu'un. Ce controle refuse qu'un
second reapparaisse.

── Pourquoi l'AST, et sur du shell ──────────────────────────────────────────

`bsi-claim.sh` est un script shell qui passe un bloc Python a `python3` par un
heredoc. On extrait ce bloc et on le **parse**. Chercher `TIMESTAMPDIFF` dans le
texte du fichier compterait les occurrences des commentaires — dont ceux qui
racontent precisement ce defaut, et qui feraient rougir le controle pour la
raison inverse de celle qu'il surveille.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

# La regle vit desormais a DEUX endroits, depuis que `close-stale` est passe
# par le moteur : la route decide, le repli local prend la
# suite quand le moteur ne repond pas. Les deux ferment des claims, donc les
# deux doivent tenir l invariant — et surtout, ils doivent le tenir PAREIL.
#
# C est le motif de toute une serie de defauts : une bonne regle appliquee
# d un cote et pas de son voisin. Ce controle la cherche aux deux.
PORTES = (
    ("scripts/bsi-claim.sh", "_fermer_stale_en_repli", "le repli local"),
    ("brain-engine/server.py", "bsi_claims_close_stale", "la route du moteur"),
)
# `cmd_close_stale` ne porte plus de SQL depuis la bascule : elle appelle le
# moteur et se replie. Son absence de requete est donc NORMALE — mais elle
# doit etre verifiee, pas supposee : si elle se remettait a ecrire, la bascule
# serait defaite.
COMMANDE = ("scripts/bsi-claim.sh", "cmd_close_stale")
HORLOGES = ("TIMESTAMPDIFF", "UTC_TIMESTAMP", "DATE_ADD", "NOW(")


def bloc_python(source_shell: str) -> str | None:
    """Le heredoc Python de `bsi-claim.sh`, sans le shell autour."""
    m = re.search(r"<<'PYEOF'\n(.*?)\nPYEOF", source_shell, re.S)
    return m.group(1) if m else None


def texte_sql(noeud: ast.AST) -> str:
    """Le litteral d'une chaine, f-string comprise.

    Une f-string est un `JoinedStr` : ses parties constantes portent le SQL, ses
    `FormattedValue` portent les interpolations. On garde les premieres et on
    marque les secondes — une interpolation peut cacher n'importe quoi, et le
    controle doit le dire plutot que de l'ignorer.
    """
    if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
        return noeud.value
    if isinstance(noeud, ast.JoinedStr):
        bouts = []
        for part in noeud.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                bouts.append(part.value)
            else:
                bouts.append(" <interpolation> ")
        return "".join(bouts)
    return ""


def requetes(fonction: ast.AST) -> tuple[list[str], list[str]]:
    """(SELECT, ecritures) — le SQL passe a `db.query` et `db.execute`."""
    lectures, ecritures = [], []
    for n in ast.walk(fonction):
        if not isinstance(n, ast.Call) or not n.args:
            continue
        cible = n.func
        nom = cible.attr if isinstance(cible, ast.Attribute) else getattr(cible, "id", "")
        if nom not in ("query", "execute", "query_one"):
            continue
        sql = texte_sql(n.args[0])
        if not sql.strip():
            continue
        (ecritures if nom == "execute" else lectures).append(" ".join(sql.split()))
    return lectures, ecritures


def source_de(brain: Path, fichier: str) -> str | None:
    """Le Python d'un fichier du brain — heredoc extrait si c'est un shell."""
    chemin = brain / fichier
    if not chemin.is_file():
        return None
    brut = chemin.read_text(encoding="utf-8")
    return bloc_python(brut) if fichier.endswith(".sh") else brut


def fonction_de(source: str, nom: str):
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    return None


def examine(nom: str, role: str, fonction) -> list[str]:
    """L'invariant, sur une porte. Rend la liste de ses ecarts."""
    lectures, ecritures = requetes(fonction)
    print(f"  {role} — `{nom}` : {len(lectures)} lecture(s), {len(ecritures)} ecriture(s)")

    if not lectures or not ecritures:
        return [f"{nom} ne fait plus une lecture ET une ecriture — "
                f"l'invariant n'a plus de sens sous cette forme"]

    fautes = []
    if not any("expires_at" in sql for sql in lectures):
        fautes.append(f"{nom} : le SELECT ne mesure plus depuis `expires_at` — "
                      "la correction du 04/09 a disparu")
    for sql in ecritures:
        where = sql.split(" WHERE ", 1)[1] if " WHERE " in sql else sql
        horloges = [h for h in HORLOGES if h in where]
        par_id = "sess_id IN" in where or "sess_id =" in where
        print(f"     {'✅' if (par_id and not horloges) else '❌'} UPDATE  "
              f"par sess_id: {par_id}  ·  horloge(s) dans le WHERE: "
              f"{', '.join(horloges) or 'aucune'}")
        if horloges:
            fautes.append(f"{nom} : l'UPDATE decide lui-meme par "
                          f"{', '.join(horloges)} — deux criteres, deux ensembles")
        elif not par_id:
            fautes.append(f"{nom} : l'UPDATE ne ferme pas par `sess_id`")
    return fautes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", default=str(Path.home() / "Dev/Brain"))
    args = ap.parse_args()
    brain = Path(args.brain).expanduser()

    print("CLOSE-STALE — la meme regle aux deux portes\n")

    fautes, vues = [], 0
    for fichier, nom, role in PORTES:
        source = source_de(brain, fichier)
        if source is None:
            fautes.append(f"{fichier} introuvable ou illisible — "
                          f"ce controle ne peut pas mesurer `{nom}`")
            continue
        f = fonction_de(source, nom)
        if f is None:
            fautes.append(f"`{nom}()` n'existe plus dans {fichier} — "
                          "renommee, retiree, ou la bascule a change de forme")
            continue
        vues += 1
        fautes += examine(nom, role, f)

    # 🔴 La commande ne doit PLUS ecrire : elle appelle le moteur et se replie.
    # Si elle s'y remettait, la bascule serait defaite — et aucune des
    # verifications ci-dessus ne le dirait, puisqu'elles portent ailleurs.
    src_cmd = source_de(brain, COMMANDE[0])
    f_cmd = fonction_de(src_cmd, COMMANDE[1]) if src_cmd else None
    if f_cmd is None:
        fautes.append(f"`{COMMANDE[1]}()` introuvable — la commande a disparu")
    else:
        lec, ecr = requetes(f_cmd)
        print(f"\n  la commande — `{COMMANDE[1]}` : {len(lec)} lecture(s), "
              f"{len(ecr)} ecriture(s)  (0 et 0 attendus depuis la bascule)")
        if lec or ecr:
            fautes.append(f"{COMMANDE[1]} ecrit ou lit en direct — "
                          "la bascule vers le moteur est defaite")

    if vues < len(PORTES):
        fautes.append(f"{vues} porte(s) sur {len(PORTES)} mesuree(s) — "
                      "un controle qui ne trouve plus ce qu'il mesure ne vaut rien")

    print()
    if fautes:
        print(f"  ❌ {len(fautes)} ecart(s) :")
        for f in fautes:
            print(f"       {f}")
        print()
        print("     Une commande qui LISTE selon un critere et FERME selon un autre")
        print("     annonce ce qu'elle a liste, et ferme autre chose. Rien ne leve.")
        return 1

    print(f"  ✅ les {len(PORTES)} portes tiennent le meme invariant — "
          f"le SELECT decide, l'UPDATE ferme sa liste")
    return 0


if __name__ == "__main__":
    sys.exit(main())
