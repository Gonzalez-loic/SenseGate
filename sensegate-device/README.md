# SenseGate Device

Base Git prête pour Raspberry Pi / Hailo avec :
- comptage entrée/sortie par ligne horizontale ou verticale
- backend Hailo dédié avec fallback propre si non disponible
- API locale `/api/stats`, `/api/health`, `/snapshot.jpg`, `/stream.mjpg`, `/api/reset`
- file locale SQLite pour stats, événements et synchro serveur résiliente
- watchdog / heartbeats / mode multi-portes clonable
- config unique par porte dans `config.yaml`

## Important
Cette base est pensée pour la prod, mais le taux de réussite réel dépend aussi de :
- hauteur et angle caméra
- largeur de porte et position de ligne
- éclairage et contre-jour
- seuils de confiance et taille mini de personne
- calibration sur site

## Structure
- `app.py` : point d'entrée
- `sensegate_device/services/runtime.py` : orchestration
- `sensegate_device/detectors/hailo_backend.py` : backend Hailo
- `sensegate_device/counting/engine.py` : logique de comptage
- `sensegate_device/storage/db.py` : base locale SQLite
- `deploy/people_counter.service` : service systemd
- `config.example.yaml` : exemple de configuration

## Installation rapide
```bash
cd /home/loic
git clone <ton-repo> sensegate-device
cd sensegate-device
cp config.example.yaml config.yaml
chmod +x install.sh
./install.sh
```

## Lancement manuel
```bash
source .venv/bin/activate
python app.py
```

## Service
```bash
sudo systemctl enable people_counter
sudo systemctl restart people_counter
sudo systemctl status people_counter
```

## Endpoints
- `GET /api/health`
- `GET /api/stats`
- `GET /api/config`
- `GET /snapshot.jpg`
- `GET /stream.mjpg`
- `POST /api/reset`
- `POST /api/reload`

## Tailscale
Le plus simple est de joindre chaque Pi via Tailscale puis d'utiliser l'IP ou le nom Tailscale côté Flutter / serveur.
