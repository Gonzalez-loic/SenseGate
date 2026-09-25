# Point 1 — maintien des pistes avec détections faibles

## Périmètre

Implémentation expérimentale basée sur le **compteur actuel**, sans ByteTrack ni nouvelle dépendance. Le modèle YOLOv8s, le prétraitement, le matériel, la ligne, le client de synchronisation, le VPS et les formats de données restent inchangés.

Le candidat est utilisé uniquement pour une comparaison isolée : ni ses IDs ni ses événements ne sont écrits dans les fichiers de comptage, les aperçus ou les API de production. Une copie séparée du compteur actuel vérifie que le rejeu des observations reproduit les décisions réelles.

## Garde-fous mis en œuvre

1. Traitement prioritaire des détections de score **≥0,30**, par le code d'origine.
2. Les observations de score **0,20 ≤ score < 0,30** peuvent uniquement maintenir une piste existante, déjà confirmée par au moins trois détections fortes et un côté stable.
3. Une observation faible ne crée jamais d'identité, n'augmente pas le nombre de confirmations fortes et n'appelle jamais la confirmation de côté ni le comptage.
4. Après une observation faible acceptée, le prochain franchissement exige une nouvelle série de confirmations fortes : au moins deux observations, réparties sur au moins 0,06 seconde.
5. Maintien faible limité initialement à **0,50 seconde depuis la dernière observation forte**, avec un trou maximal de **0,20 seconde** entre observations. Il ne s'agit pas d'un maintien aveugle de 1,5 seconde.
6. Distance maximale 90 pixels dans les coordonnées 1280×720, recouvrement des boîtes ≥0,20, ratio de surface ≤2 et ratios de largeur/hauteur ≤1,8. Vérification du déplacement, du sens et de l'erreur de prédiction ; cas stationnaire traité avec une limite de 20 pixels et un recouvrement ≥0,60.
7. Refus d'une association faible ambiguë : plusieurs pistes compatibles avec une boîte, plusieurs boîtes compatibles avec une piste, ou recouvrement avec une détection forte déjà traitée.
8. Seules des observations réelles mettent à jour la piste. L'absence de détection ne crée aucun événement prédit.

Ces valeurs sont des paramètres initiaux prudents, **pas une calibration validée de précision**. Des personnes différentes peuvent présenter des observations géométriques similaires ; ces filtres ne prouvent pas l'identité.

## Vérifications effectuées avant la capture

- 20 tests de suivi passent sur PC et Pi : parité exacte avec le moteur d'origine sur les séquences à scores forts, seuils, priorité aux détections fortes, cas ambigus, expiration, durées bornées, changement de taille, retournement, absence de comptage avec des observations faibles seules.
- Un scénario synthétique comportant un intervalle faible de 0,6 seconde retrouve une entrée, seulement après retour et confirmation des observations fortes. Ce résultat synthétique n'est pas présenté comme une entrée réelle récupérée.
- 3 tests de comparaison vérifient que le compteur principal n'est pas modifié, que les événements du candidat ne sortent pas dans les logs normaux et qu'une divergence de référence est signalée.
- 3 tests d'instrumentation et 13 tests antérieurs de sauvegarde/contrat VPS passent. Une erreur de démarrage est inscrite dans le résultat avant finalisation ; une capture vide ou une comparaison demandée mais absente ne peut être déclarée réussie.

## Rejeu des preuves privées antérieures

| Lot | Référence | Candidat | Observations faibles utilisées |
|---|---|---|---:|
| Capture réelle de 4 032 images du matin | 0 IN / 1 OUT | 0 IN / 1 OUT | 4 sur 10 |
| 12 clips compressés, 631 images | 1 IN / 0 OUT | 1 IN / 0 OUT | 23 sur 93 |

Sur la capture réelle précédente, parité exacte de la référence avec les IDs et événements enregistrés en direct. La sortie qui était perdue avec les variantes ByteTrack reste comptée avec ce candidat.

Sur les clips, 16 observations faibles sont écartées car elles recouvrent des détections fortes et 54 faute d'association sûre. Les limites du rejeu vidéo déjà décrites dans `TRACKING_20260925.md` restent applicables : compression, incrustations et faible cadence. Un score faible utilisé n'est ni une personne supplémentaire ni un passage récupéré.

## Capture en direct du point 1

Capture du 25/09/2026, vers 16:29–16:32 CEST : **4 004 images**, durée totale instrumentée **180,10 secondes**, cadence moyenne **22,50 images/s**.

- Compteur réel : **1 IN / 1 OUT** pendant la capture ; candidat : **1 IN / 1 OUT** également.
- Copie de référence conforme aux IDs, boîtes et compteurs réels à chaque image ; aucune erreur de parité.
- 37 observations faibles reçues : **14 utilisées**, 11 écartées car elles recouvrent une détection forte, 12 sans partenaire sûr.
- Les deux variantes créent 9 IDs sur la séquence : **aucune réduction du nombre total d'IDs démontrée**.
- Le candidat confirme l'entrée deux images plus tard, soit **85,7 ms**, à cause de la nouvelle confirmation forte requise après une observation faible. La sortie est comptée à la même image. Aucune correction de total n'est effectuée.
- Inspection des images sélectionnées par l'assistant : une sortie et une entrée visibles, correspondant aux deux événements. Ce contrôle n'est ni une annotation humaine indépendante ni une revue exhaustive des trois minutes.
- Rejeu indépendant sur PC : mêmes pistes candidates sur les **4 004 images**, mêmes totaux et mêmes 14 observations faibles utilisées.
- Temps médian du calcul des deux copies de comparaison : **0,049 ms** ; hook complet d'enregistrement : **0,069 ms**. L'encodage des images dans un autre thread n'est pas inclus dans ces temps.
- Aucune erreur de capture, aucune image abandonnée par la file d'attente, absence de bridage signalée (`throttled=0x0`).

Au début : **43 IN / 37 OUT** ; après reprise : **44 IN / 38 OUT**. Quatre services Pi actifs, sources applicatives et configuration vérifiées inchangées. Le comptage original est resté actif pendant la capture, sauf les brefs redémarrages de début et de fin. Les totaux du candidat n'ont jamais été transmis au VPS.

SHA-256 de la trace privée : `8ac70799c687dc814328901acfa4b853bf34eddc0948c7898581278ed3c75c9a`.

**État final : essai ponctuel terminé, candidat non activé pour le comptage officiel.** Le maintien des observations faibles fonctionne dans les cas contrôlés, mais aucun passage réel supplémentaire n'a été récupéré dans ces lots. Il n'existe pas encore de gain de précision chiffrable. Prochaine étape : comparaison sur un lot de passages annotés plus large avant toute activation officielle.

Les preuves privées sont conservées dans `.codex-staging/weak-shadow-20260925-01` sur le Pi et `AppData/Local/SenseGate/Backups/weak-shadow-20260925-01` sur le PC ; elles ne sont pas dans Git.

## Fichiers

- `tracking/low_score_counter.py` : candidat sans accès disque/réseau.
- `tracking/low_score_replay.py` : comparaison hors ligne sur données privées.
- `tracking/low_score_shadow.py` : comparaison en mémoire, avec contrôle de parité.
- `tracking/shadow-enabled.example.json` : activation explicite de la comparaison dans le dossier temporaire de capture uniquement.
- `tracking/test_low_score_counter.py` et `tracking/test_low_score_shadow.py` : tests ciblés.

L'option de capture conserve également des images brutes à au plus 5 images/s **même sans détection**, pour ne pas limiter le contrôle visuel aux personnes déjà détectées. Stockage et durée bornés ; médias privés hors Git.
