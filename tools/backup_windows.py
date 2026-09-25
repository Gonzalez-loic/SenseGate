"""Windows-only recovery key store and isolated backup verification.

The private RSA key is protected with DPAPI for the current Windows user.
Never prints key bytes. Keep this directory outside Git and outside OneDrive.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import tarfile
import tempfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from backup_crypto import decrypt_file


class Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data, decrypt=False):
    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, result = Blob(len(data), buf), Blob()
    api = ctypes.windll.crypt32
    name = 'CryptUnprotectData' if decrypt else 'CryptProtectData'
    fn = getattr(api, name)
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def init(root):
    root.mkdir(parents=True, exist_ok=True)
    private_path, public_path = root / 'recovery-key.dpapi', root / 'backup-public.pem'
    if private_path.exists():
        private = serialization.load_pem_private_key(dpapi(private_path.read_bytes(), True), password=None)
    else:
        private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        with private_path.open('xb') as output:
            output.write(dpapi(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())))
    public_path.write_bytes(private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    print(json.dumps({'public_key': str(public_path), 'private_key_protection': 'Windows DPAPI current user; NOT portable to a new Windows profile'}))


def decrypt(root, source, destination):
    if destination.exists():
        raise ValueError('refusing to overwrite an existing restoration archive')
    destination.parent.mkdir(parents=True, exist_ok=True)
    private = serialization.load_pem_private_key(dpapi((root / 'recovery-key.dpapi').read_bytes(), True), password=None)
    pending = destination.with_name(destination.name + '.unauthenticated')
    created = False
    try:
        with pending.open('xb') as out:
            created = True
            with source.open('rb') as inp:
                decrypt_file(inp, out, private)
        os.replace(pending, destination)
    finally:
        if created and pending.exists():
            pending.unlink()
    print(json.dumps({'authenticated_archive': str(destination), 'warning': 'contains secrets; keep outside Git and cloud folders'}))


def verify(root, source, proof_path):
    private = serialization.load_pem_private_key(dpapi((root / 'recovery-key.dpapi').read_bytes(), True), password=None)
    proof = json.loads(proof_path.read_text())
    with source.open('rb') as inp:
        assert hashlib.file_digest(inp, 'sha256').hexdigest() == proof['sha256']
    with tempfile.TemporaryDirectory(prefix='verify-', dir=root) as tmp:
        plain = Path(tmp) / 'authenticated.tar.gz'
        try:
            with source.open('rb') as inp, plain.open('xb') as out:
                decrypt_file(inp, out, private)
            verified, extracted = 0, 0
            with tarfile.open(plain, 'r:gz') as archive:
                manifest = json.load(archive.extractfile('manifest.json'))
                for name, expected in manifest['critical_sha256'].items():
                    member = 'filesystem/' + name.lstrip('/')
                    raw = archive.extractfile(member).read()
                    assert hashlib.sha256(raw).hexdigest() == expected, name
                    verified += 1
                    if '/app/' in name and name.endswith('.py'):
                        # Extract ONLY validated code for an isolated syntax restoration test.
                        dest = Path(tmp) / 'restored-app' / Path(name).name
                        dest.parent.mkdir(exist_ok=True)
                        dest.write_bytes(raw)
                        compile(raw, name, 'exec')
                        extracted += 1
                model_name = 'filesystem/usr/share/hailo-models/yolov8s_h8l.hef'
                assert archive.getmember(model_name).size > 1000000
                # Iterate/read every regular file: checks gzip truncation and tar accessibility.
                files, total = 0, 0
                for item in archive:
                    if item.isfile():
                        with archive.extractfile(item) as stream:
                            while chunk := stream.read(1024 * 1024):
                                total += len(chunk)
                        files += 1
            result = {'authenticated': True, 'sha256_matches': True, 'critical_files_verified': verified,
                      'restored_python_files_compile': extracted, 'readable_files': files, 'uncompressed_bytes': total,
                      'boot_restore_tested': False, 'live_services_modified': False}
            (source.parent / 'restore-verification.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result))
        finally:
            if plain.exists():
                plain.unlink()  # Only this newly created temporary plaintext, never production.


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['init', 'verify', 'decrypt'])
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--archive', type=Path)
    p.add_argument('--proof', type=Path)
    p.add_argument('--destination', type=Path)
    a = p.parse_args()
    if a.action == 'init':
        init(a.root)
    elif a.action == 'verify':
        verify(a.root, a.archive, a.proof)
    else:
        if a.destination is None:
            p.error('--destination is required for decrypt')
        decrypt(a.root, a.archive, a.destination)
