# Sauvegarde et restauration du Pi

## Où se trouve la sauvegarde

- Pi : `/home/loic/.sensegate-backups/20260925-before-benchmark/pi-application.sgbak`.
- PC : `C:\Users\loicg\AppData\Local\SenseGate\Backups\20260925-before-benchmark\pi-application.sgbak`.
- Preuves : `proof.json` et `restore-verification.json` dans le dossier PC ci-dessus.
- Clé privée protégée : `C:\Users\loicg\AppData\Local\SenseGate\Backups\recovery-key.dpapi`.

Les dossiers PC sont hors du dépôt et hors OneDrive. Le chiffrement de l'archive utilise AES-256-GCM, sa clé aléatoire étant enveloppée par RSA-OAEP/SHA-256. La clé privée est protégée par Windows DPAPI pour le compte Windows actuel.

**Conserver le profil Windows et le fichier `.dpapi` : l'archive seule ne suffit pas.** Cette protection couvre la panne du Pi, pas la perte simultanée du Pi et de ce PC/profil Windows. Une clé de secours portable chiffrée par un mot de passe choisi par l'utilisateur reste à prévoir avant une migration/réinstallation de Windows. Ne pas mettre de clé privée en clair dans Git.

## Contenu et limites

L'archive contient le répertoire applicatif complet du Pi, ses données présentes au moment de la capture, les modèles de `/usr/share/hailo-models`, les unités systemd lisibles concernées, des fichiers de configuration de démarrage lisibles et l'inventaire des paquets/versions Python. La capture a été effectuée à chaud ; les sources et la configuration critique ont été contrôlées stables avant/après. Les journaux et vidéos en cours d'écriture ne constituent pas une image disque cohérente à un instant unique.

Ce n'est pas une image de la carte SD. Les fichiers système root non lisibles, les secrets réseau/SSH/Tailscale administrateur, le chargeur complet et les binaires de tous les paquets OS ne sont pas sauvegardés ici. La disponibilité future des versions de paquets inventoriées n'est pas garantie. Une réinstallation OS et une reconfiguration réseau peuvent être nécessaires après une panne totale.

Le Git contient seulement les sources et outils. **Un `git clone` ne restaure donc ni les secrets ni les compteurs.**

## Vérifier ou déchiffrer sur le PC d'origine

Depuis la racine de ce dépôt, avec Python et `cryptography` :

```powershell
python tools/backup_windows.py verify --root C:/Users/loicg/AppData/Local/SenseGate/Backups --archive C:/Users/loicg/AppData/Local/SenseGate/Backups/20260925-before-benchmark/pi-application.sgbak --proof C:/Users/loicg/AppData/Local/SenseGate/Backups/20260925-before-benchmark/proof.json
```

Pour préparer une reconstruction, choisir un nouveau fichier de sortie **hors Git et hors synchronisation cloud** :

```powershell
python tools/backup_windows.py decrypt --root C:/Users/loicg/AppData/Local/SenseGate/Backups --archive C:/Users/loicg/AppData/Local/SenseGate/Backups/20260925-before-benchmark/pi-application.sgbak --destination C:/Users/loicg/AppData/Local/SenseGate/Backups/restoration-private.tar.gz
```

Le déchiffrement vérifie l'authentification avant de rendre le fichier final disponible, et refuse d'écraser une destination existante. L'archive déchiffrée contient des secrets : la garder privée et supprimer cette copie temporaire lorsqu'elle n'est plus nécessaire.

## Retour arrière logiciel / panne complète

1. Pour un simple défaut du nouveau code, restaurer uniquement les sources sauvegardées concernées et conserver les données et compteurs récents. Vérifier leurs SHA-256 avant un redémarrage contrôlé.
2. En cas de panne OS, réinstaller un Raspberry Pi OS compatible sur un support sain, rétablir le réseau puis récupérer l'archive privée par SSH.
3. Extraire d'abord dans un **nouveau dossier de restauration**, jamais directement à la racine. Les fichiers applicatifs sont sous `filesystem/home/loic/people_counter/`, les modèles sous `filesystem/usr/share/hailo-models/`, les unités sous `filesystem/etc/systemd/system/`, les inventaires sous `inventory/`.
4. Réinstaller les dépendances compatibles, restaurer les propriétaires et autorisations nécessaires, puis vérifier le moteur local avant d'activer la synchronisation.
5. **Ne pas réinjecter aveuglément d'anciens compteurs dans le VPS** : comparer la date de sauvegarde aux dernières données serveur et décider de la reprise sans créer de faux événements ou doublons.

Le déchiffrement, la lecture intégrale et une extraction/compilation isolée du code ont été testés. Un démarrage après destruction/recréation du système n'a pas été testé. Aucun script de cette campagne ne réinstalle automatiquement le système ni ne réinjecte des compteurs historiques.
