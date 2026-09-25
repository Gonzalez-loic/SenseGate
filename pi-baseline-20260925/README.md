# Copie de référence de la production Pi

Les huit fichiers `app/*.py` sont des copies byte-for-byte des sources du Pi avant essais. Les empreintes sont dans `source-sha256.json`. Ce répertoire ne contient ni secrets, ni compteurs, ni vidéos.

**Ne pas installer `sensegate-device/` par-dessus cette architecture.** Le logiciel installé utilise `/home/loic/people_counter`, ses fichiers JSON locaux et ses services systemd existants.

Les binaires Hailo et paramètres privés nécessaires à une reconstruction sont dans la sauvegarde chiffrée séparée. Pour un retour arrière logiciel, restaurer seulement les sources concernées, conserver les compteurs récents et vérifier les empreintes avant redémarrage. Voir `docs/RESTAURATION_PI.md`.
