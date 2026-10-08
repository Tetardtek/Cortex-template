---
# Généré depuis docs/src/installer-avec-claude.md par scripts/docs-generer.py — ne pas éditer ici.
label: Installer avec Claude
groupe: Démarrer
ordre: 0.5
---

# Installer un brain avec Claude — la procédure guidée

> **Cette page s'adresse à un Claude** qui accompagne une personne dans
> l'installation de son brain. Donne-la-lui telle quelle : elle ne suppose
> rien d'autre. Kernel v3.5.3.

---

## Ce qu'il faut savoir avant de commencer

Le brain s'installe comme un **programme** (le paquet `brain-cortex`, qui pose
la commande `brain`), puis `brain init` crée **le brain de la personne** : un
dossier à elle, qui ne contient que ses données et des liens vers le programme.

**Ce qui n'existe pas encore** : le paquet n'est pas sur PyPI. Il se reçoit de
celui qui le publie, sous l'une de deux formes :

- l'adresse d'un **index** (un registre de paquets) et une **version** ;
- un **fichier** `brain_cortex-<version>-py3-none-any.whl`.

Si la personne n'a ni l'un ni l'autre, arrête-toi là et dis-le-lui : il n'y a
rien à installer.

### Tes règles, pendant toute la procédure

1. **Demande avant** tout geste qui touche plus que l'installation : `sudo`, une
   modification d'un fichier de démarrage du shell (`~/.bashrc`…), le
   remplacement d'un `~/.claude/CLAUDE.md` existant, l'ajout d'un serveur MCP à
   Claude Code. Si la personne n'est pas là pour répondre, ne le fais pas :
   note-le, et passe à ce qui ne le demande pas.
2. **Les secrets ne se lisent pas.** Le fichier `brain-secrets/MYSECRETS` du
   brain, les jetons, les clés : tu ne les ouvres pas, tu ne les affiches pas.
   Le brain fonctionne sans eux.
3. **Tout se fait en tant que la personne**, jamais en root — sauf `sudo` pour
   installer un prérequis, et seulement avec son accord.
4. **Une étape ratée s'arrête là.** Lis le message, applique la ligne « si ça
   échoue » de l'étape, et sinon rapporte-le à la personne. Ne contourne pas un
   refus du brain : il protège quelque chose.
5. **Dis à la personne, à chaque étape**, ce que tu as fait et ce que tu as vu.
6. **Chaque vérification se lance**, même si tu crois connaître la réponse : c'est
   elle qui décide de l'étape suivante.

### Ce que tu demandes à la personne

| Quoi | Exemple | Par défaut |
|---|---|---|
| le nom du brain | `mon-brain` | `mon-brain` |
| le dossier du brain | `~/MonBrain` | `~/MonBrain` |
| la source du paquet | un index et une version, ou un fichier `.whl` | — à fournir |

---

## 1. Les prérequis

```bash
python3 --version     # 3.12 ou plus
pipx --version
git --version
```

**On vérifie** : les trois répondent, et Python est en 3.12 ou plus.

**Si ça échoue** — il manque un outil. Propose sa commande d'installation
selon la distribution, et **demande** avant de lancer `sudo` :

| Distribution | Commande |
|---|---|
| Arch | `sudo pacman -S python python-pipx git` |
| Debian, Ubuntu | `sudo apt install python3 python3-venv pipx git` |
| Fedora | `sudo dnf install python3 pipx git` |
| macOS | `brew install python pipx git` |

⚠️ **Debian 12 et Ubuntu 22.04 fournissent un Python trop ancien** (3.11, 3.10 — il faut
3.12) : `apt install python3` ne suffit pas. Debian 13 et Ubuntu 24.04 conviennent.
Sinon, propose un Python 3.12 installé à part (`uv python install 3.12`, ou pyenv), puis
`pipx install --python <ce python> …` — et **demande** avant.

## 2. Installer le programme

Depuis un **index** (remplace `<INDEX>` et `<VERSION>`) :

```bash
pipx install --index-url <INDEX> --pip-args="--extra-index-url https://pypi.org/simple" "brain-cortex==<VERSION>"
```

Depuis un **fichier** :

```bash
pipx install <chemin/vers/brain_cortex-VERSION-py3-none-any.whl>
```

La version s'écrit **exacte** (`==`) : les dépendances viennent de PyPI, et pip
prend la plus haute version qu'il voit sur les deux index.

**Un index privé demande un jeton.** Sans lui, pip répond `401`. C'est à **la
personne** de l'écrire, pas à toi : un jeton est un secret (règle 2). Dis-lui de
créer `~/.netrc`, lisible d'elle seule, avec l'hôte de l'index, son identifiant
et son jeton de **lecture** :

```text
machine <hôte de l'index>
login <son identifiant>
password <son jeton>
```

puis `chmod 600 ~/.netrc`. pip le lit tout seul ; relance ensuite l'installation.
Tu ne l'ouvres pas pour vérifier : l'installation qui réussit le prouve.

**On vérifie** :

```bash
command -v brain
```

**Si ça échoue** — `brain` est introuvable : pipx l'a posée dans
`~/.local/bin`, qui n'est pas dans le `PATH`. Pour la suite, appelle-la par
`~/.local/bin/brain`. `pipx ensurepath` l'ajoute pour de bon, mais modifie le
fichier de démarrage du shell : **demande** avant.

## 3. Le dernier contrôle

```bash
brain init --verifier
```

**On vérifie** : « brain init peut tourner ». Rien n'est écrit. Les lignes
« recommandé » (Claude Code, Node) ne bloquent pas : dis-les à la personne.

## 4. Créer le brain

D'abord, la machine a-t-elle **systemd en session utilisateur** ?

```bash
systemctl --user is-system-running
```

S'il répond (même `degraded`), les services démarreront seuls. S'il échoue,
ajoute `--sans-service` à la commande suivante : le brain se lancera à la main.

```bash
brain init <NOM> <DOSSIER>                  # avec systemd
brain init <NOM> <DOSSIER> --sans-service   # sans
```

`brain init` crée le dossier, y pose la configuration de la machine, la base,
la vue du programme, et écrit `~/.claude/CLAUDE.md` **s'il n'existe pas**. S'il
existe, il n'y touche pas et le dit : **demande** à la personne avant de
relancer avec `--reecrire-claude-md` (l'ancien est sauvegardé à côté).

**On vérifie** :

```bash
ls <DOSSIER>/brain-compose.local.yml
cat ~/.config/brain-cortex/brain     # le dossier du brain, déclaré
```

**Si ça échoue** — relis la sortie : `brain init` dit ce qui manque, et se
relance sans risque (une seconde passe ne change rien de ce qui est fait).

## 5. Démarrer le brain

Avec systemd, les services tournent déjà. Sans (`--sans-service`) :

```bash
cd <DOSSIER> && bash scripts/brain-engine.sh start
```

**Ne lance pas la base toi-même** : `start` lance aussi la base (Dolt) si elle
ne tourne pas, avec ses journaux dans le dossier du brain.

**On vérifie** :

```bash
cd <DOSSIER> && bash scripts/brain-engine.sh status
```

**Si ça échoue** — `bash scripts/brain-engine.sh logs --fin` montre les dernières
lignes du journal et rend la main (sans `--fin`, il le suit sans fin) ; un port déjà
pris se dit en clair.

## 6. Le brain se contrôle

```bash
cd <DOSSIER> && brain doctor
```

**On vérifie** : le code de sortie est `0`. Une ligne ⏭️ s'abstient et dit
pourquoi : ce n'est pas une erreur.

**Si ça échoue** — une ligne ❌ dit ce qui dérive. Rapporte-la à la personne
telle quelle : on corrige la cause, jamais le contrôle.

## 7. Brancher Claude Code

Le serveur MCP du brain donne à Claude Code la mémoire de ce brain. Son port :

```bash
cd <DOSSIER> && brain serve --ports
```

Puis, **avec l'accord de la personne** (cela modifie sa configuration de
Claude Code) :

```bash
claude mcp add --transport http brain http://127.0.0.1:<PORT_MCP>/mcp
```

Toujours vers **sa** machine (`127.0.0.1`) : un MCP lit le brain de celui qui
le sert.

## 8. La première session — c'est la personne qui la lance

```bash
cd <DOSSIER> && claude
```

Puis elle tape `brain boot`. Un brain neuf est vide : il se remplit en
travaillant. Dis-le-lui, et donne-lui la page **Sessions** pour la suite.

---

## Ce que tu rapportes à la fin

- les étapes faites, et celles que tu n'as pas faites parce qu'elles
  demandaient son accord ;
- le dossier du brain, et le résultat de `brain doctor` ;
- ce qu'elle doit faire elle-même : brancher Claude Code (étape 7) si ce n'est
  pas fait, puis la première session (étape 8).
