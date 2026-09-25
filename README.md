# SenseGate — sauvegarde Pi et essais de détection

Cette branche conserve **l'architecture Pi réellement installée au 25 septembre 2026** et un banc d'essai isolé. Le répertoire historique `sensegate-device/` n'est pas le logiciel actuellement exécuté sur le Pi : il n'a pas été remplacé ni déployé.

- `pi-baseline-20260925/` : huit sources actives, sans fichiers de configuration privés, avec empreintes SHA-256.
- `tools/` : sauvegarde chiffrée, vérification de restauration, tests de contrat et comparaison hors ligne des détecteurs.
- `docs/ESSAIS_20260925.md` : mesures et limites.
- `docs/RESTAURATION_PI.md` : emplacement et procédure de récupération.
- `tracking/` : comparaison isolée du suivi d'identité et capture temporaire des détections réelles.
- `docs/TRACKING_20260925.md` : résultats de suivi et limites de la conservation d'ID pendant 1,5 seconde.
- `docs/POINT1_FAIBLES_SCORES_20260925.md` : candidat conservateur sur le suivi actuel, tests et comparaison sans effet sur les compteurs officiels.

## Contraintes

Le VPS, les API et les calculs serveur restent inchangés. Aucun changement du client de synchronisation, du format des statistiques, du sens IN/OUT, de la ligne ou du calcul d'occupation n'est déployé. Les résultats d'essai ne sont jamais envoyés comme comptages de production.

Le code présent dans Git **n'est pas une image de la carte SD**. Les secrets, vidéos, données privées, modèles binaires et sauvegardes chiffrées ne sont pas dans Git.

## Tests locaux

Python 3 et `cryptography` sont nécessaires pour les tests de sauvegarde. Les essais réels de détection utilisent les bibliothèques déjà installées sur le Pi, sans mise à jour globale des pilotes.

```sh
python -m unittest discover -s tools -p 'test_*.py' -v
```

Les scripts `run_bounded_benchmark.py` et `prepare_*_pi.py` sont spécifiques à la campagne du 25/09 et **ne doivent pas être lancés sans préparation et créneau de maintenance**. Le comptage s'interrompt pendant le rejeu Hailo ; le moteur initial est remis automatiquement en service.
