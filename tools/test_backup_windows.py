import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import backup_windows
from backup_crypto import SealedWriter


class RestoreSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.raw_key = cls.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        cls.public = cls.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    def setup_files(self, root):
        (root/'recovery-key.dpapi').write_bytes(b'mocked-in-test')
        source = root/'test.sgbak'
        with source.open('wb') as output:
            writer = SealedWriter(output, self.public)
            writer.write(b'private backup fixture')
            writer.finish()
        return source, root/'restored.tar.gz'

    def test_does_not_delete_preexisting_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, dest = self.setup_files(root)
            partial = dest.with_name(dest.name+'.unauthenticated')
            partial.write_bytes(b'belongs to another attempt')
            with patch.object(backup_windows, 'dpapi', return_value=self.raw_key):
                with self.assertRaises(FileExistsError):
                    backup_windows.decrypt(root, source, dest)
            self.assertEqual(partial.read_bytes(), b'belongs to another attempt')

    def test_does_not_overwrite_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, dest = self.setup_files(root)
            dest.write_bytes(b'existing')
            with self.assertRaises(ValueError):
                backup_windows.decrypt(root, source, dest)
            self.assertEqual(dest.read_bytes(), b'existing')

    def test_success_only_publishes_authenticated_plaintext(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, dest = self.setup_files(root)
            with patch.object(backup_windows, 'dpapi', return_value=self.raw_key), patch('sys.stdout', new_callable=io.StringIO):
                backup_windows.decrypt(root, source, dest)
            self.assertEqual(dest.read_bytes(), b'private backup fixture')
            self.assertFalse(dest.with_name(dest.name+'.unauthenticated').exists())


if __name__ == '__main__':
    unittest.main()
