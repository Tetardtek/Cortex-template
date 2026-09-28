"""Le CORE de Myéline — le programme, séparé de la data.

Six capacités, arrêtées le 02/09 par et vérifiées par `brick_test.py` :
persistance, index+recherche, écriture gouvernée, identité/zones, traces, BSI.

**Rien ici ne connaît l'arborescence d'un brain.** Un CORE qui déduit où vivent
les données de sa propre position ne peut pas être un programme : il devient une
partie de l'installation qu'il sert. C'est ce que `brain-engine/db.py` fait
aujourd'hui — `BRAIN_ROOT = Path(__file__).parent.parent` — et c'est le premier
point qu'on ne rapatrie pas.
"""

__version__ = "0.1.0"
