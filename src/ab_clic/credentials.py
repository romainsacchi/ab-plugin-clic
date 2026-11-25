"""Remember the CLIC token in the operating system's credential store."""

import keyring
from keyring.backends.chainer import ChainerBackend
from keyring.errors import NoKeyringError

SERVICE = "Activity Browser CLIC"
ACCOUNT = "clic.psi.ch"
SYSTEM_BACKENDS = {
    "keyring.backends.macOS",
    "keyring.backends.Windows",
    "keyring.backends.SecretService",
    "keyring.backends.kwallet",
    "keyring.backends.libsecret",
}


def _system_keyring():
    backend = keyring.get_keyring()
    candidates = backend.backends if isinstance(backend, ChainerBackend) else [backend]
    for candidate in candidates:
        if type(candidate).__module__ in SYSTEM_BACKENDS:
            return candidate
    raise NoKeyringError("No system credential store is available.")


def load_token() -> str:
    return _system_keyring().get_password(SERVICE, ACCOUNT) or ""


def save_token(token: str) -> None:
    _system_keyring().set_password(SERVICE, ACCOUNT, token)


def delete_token() -> None:
    _system_keyring().delete_password(SERVICE, ACCOUNT)
