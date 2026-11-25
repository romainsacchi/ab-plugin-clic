import unittest
from unittest.mock import Mock, patch

from keyring.errors import NoKeyringError

from ab_clic import credentials


class SystemBackend:
    __module__ = "keyring.backends.macOS"

    def __init__(self):
        self.get_password = Mock(return_value="synthetic-token")
        self.set_password = Mock()
        self.delete_password = Mock()


class CredentialTests(unittest.TestCase):
    @patch("ab_clic.credentials.keyring.get_keyring")
    def test_token_uses_the_system_credential_store(self, get_keyring):
        backend = SystemBackend()
        get_keyring.return_value = backend
        key = (credentials.SERVICE, credentials.ACCOUNT)
        credentials.save_token("synthetic-token")
        self.assertEqual(credentials.load_token(), "synthetic-token")
        credentials.delete_token()
        backend.set_password.assert_called_once_with(*key, "synthetic-token")
        backend.get_password.assert_called_once_with(*key)
        backend.delete_password.assert_called_once_with(*key)

    @patch("ab_clic.credentials.keyring.get_keyring")
    def test_token_is_never_saved_to_an_unrecognized_backend(self, get_keyring):
        with self.assertRaises(NoKeyringError):
            credentials.save_token("synthetic-token")
        get_keyring.return_value.set_password.assert_not_called()
