import io
import unittest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from backup_crypto import SealedWriter, decrypt_file


class EnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.pem = cls.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    def sealed(self, raw):
        target = io.BytesIO()
        writer = SealedWriter(target, self.pem)
        for offset in range(0, len(raw), 313):
            writer.write(raw[offset:offset+313])
        writer.finish()
        writer.finish()
        return target.getvalue()

    def test_roundtrip(self):
        raw = b'private configuration\x00' * 10000
        result = io.BytesIO()
        decrypt_file(io.BytesIO(self.sealed(raw)), result, self.key)
        self.assertEqual(raw, result.getvalue())

    def test_empty(self):
        result = io.BytesIO()
        decrypt_file(io.BytesIO(self.sealed(b'')), result, self.key)
        self.assertEqual(result.getvalue(), b'')

    def test_tamper_is_rejected(self):
        raw = bytearray(self.sealed(b'private' * 1000))
        raw[-25] ^= 1
        with self.assertRaises(InvalidTag):
            decrypt_file(io.BytesIO(raw), io.BytesIO(), self.key)

    def test_truncation_is_rejected(self):
        with self.assertRaises(InvalidTag):
            decrypt_file(io.BytesIO(self.sealed(b'private' * 1000)[:-1]), io.BytesIO(), self.key)

    def test_wrong_key(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with self.assertRaises(ValueError):
            decrypt_file(io.BytesIO(self.sealed(b'private')), io.BytesIO(), other)


if __name__ == '__main__':
    unittest.main()
