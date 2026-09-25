"""Authenticated streaming backup envelope. No network access or secret logging."""
import base64
import io
import json
import os
import struct
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b'SGBAK1\n'


class SealedWriter(io.RawIOBase):
    def __init__(self, dest, public_pem):
        self.dest = dest
        key, nonce = os.urandom(32), os.urandom(12)
        public = serialization.load_pem_public_key(public_pem)
        wrapped = public.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        header = json.dumps({'nonce': base64.b64encode(nonce).decode(), 'key': base64.b64encode(wrapped).decode()}, sort_keys=True).encode()
        self.aad = MAGIC + struct.pack('>I', len(header)) + header
        dest.write(self.aad)
        self.encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
        self.encryptor.authenticate_additional_data(self.aad)
        self.finished = False

    def writable(self):
        return True

    def write(self, data):
        if self.finished:
            raise ValueError('envelope already finalized')
        self.dest.write(self.encryptor.update(data))
        return len(data)

    def finish(self):
        if not self.finished:
            self.dest.write(self.encryptor.finalize())
            self.dest.write(self.encryptor.tag)
            self.finished = True


def decrypt_file(source, dest, private):
    """Caller must discard plaintext if authentication fails; never extract early."""
    if source.read(len(MAGIC)) != MAGIC:
        raise ValueError('invalid envelope')
    length_bytes = source.read(4)
    length = struct.unpack('>I', length_bytes)[0]
    if length > 16384:
        raise ValueError('oversized header')
    raw = source.read(length)
    header = json.loads(raw)
    key = private.decrypt(base64.b64decode(header['key']), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    start = source.tell()
    source.seek(-16, 2)
    end = source.tell()
    tag = source.read(16)
    source.seek(start)
    decryptor = Cipher(algorithms.AES(key), modes.GCM(base64.b64decode(header['nonce']), tag)).decryptor()
    decryptor.authenticate_additional_data(MAGIC + length_bytes + raw)
    remaining = end - start
    while remaining:
        chunk = source.read(min(1024 * 1024, remaining))
        if not chunk:
            raise ValueError('truncated ciphertext')
        dest.write(decryptor.update(chunk))
        remaining -= len(chunk)
    dest.write(decryptor.finalize())
