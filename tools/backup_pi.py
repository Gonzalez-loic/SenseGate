"""Read-only application/model snapshot; writes ONLY into the chosen backup directory.

Not a disk image. Root-only OS/network credentials are deliberately out of scope.
No service restart, no upload, no API calls. Run as the application's owner.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time
from backup_crypto import SealedWriter

ROOT = Path('/home/loic/people_counter')


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def command(args):
    p = subprocess.run(args, capture_output=True, timeout=60)
    return p.stdout + b'\n' + p.stderr


def backup(public_key, destination):
    os.umask(0o077)
    destination = destination.resolve()
    assert not destination.is_relative_to(ROOT), 'backup must be outside source tree'
    destination.mkdir(parents=True, exist_ok=False)
    app_files = sorted((ROOT / 'app').glob('*.py'))
    critical = app_files + [ROOT / 'config/device_config.env']
    before = {str(p): sha(p) for p in critical}
    started = time.time()
    manifest = {'format': 1, 'kind': 'application-reconstruction-not-disk-image', 'started_at': started,
                'critical_sha256': before, 'files': [], 'volatile_omissions': [],
                'excluded': ['OS disk image', 'root-only SSH/Wi-Fi/Tailscale credentials', 'Linux filesystem outside listed roots']}
    target = destination / 'pi-application.sgbak'
    with target.open('xb') as sink:
        sealed = SealedWriter(sink, public_key.read_bytes())
        with tarfile.open(fileobj=sealed, mode='w|gz', compresslevel=1) as archive:
            def add_bytes(name, data):
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(data), 0o600, time.time()
                archive.addfile(info, io.BytesIO(data))

            roots = [ROOT, Path('/usr/share/hailo-models')]
            paths = []
            for root in roots:
                paths.extend([root] + sorted(root.rglob('*')))
            paths += sorted(Path('/etc/systemd/system').glob('people_counter*'))
            paths += sorted(Path('/etc/systemd/system').glob('sensegate*'))
            for p in list(paths):
                if p.is_dir() and not p.is_symlink() and str(p).startswith('/etc/'):
                    paths.extend(sorted(p.rglob('*')))
            paths += [Path(p) for p in ['/etc/os-release', '/etc/fstab', '/boot/firmware/config.txt', '/boot/firmware/cmdline.txt']]
            for p in paths:
                name = 'filesystem/' + str(p).lstrip('/')
                try:
                    archive.add(p, arcname=name, recursive=False)
                    manifest['files'].append(name)
                except (FileNotFoundError, PermissionError) as exc:
                    if p in critical or not str(p).startswith(str(ROOT / 'data')):
                        raise
                    manifest['volatile_omissions'].append({'path': str(p), 'reason': type(exc).__name__})
            inventory = {
                'dpkg.txt': ['dpkg-query', '-W'],
                'pip.txt': ['python3', '-m', 'pip', 'freeze'],
                'os.txt': ['uname', '-a'],
                'filesystems.txt': ['findmnt', '--json'],
                'services.txt': ['systemctl', 'list-unit-files', 'people_counter*', 'sensegate*', '--no-pager'],
            }
            for name, args in inventory.items():
                add_bytes('inventory/' + name, command(args))
            after = {str(p): sha(p) for p in critical}
            if before != after:
                raise RuntimeError('application changed during backup; not valid for rollback')
            manifest['completed_at'] = time.time()
            add_bytes('manifest.json', json.dumps(manifest, indent=2).encode())
        sealed.finish()
    proof = {'kind': manifest['kind'], 'started_at': started, 'completed_at': time.time(),
             'encrypted_archive': target.name, 'sha256': sha(target), 'bytes': target.stat().st_size,
             'critical_files_stable': True, 'entries': len(manifest['files']),
             'volatile_omissions': len(manifest['volatile_omissions']), 'services_restarted': False}
    (destination / 'proof.json').write_text(json.dumps(proof, indent=2))
    print(json.dumps(proof), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--public-key', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    backup(args.public_key, args.destination)
