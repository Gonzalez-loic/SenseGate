# Banc d'essai de tracking — pas un déploiement

Les scripts utilisent le compteur sauvegardé, sans modifier les calculs VPS ni y envoyer des résultats d'essai. `ByteTrack` est testé comme remplacement de l'association des boîtes uniquement. La confirmation de franchissement reste confiée au compteur d'origine et ne reçoit que des boîtes réellement détectées, jamais des positions prédites seules.

## Tests synthétiques

Dans un environnement Python isolé disposant des dépendances de `requirements-experiment.txt` :

```sh
python -m unittest discover -s tracking -p 'test_*.py' -v
```

`test_tracking.py` prend le compteur figé dans `pi-baseline-20260925/app/counter_logic.py`, ou `counter_baseline.py` dans le dossier temporaire de campagne sur le Pi.

`adversarial_check.py` illustre séparément une **limite connue et bloquante** : une seconde personne surgissant à la position prédite après 1,2 seconde peut être prise pour la première. La variante autorisant aussi le franchissement après 1,5 seconde produit alors une fausse entrée. Les tests réussis ne signifient pas que cette variante est sûre.

Supervision 0.26.1 est figé pour cet essai. Sa classe ByteTrack utilise Kalman et l'association en deux passes, dont une pour les scores faibles. Le seuil de naissance reste 0,3 ; les scores de 0,2 à 0,3 peuvent seulement entretenir une piste déjà créée. La durée d'expiration est contrôlée à la fois par le buffer du tracker et par les secondes du compteur. Cela ne garantit ni l'identité d'une personne ni l'absence de doubles comptages.

## Rejeu privé

Les scripts de campagne supposent un dossier temporaire préparé sur **ce Pi**, avec une copie vérifiée du compteur, les paramètres autorisés dans `counter-config.json` et les détections privées. Ils ne constituent pas un installateur générique.

- `cache_detections.py` : inférence de chaque image de 12 clips figés, avant comparaison CPU ; nécessite une fenêtre sans moteur Hailo concurrent.
- `replay.py` : compare six variantes sur le même cache ; ne touche pas aux compteurs réels.
- `prepare_pi.py` : exporte seulement une liste autorisée de paramètres, jamais les clés/API de configuration.
- `event_contact_sheets.py` : preuves visuelles privées des deux événements supplémentaires du rejeu vidéo.
- `live_trace.py` : observation temporaire des décisions **du moteur d'origine**, sans double inférence. Tous les résultats du détecteur sont enregistrés ; des images brutes sont conservées à au plus 5 Hz sur une file bornée, uniquement lorsqu'une personne est détectée ou pendant les deux secondes suivantes. Cette sélection ne peut pas révéler une personne jamais détectée.
- `run_live_trace.py` : sauvegarde et restaure l'entrée avant exécution de la capture en mémoire ; délai dur de 220 secondes, puis reprise normale par systemd. **Deux redémarrages créent de brèves interruptions**. Ne pas lancer sans créneau, sauvegarde vérifiée et surveillance de la reprise.
- `replay_live.py` : exige que le rejeu du compteur actuel reproduise les IDs et événements réels, avant toute interprétation des variantes.
- `live_contact_sheet.py` : inspection privée du passage observé pendant la capture ; script spécifique à cette séquence.

Les variantes `immediate` permettent de tester la publication des boîtes dès leur naissance, puisque le compteur exige déjà sa propre confirmation. Elles corrigent le scénario synthétique de sortie rapide, mais ne corrigent pas le passage réel testé : voir le rapport. Elles ne sont pas déployées.

Les captures, vidéos, images et traces restent hors Git. Aucun pourcentage de précision ne peut être déduit des scores du détecteur, du nombre d'IDs ou de ces seuls tests.

Références : [ByteTrack dans Supervision 0.26.1](https://github.com/roboflow/supervision/blob/0.26.1/supervision/tracker/byte_tracker/core.py), [ByteTrack original](https://github.com/ifzhang/ByteTrack).

## Point 1 : maintien par scores faibles sur le tracker actuel

`low_score_counter.py` est un candidat distinct, sans dépendance ByteTrack : il garde le traitement original des scores forts et utilise les scores 0,20–0,30 seulement pour maintenir une piste confirmée, sans création d'ID ni comptage faible. Voir `docs/POINT1_FAIBLES_SCORES_20260925.md` pour les limites précises et les résultats.

Tests ciblés, avec la bibliothèque standard seulement :

```sh
python -m unittest discover -s tracking -p 'test_low_score*.py' -v
```

`low_score_replay.py` reçoit explicitement `--input`, `--config`, `--source` et `--output`. Il refuse d'écraser un résultat existant. Pour la comparaison temporaire en direct, un fichier `shadow-enabled.json` conforme à l'exemple doit être placé dans le dossier de capture ; le compteur de référence et le candidat tournent en mémoire sur les mêmes observations, sans publication de leurs résultats. Le fichier du compteur de référence doit correspondre exactement au compteur actif du Pi. Les durées et mécanismes de reprise du test restent ceux de `run_live_trace.py`.
