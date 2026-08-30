import json
import os
import struct
import sys
import threading
from typing import Optional
import zlib

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import keyring

try:
    from oqs import KeyEncapsulation
    print("oqs library found. OQS key encapsulation will be available.")
except ImportError:
    print("Warning: oqs library not found. OQS key encapsulation will not be available.")
    KeyEncapsulation = None


ENCRYPTOR_TYPE_KEY = "encryptor_type"

# =============================================================================
# Key store
#
# macOS prompts per keychain *item* on first access, so the number of items is
# the number of prompts a user sees on first run. The previous layout stored
# salt, nonce, tag, encryptor type, and 500-hex-char chunks of the private and
# public keys as separate items -- 22 of them for the default Kyber768.
#
# Only the passphrase needs the keychain. Everything else is either non-secret
# (salt, nonce, tag, type, public key) or already ciphertext: the private key
# is encrypted with a passphrase-derived key before it is ever stored. So the
# keychain keeps one item and the rest moves to this sidecar file, which also
# removes the chunking -- that existed only for Windows Credential Manager's
# ~2.5KB blob limit, which does not apply to a file.
# =============================================================================

KEY_STORE_VERSION = 1
_KEY_STORE_FILENAME = "key_store.json"

# {(service_name, app_identifier): dict}. Key material is read once per
# process: load_private_key runs on every encrypt and decrypt, and
# AppInfoCache.store() is on a periodic timer, so without this the keychain and
# disk are hit repeatedly for the whole session.
_key_store_cache: dict = {}
_passphrase_cache: dict = {}
_key_store_lock = threading.Lock()


def service_subdir(root: str, service_name: str) -> str:
    """``<root>/<service_name>`` -- the folder apps sharing a service name share.

    SERVICE_NAME is common to every app in this family, so keying the folder on
    it (and the filenames on app_identifier) puts their key material together
    in one place instead of one directory per app.
    """
    return os.path.join(root, service_name)


def _host_util(method_name: str):
    """Return ``Utils.<method_name>`` if the host application provides it.

    Resolved per call rather than cached so a host can patch or install the
    method later, and so tests can substitute one.
    """
    try:
        from utils.utils import Utils
        return getattr(Utils, method_name)
    except (ImportError, AttributeError):
        return None


def _fallback_user_data_dir() -> str:
    """Platform user-data directory, for hosts without Utils.user_data_dir().

    The data location, not the cache one: XDG defines the cache directory as
    regenerable data, which a private key is not.
    """
    if sys.platform == "win32":
        return os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    return os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )


def _fallback_available_external_drives() -> list:
    """Writable non-system mount points, for hosts without the Utils method."""
    candidates = []
    if sys.platform == "win32":
        for letter in "EFGHIJKLMNOPQRSTUVWXYZ":
            root = f"{letter}:\\"
            if os.path.isdir(root):
                candidates.append(root)
    else:
        user = os.environ.get("USER") or ""
        for root in ("/Volumes", "/media", "/run/media", "/mnt"):
            bases = [os.path.join(root, user), root] if user else [root]
            for base in bases:
                try:
                    entries = sorted(os.listdir(base))
                except OSError:
                    continue
                candidates.extend(
                    os.path.join(base, entry) for entry in entries
                    if os.path.isdir(os.path.join(base, entry))
                )
                break
    return [path for path in candidates if os.access(path, os.W_OK)]


# These two prefer the host's Utils and fall back to the implementations above,
# so the module drops into an application that has no such helpers. The host
# wins when present, which is what lets one app keep the platform conventions
# in a single place, beside Utils._get_external_drive_root, whose platform
# conventions these deliberately match. Port any change to one into the other
# rather than leaving two copies to drift.

def user_data_dir() -> str:
    host = _host_util("user_data_dir")
    return host() if host else _fallback_user_data_dir()


def available_external_drives() -> list:
    host = _host_util("available_external_drives")
    return host() if host else _fallback_available_external_drives()


def key_store_dir(service_name: str) -> str:
    """Directory holding the key store: ``<user data dir>/<service_name>``.

    This decides only the namespace; where the user data directory is per
    platform is user_data_dir()'s business. SD_RUNNER_CACHE_DIR still wins, so a
    test or a packaged install can redirect the whole thing.
    """
    override = os.environ.get("SD_RUNNER_CACHE_DIR")
    return service_subdir(override or user_data_dir(), service_name)


# No same-drive backup copies are kept. Extra copies beside the original guard
# against corruption, which os.replace() already makes unlikely for a file
# written this rarely -- they do nothing about the failure that actually loses
# an irreplaceable key, which is the drive going. Off-drive backup is
# export_key_material(..., output_path=<somewhere else>), which the caller
# chooses because only they know where "somewhere else" is.


def key_store_path(service_name: str, app_identifier: str) -> str:
    """Key store path for one service/app pair.

    The service names the shared folder; the app names the file, so several
    apps -- and the legacy identifiers of one app -- sit side by side without
    reading each other's material.
    """
    name = namespaced_key(app_identifier, _KEY_STORE_FILENAME)
    return os.path.join(key_store_dir(service_name), name)


def _load_key_store_file(path: str) -> Optional[dict]:
    """Parse one key store file, or None when absent/unreadable/malformed."""
    try:
        with open(path, "r", encoding="utf-8") as store:
            data = json.load(store)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Could not read key store at {path}: {e}")
        return None
    if not isinstance(data, dict) or not data.get(ENCRYPTOR_TYPE_KEY):
        print(f"Key store at {path} is malformed")
        return None
    return data


def read_key_store(service_name: str, app_identifier: str) -> Optional[dict]:
    """Return the stored key material, or None when absent/unreadable."""
    cache_key = (service_name, app_identifier)
    with _key_store_lock:
        if cache_key in _key_store_cache:
            return _key_store_cache[cache_key]

    data = _load_key_store_file(key_store_path(service_name, app_identifier))
    if data is None:
        return None

    with _key_store_lock:
        _key_store_cache[cache_key] = data
    return data


#: Off-drive backup after every key store write. A backup nobody remembers to
#: take protects nothing, and the moment a write completes is exactly when the
#: store becomes the only copy. Set False to write nothing automatically.
AUTO_BACKUP_KEY_STORE = True

#: "Nowhere to back up to" is reported once per process, not per write.
_auto_backup_warned: set = set()


def write_key_store(service_name: str, app_identifier: str, data: dict) -> None:
    """Write the key store atomically and refresh the process cache.

    Written through a temp file and os.replace(), so an interrupted write
    leaves the previous store intact rather than a truncated one. An off-drive
    backup follows, best-effort -- see AUTO_BACKUP_KEY_STORE.
    """
    path = key_store_path(service_name, app_identifier)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as store:
        json.dump(data, store)
    os.replace(tmp, path)
    try:
        # Owner-only: this carries the private key's ciphertext. No-op on
        # Windows, where the user profile already restricts access.
        os.chmod(path, 0o600)
    except OSError:
        pass
    with _key_store_lock:
        _key_store_cache[(service_name, app_identifier)] = data
    _auto_backup(service_name, app_identifier)


def _auto_backup(service_name: str, app_identifier: str) -> None:
    """Copy the key store off-drive, never failing the write that triggered it.

    Runs on every write rather than only after migration: a password stored
    later lives in the store too, so a backup taken once at migration would be
    missing it exactly when it mattered.
    """
    if not AUTO_BACKUP_KEY_STORE:
        return
    key = (service_name, app_identifier)
    try:
        path = default_key_backup_path(service_name, app_identifier)
        if not path:
            if key not in _auto_backup_warned:
                _auto_backup_warned.add(key)
                print(
                    f"No external drive found for an automatic key backup. Set "
                    f"{KEY_BACKUP_DIR_ENV_VAR} to a path on another drive; until then "
                    f"the key store is the only copy of the private key."
                )
            return
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        export_key_material(service_name, app_identifier, output_path=path)
    except Exception as e:
        # The store itself is written; a failed backup must not undo that.
        print(f"Automatic key backup failed ({e}); the key store was still written.")


def clear_key_store_cache(service_name: str = None, app_identifier: str = None) -> None:
    """Drop cached key material so the next read goes back to disk/keychain."""
    with _key_store_lock:
        if service_name is None:
            _key_store_cache.clear()
            _passphrase_cache.clear()
            return
        _key_store_cache.pop((service_name, app_identifier), None)
        _passphrase_cache.pop((service_name, app_identifier), None)


def delete_key_store(service_name: str, app_identifier: str) -> None:
    try:
        os.remove(key_store_path(service_name, app_identifier))
    except OSError:
        pass
    clear_key_store_cache(service_name, app_identifier)


class KeyMaterialError(Exception):
    """Prior key material exists but could not be loaded.

    Raised rather than letting a new keypair be generated: new keys leave every
    file encrypted under the old ones permanently undecryptable, and generating
    them silently would destroy the evidence needed to recover.
    """


def peek_passphrase(service_name: str, app_identifier: str) -> Optional[str]:
    """Read the passphrase without creating one.

    PassphraseManager.get_passphrase() generates and stores a passphrase when
    none is found, so it cannot be used to ask whether keys ever existed.
    """
    env_var = f"{service_name.upper()}_PASSPHRASE"
    if env_var in os.environ:
        return os.environ[env_var]
    # Cache first: this is on the auto-backup path, and an uncached read here
    # would put a keychain access -- a macOS prompt -- behind every key store
    # write, undoing the one-item budget this module exists for.
    with _key_store_lock:
        cached = _passphrase_cache.get((service_name, app_identifier))
    if cached:
        return cached
    try:
        return keyring.get_password(
            service_name, namespaced_key(app_identifier, "passphrase")
        )
    except Exception:
        return None


def has_prior_key_material(service_name: str, app_identifier: str) -> bool:
    """Whether this service/app ever had keys generated for it.

    Any of: a key store, a pre-consolidation salt item, or a passphrase. The
    passphrase is the durable tell -- it is written once when keys are first
    generated and is not touched by migration.
    """
    if read_key_store(service_name, app_identifier) is not None:
        return True
    try:
        if keyring.get_password(service_name, namespaced_key(app_identifier, "salt")):
            return True
    except Exception:
        pass
    return bool(peek_passphrase(service_name, app_identifier))


#: Explicit destination for key backups. Set this to a path on another drive
#: and default_key_backup_path() will use it instead of guessing.
KEY_BACKUP_DIR_ENV_VAR = "SD_RUNNER_KEY_BACKUP_DIR"


def default_key_backup_path(service_name: str, app_identifier: str) -> Optional[str]:
    """Where an off-drive key backup should go, or None if nowhere is available.

    KEY_BACKUP_DIR_ENV_VAR wins; otherwise the first writable external drive.
    Returns None rather than falling back to the system drive -- a "backup"
    beside the original does not survive the failure it exists for.
    """
    explicit = os.environ.get(KEY_BACKUP_DIR_ENV_VAR)
    root = explicit or next(iter(available_external_drives()), None)
    if not root:
        return None
    # Same shape as the key store: a folder per service, a file per app, so one
    # backup drive holds every app in the family together.
    name = namespaced_key(app_identifier, "key_backup.json")
    return os.path.join(service_subdir(root, service_name), name)


def backup_key_material(service_name: str, app_identifier: str) -> Optional[str]:
    """Write a key backup to the default off-drive location.

    Returns the path written, or None when no external destination is
    available -- callers should report that rather than treat it as done.
    """
    path = default_key_backup_path(service_name, app_identifier)
    if not path:
        print(
            f"No external drive found for a key backup. Set {KEY_BACKUP_DIR_ENV_VAR} "
            f"to a path on another drive, or call export_key_material() with one."
        )
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    export_key_material(service_name, app_identifier, output_path=path)
    return path


def print_recovery_material(
    service_name: str, app_identifier: str, store: Optional[dict] = None
) -> None:
    """Dump key material to stdout when migration could not complete.

    The point of printing here rather than only writing a file: the failures
    this runs on are failures to write a file. Whatever is on screen (or in the
    session log) is then the user's copy, and import_key_material() takes it
    back. Includes the passphrase, so the dump is a complete secret.
    """
    material = {
        "service_name": service_name,
        "app_identifier": app_identifier,
        "passphrase": peek_passphrase(service_name, app_identifier),
        "key_store": store if store is not None else read_key_store(service_name, app_identifier),
    }
    print("=" * 72)
    print("KEY MATERIAL RECOVERY DUMP -- migration did not complete.")
    print("The legacy keychain entries have been left in place, so the next run")
    print("will retry. Save the JSON below only if you need to restore manually:")
    print("  import_key_material(json.loads(<the JSON below>))")
    print("It contains the passphrase in the clear -- treat it as a private key.")
    print("=" * 72)
    print(json.dumps(material, indent=2))
    print("=" * 72)


def export_key_material(
    service_name: str,
    app_identifier: str,
    output_path: Optional[str] = None,
) -> dict:
    """Collect everything needed to reconstruct this app's key material.

    The escape hatch for a failed or half-finished migration: it reads whatever
    exists (key store, or the pre-consolidation keychain items) plus the
    passphrase, and returns it. With *output_path* it is also written there;
    otherwise it is printed.

    The result contains the passphrase in the clear -- it is a full backup of
    the secret, so write it somewhere you would keep a private key.
    """
    from_store = read_key_store(service_name, app_identifier)
    material = {
        "service_name": service_name,
        "app_identifier": app_identifier,
        "passphrase": peek_passphrase(service_name, app_identifier),
        "key_store": from_store,
        "legacy_items": None,
    }

    if from_store is None:
        # Fall back to reading the pre-consolidation layout directly, which is
        # the state a partly-completed migration leaves behind.
        legacy = {}
        for key in ("salt", "nonce", "tag", ENCRYPTOR_TYPE_KEY):
            legacy[key] = keyring.get_password(
                service_name, namespaced_key(app_identifier, key)
            )
        for key in ("encrypted_priv", "public_key"):
            data = BaseEncryptor._retrieve_large_data(service_name, app_identifier, key)
            legacy[key] = data.hex() if data else None
        if any(legacy.values()):
            material["legacy_items"] = legacy

    if output_path:
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(material, handle, indent=2)
        try:
            os.chmod(output_path, 0o600)
        except OSError:
            pass
        print(f"Key material written to {output_path} -- contains the passphrase in the clear")
    else:
        print(json.dumps(material, indent=2))
    return material


def import_key_material(material: dict, service_name: str = None, app_identifier: str = None) -> None:
    """Restore key material produced by export_key_material().

    Writes the key store and the passphrase, so a lost or corrupted store can
    be rebuilt from a backup rather than regenerated (which would orphan every
    file encrypted under the old keys).
    """
    service_name = service_name or material.get("service_name")
    app_identifier = app_identifier or material.get("app_identifier")
    if not service_name or not app_identifier:
        raise ValueError("service_name and app_identifier are required to import")

    store = material.get("key_store")
    if store is None and material.get("legacy_items"):
        legacy = material["legacy_items"]
        missing = [k for k, v in legacy.items() if not v and k != ENCRYPTOR_TYPE_KEY]
        if missing:
            raise KeyMaterialError(f"Exported legacy material is incomplete: {missing}")
        store = {
            "version": KEY_STORE_VERSION,
            ENCRYPTOR_TYPE_KEY: legacy.get(ENCRYPTOR_TYPE_KEY) or "standard",
            "salt": legacy["salt"],
            "nonce": legacy["nonce"],
            "tag": legacy["tag"],
            "encrypted_priv": legacy["encrypted_priv"],
            "public_key": legacy["public_key"],
        }
    if store is None:
        raise KeyMaterialError("Nothing to import: no key_store and no legacy_items")

    passphrase = material.get("passphrase")
    if passphrase:
        keyring.set_password(
            service_name, namespaced_key(app_identifier, "passphrase"), passphrase
        )
    write_key_store(service_name, app_identifier, store)
    clear_key_store_cache(service_name, app_identifier)
    print(f"Restored key material for {service_name}:{app_identifier}")


def namespaced_key(*keyparts):
    return f"__".join(str(part) for part in keyparts if part)

def get_key_base(app_identifier, key, encryptor_type=None):
    base = app_identifier if app_identifier else ""
    if encryptor_type:
        base = namespaced_key(base, encryptor_type)
    return namespaced_key(base, key) if key else base

# =============================================================================
# Passphrases and Passwords
# =============================================================================

class PassphraseManager:
    @staticmethod
    def get_passphrase(service_name="MyApp", app_identifier="main_app"):
        """
        Retrieve passphrase from secure storage with platform-specific methods

        Cached for the process: this is now the only keychain read on the
        encrypt/decrypt path, and it would otherwise repeat on every call.
        """
        # 1. Try environment variable first (for containerized environments)
        env_var = f"{service_name.upper()}_PASSPHRASE"
        if env_var in os.environ:
            return os.environ[env_var]

        cache_key = (service_name, app_identifier)
        with _key_store_lock:
            if cache_key in _passphrase_cache:
                return _passphrase_cache[cache_key]

        # 2. Try platform-specific secure storage
        platform_handler = {
            'win32': PassphraseManager._windows_get_passphrase,
            'darwin': PassphraseManager._macos_get_passphrase,
            'linux': PassphraseManager._linux_get_passphrase
        }.get(sys.platform, PassphraseManager._fallback_get_passphrase)

        passphrase = platform_handler(service_name, app_identifier)
        if passphrase:
            with _key_store_lock:
                _passphrase_cache[cache_key] = passphrase
        return passphrase

    @staticmethod
    def _windows_get_passphrase(service_name, app_identifier):
        """Use Windows Credential Manager with ACL protection"""
        # Try to retrieve from Credential Manager
        key = namespaced_key(app_identifier, "passphrase")
        passphrase = keyring.get_password(service_name, key)
        
        if not passphrase:
            # Generate and store new passphrase
            passphrase = os.urandom(32).hex()
            keyring.set_password(service_name, key, passphrase)
            
            # Lock down permissions (Windows specific)
            try:
                import win32security
                import win32cred
                cred = win32cred.CredRead(f"{service_name}/{app_identifier}", 
                                         win32cred.CRED_TYPE_GENERIC, 0)
                sd = win32security.SECURITY_DESCRIPTOR()
                sd.SetSecurityDescriptorOwner(win32security.LookupAccountName(None, os.getlogin())[0], True)
                win32cred.CredWrite(cred, win32cred.CRED_PRESERVE_CREDENTIAL_BLOB)
            except ImportError:
                pass  # Fallback if pywin32 not available
        
        return passphrase

    @staticmethod
    def _macos_get_passphrase(service_name, app_identifier):
        """Use macOS Keychain with Access Control"""
        key = namespaced_key(app_identifier, "passphrase")
        passphrase = keyring.get_password(service_name, key)
        
        if not passphrase:
            passphrase = os.urandom(32).hex()
            keyring.set_password(service_name, key, passphrase)
            
            # Set keychain item ACL (requires PyObjC Foundation/Security)
            try:
                from Foundation import NSBundle
                from Security import kSecAttrAccessible, kSecAttrAccessGroup
                keyring.set_keyring_properties(
                    label=f"{service_name} Passphrase",
                    accessible=kSecAttrAccessible.AccessibleWhenUnlockedThisDeviceOnly,
                    access_group=NSBundle.mainBundle().bundleIdentifier()
                )
            except ImportError:
                pass  # PyObjC Foundation/Security not installed
            except AttributeError:
                pass  # keyring.set_keyring_properties not available
        
        return passphrase

    @staticmethod
    def _linux_get_passphrase(service_name, app_identifier):
        """Use Linux Secret Service with DBus protection"""
        key = namespaced_key(app_identifier, "passphrase")
        passphrase = keyring.get_password(service_name, key)
        
        if not passphrase:
            passphrase = os.urandom(32).hex()
            keyring.set_password(service_name, key, passphrase)
            
            # Lock down keyring permissions
            try:
                import dbus
                bus = dbus.SessionBus()
                service = bus.get_object('org.freedesktop.secrets', '/org/freedesktop/secrets')
                service.Lock([f"/org/freedesktop/secrets/collection/{service_name}"])
            except ImportError:
                pass  # Fallback if dbus not available
        
        return passphrase

    @staticmethod
    def _fallback_get_passphrase(service_name, app_identifier):
        """Fallback method using encrypted file storage"""
        config_path = os.path.expanduser(f"~/.config/{service_name}/{app_identifier}.enc")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        if os.path.exists(config_path):
            # Derive key from system fingerprint
            system_id = PassphraseManager._get_system_fingerprint()
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"fixed_salt",
                iterations=100000,
                backend=default_backend()
            )
            key = kdf.derive(system_id)
            
            # Decrypt passphrase
            with open(config_path, "rb") as f:
                nonce = f.read(12)
                tag = f.read(16)
                ciphertext = f.read()
            
            cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag), default_backend())
            decryptor = cipher.decryptor()
            return decryptor.update(ciphertext) + decryptor.finalize()
        else:
            # Generate and store new passphrase
            passphrase = os.urandom(32).hex()
            system_id = PassphraseManager._get_system_fingerprint()
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"fixed_salt",
                iterations=100000,
                backend=default_backend()
            )
            key = kdf.derive(system_id)
            
            nonce = os.urandom(12)
            cipher = Cipher(algorithms.AES(key), modes.GCM(nonce), default_backend())
            encryptor = cipher.encryptor()
            ciphertext = encryptor.update(passphrase.encode()) + encryptor.finalize()
            
            with open(config_path, "wb") as f:
                f.write(nonce)
                f.write(encryptor.tag)
                f.write(ciphertext)
            
            os.chmod(config_path, 0o600)
            return passphrase

    @staticmethod
    def _get_system_fingerprint():
        """Create system-specific fingerprint"""
        import platform
        import hashlib
        import uuid
        
        fingerprint = hashlib.sha256()
        fingerprint.update(platform.node().encode())  # Hostname
        fingerprint.update(platform.machine().encode())  # Architecture
        fingerprint.update(platform.processor().encode())  # CPU
        fingerprint.update(uuid.getnode().to_bytes(6, 'big'))  # MAC address
        
        try:
            with open("/etc/machine-id", "rb") as f:
                fingerprint.update(f.read())
        except FileNotFoundError:
            pass
        
        return fingerprint.digest()


class PasswordManager:
    """Stored passwords live in the key store, not the keychain.

    They are ciphertext -- encrypt_password() KEM-encrypts them against the
    public key -- so they need the keychain no more than the private key's
    ciphertext does. Chunked into keychain items they cost about six more
    macOS prompts, and is_security_configured() reads them at startup.
    """

    STORE_SECTION = "passwords"

    @staticmethod
    def store_password(
        service_name: str,
        app_identifier: str,
        password_id: str,
        encrypted_password: bytes
    ):
        """Store an encrypted password in the key store."""
        store = read_key_store(service_name, app_identifier)
        if store is None:
            # No keys yet is a caller error: encrypt_password() needs the
            # public key, so the store exists by the time this runs.
            raise ValueError("Cannot store a password before keys are generated")
        updated = dict(store)
        passwords = dict(updated.get(PasswordManager.STORE_SECTION, {}))
        passwords[password_id] = encrypted_password.hex()
        updated[PasswordManager.STORE_SECTION] = passwords
        write_key_store(service_name, app_identifier, updated)

    @staticmethod
    def retrieve_password(
        service_name: str,
        app_identifier: str,
        password_id: str
    ) -> Optional[bytes]:
        """Retrieve an encrypted password, migrating a legacy chunked one."""
        store = read_key_store(service_name, app_identifier)
        if store is not None:
            stored = store.get(PasswordManager.STORE_SECTION, {}).get(password_id)
            if stored:
                return bytes.fromhex(stored)
        legacy = BaseEncryptor._retrieve_large_data(
            service_name, app_identifier, password_id
        )
        if legacy is not None and store is not None:
            # Fold it in, then drop the chunked items -- same verified-write
            # ordering as the key migration.
            PasswordManager.store_password(
                service_name, app_identifier, password_id, legacy
            )
            if read_key_store(service_name, app_identifier).get(
                    PasswordManager.STORE_SECTION, {}).get(password_id):
                PasswordManager._delete_legacy_password(
                    service_name, app_identifier, password_id
                )
        return legacy

    @staticmethod
    def _delete_legacy_password(
        service_name: str, app_identifier: str, password_id: str
    ) -> None:
        """Remove a pre-consolidation chunked password."""
        key_base = get_key_base(app_identifier, password_id)
        count_key = namespaced_key(key_base, "count")
        count_str = keyring.get_password(service_name, count_key)
        if count_str:
            try:
                for i in range(int(count_str)):
                    BaseEncryptor._delete_key_quietly(
                        service_name, namespaced_key(key_base, i)
                    )
            except ValueError:
                pass
        BaseEncryptor._delete_key_quietly(service_name, count_key)

    @staticmethod
    def delete_password(
        service_name: str,
        app_identifier: str,
        password_id: str
    ):
        """
        Delete stored password from all storage locations
        """
        store = read_key_store(service_name, app_identifier)
        if store is not None and password_id in store.get(
                PasswordManager.STORE_SECTION, {}):
            updated = dict(store)
            passwords = dict(updated[PasswordManager.STORE_SECTION])
            passwords.pop(password_id, None)
            updated[PasswordManager.STORE_SECTION] = passwords
            write_key_store(service_name, app_identifier, updated)
        # Also clear any pre-consolidation chunks still present.
        PasswordManager._delete_legacy_password(
            service_name, app_identifier, password_id
        )


# =============================================================================
# Encryptor classes - Asymmetric
# =============================================================================

class BaseEncryptor:
    SALT_KEY = "salt"
    NONCE_KEY = "nonce"
    TAG_KEY = "tag"
    ENCRYPTED_PRIV_KEY = "encrypted_priv"
    PUBLIC_KEY = "public_key"
    PASSPHRASE_KEY = "passphrase"

    @classmethod
    def _get_key_type(cls):
        """What type of encryptor is this?"""
        raise NotImplementedError("Subclass must implement this method")

    @classmethod
    def encrypt_password(
        cls,
        public_key: bytes,
        password: str
    ) -> bytes:
        """Encrypt a password string to bytes"""
        password_bytes = password.encode('utf-8')
        encapsulated_key, aes_key = cls.encapsulate_secret(public_key)
        nonce = os.urandom(12)
        cipher = Cipher(algorithms.AES(aes_key), modes.GCM(nonce), default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(password_bytes) + encryptor.finalize()
        return struct.pack('>I', len(encapsulated_key)) + encapsulated_key + nonce + encryptor.tag + ciphertext
    
    @classmethod
    def decrypt_password(
        cls,
        private_key: bytes,
        encrypted_password: bytes
    ) -> str:
        """Decrypt bytes back to password string"""
        key_len = struct.unpack('>I', encrypted_password[:4])[0]
        index = 4
        encapsulated_key = encrypted_password[index:index+key_len]
        index += key_len
        nonce = encrypted_password[index:index+12]
        index += 12
        tag = encrypted_password[index:index+16]
        index += 16
        ciphertext = encrypted_password[index:]
        
        aes_key = cls.decapsulate_secret(private_key, encapsulated_key)
        cipher = Cipher(
            algorithms.AES(aes_key),
            modes.GCM(nonce, tag),
            default_backend()
        )
        decryptor = cipher.decryptor()
        password_bytes = decryptor.update(ciphertext) + decryptor.finalize()
        return password_bytes.decode('utf-8')
    
    @classmethod
    def generate_keypair(cls) -> tuple[bytes, bytes]:
        """Generate key pair"""
        raise NotImplementedError("Subclass must implement this method")

    @classmethod
    def encapsulate_secret(
        cls,
        public_key: bytes
    ) -> tuple[bytes, bytes]:
        """Encapsulate secret"""
        raise NotImplementedError("Subclass must implement this method")
    
    @classmethod
    def decapsulate_secret(
        cls,
        private_key: bytes,
        ciphertext: bytes
    ) -> bytes:
        """Decapsulate secret"""
        raise NotImplementedError("Subclass must implement this method")
    
    @classmethod
    def generate_and_store_keys(
        cls,
        service_name: str,
        app_identifier: str,
        force_new: bool = False,
    ) -> bytes:
        """Generate and store keys"""
        try:
            store = cls._ensure_key_store(service_name, app_identifier)
        except KeyMaterialError:
            if not force_new:
                raise
            store = None  # force_new is the deliberate "discard what is there"
        if store:
            if force_new:
                print(f"{service_name}:{app_identifier} keys already exist. Generating new keys.")
                cls.purge_keys(service_name, app_identifier)
                return cls.generate_and_store_keys(service_name, app_identifier, force_new=False)
            # print("Keys already exist. Using existing configuration.")
            return bytes.fromhex(store[cls.PUBLIC_KEY])

        print(f"Generating new keys for {service_name}:{app_identifier}")

        # Generate new keys
        pub_key, priv_key = cls.generate_keypair()
        salt = os.urandom(16)
        passphrase = PassphraseManager.get_passphrase(service_name, app_identifier)
        storage_key = cls._derive_key(passphrase, salt, 32)
        nonce = os.urandom(12)

        # Encrypt private key
        cipher = Cipher(algorithms.AES(storage_key), modes.GCM(nonce), default_backend())
        encryptor = cipher.encryptor()
        encrypted_priv = encryptor.update(priv_key) + encryptor.finalize()

        # One file rather than 22 keychain items. Only the passphrase, read
        # above, still lives in the keychain.
        write_key_store(service_name, app_identifier, {
            "version": KEY_STORE_VERSION,
            ENCRYPTOR_TYPE_KEY: cls._get_key_type(),
            cls.SALT_KEY: salt.hex(),
            cls.NONCE_KEY: nonce.hex(),
            cls.TAG_KEY: encryptor.tag.hex(),
            cls.ENCRYPTED_PRIV_KEY: encrypted_priv.hex(),
            cls.PUBLIC_KEY: pub_key.hex(),
        })
        return pub_key

    @classmethod
    def load_private_key(
        cls,
        service_name: str,
        app_identifier: str
    ) -> bytes:
        """Load private key"""
        store = cls._ensure_key_store(service_name, app_identifier)
        if not store:
            raise ValueError("Failed to retrieve key components from the key store")
        cls._check_class_valid(service_name, app_identifier, store=store)

        salt = bytes.fromhex(store[cls.SALT_KEY])
        nonce = bytes.fromhex(store[cls.NONCE_KEY])
        tag = bytes.fromhex(store[cls.TAG_KEY])
        encrypted_priv = bytes.fromhex(store[cls.ENCRYPTED_PRIV_KEY])

        passphrase = PassphraseManager.get_passphrase(service_name, app_identifier)
        storage_key = cls._derive_key(passphrase, salt, 32)
        
        cipher = Cipher(
            algorithms.AES(storage_key),
            modes.GCM(nonce, tag),
            default_backend()
        )
        decryptor = cipher.decryptor()
        return decryptor.update(encrypted_priv) + decryptor.finalize()

    @classmethod
    def _check_class_valid(cls, service_name, app_identifier, store: Optional[dict] = None):
        # *store* is passed by callers that already hold it, so the type is read
        # once per operation rather than once here and again in
        # _determine_encryptor.
        if store is None:
            store = cls._ensure_key_store(service_name, app_identifier)
        stored_type = store.get(ENCRYPTOR_TYPE_KEY) if store else None
        if not stored_type:
            # Nothing stored yet; generate_and_store_keys records the type.
            return
        if stored_type != cls._get_key_type():
            raise ValueError(f"Key type mismatch: Expected {cls._get_key_type()}, found {stored_type}")

    # -------------------------------------------------------------------
    # Key store access and one-time migration off the per-item layout
    # -------------------------------------------------------------------

    @classmethod
    def _ensure_key_store(cls, service_name: str, app_identifier: str) -> Optional[dict]:
        """Return the key store, migrating the old keychain layout if needed.

        Returns None only for a genuinely new install. When material existed
        but cannot be loaded this raises rather than reporting "no keys": every
        caller treats None as permission to start fresh, which for a decrypt is
        a confusing failure and for key generation is destructive.
        """
        store = read_key_store(service_name, app_identifier)
        if store is not None:
            return store
        migrated = cls._migrate_from_keyring_items(service_name, app_identifier)
        if migrated is not None:
            return migrated
        if has_prior_key_material(service_name, app_identifier):
            raise KeyMaterialError(
                f"Key material for {service_name}:{app_identifier} existed but the key "
                f"store at {key_store_path(service_name, app_identifier)} could not be "
                f"read.\nAnything already encrypted needs those keys, so no new ones "
                f"were generated. Restore from a backup with:\n"
                f"  import_key_material(json.load(open('<backup>.json')))\n"
                f"or discard the old keys deliberately with force_new=True."
            )
        return None

    @classmethod
    def _migrate_from_keyring_items(
        cls, service_name: str, app_identifier: str
    ) -> Optional[dict]:
        """Move an existing per-item keychain layout into the key store.

        Reads the old items once (the last time the user sees a prompt per
        item), writes the store, reads it back, and only then deletes the
        originals. The old items are the only copy of the private key, so a
        delete that ran before a verified read-back would make every encrypted
        cache and stored password permanently unrecoverable.

        Returns the migrated store, or None when there is nothing to migrate.
        """
        salt = keyring.get_password(service_name, namespaced_key(app_identifier, cls.SALT_KEY))
        if not salt:
            return None  # no legacy layout either; caller will generate keys

        print(f"Consolidating {service_name}:{app_identifier} keychain items into a key store")
        nonce = keyring.get_password(service_name, namespaced_key(app_identifier, cls.NONCE_KEY))
        tag = keyring.get_password(service_name, namespaced_key(app_identifier, cls.TAG_KEY))
        stored_type = keyring.get_password(
            service_name, namespaced_key(app_identifier, ENCRYPTOR_TYPE_KEY)
        )
        encrypted_priv = cls._retrieve_large_data(
            service_name, app_identifier, cls.ENCRYPTED_PRIV_KEY
        )
        pub_key = cls._retrieve_large_data(service_name, app_identifier, cls.PUBLIC_KEY)

        if not all((nonce, tag, encrypted_priv, pub_key)):
            missing = [
                name for name, value in (
                    (cls.NONCE_KEY, nonce), (cls.TAG_KEY, tag),
                    (cls.ENCRYPTED_PRIV_KEY, encrypted_priv), (cls.PUBLIC_KEY, pub_key),
                ) if not value
            ]
            # Returning None here would let generate_and_store_keys() mint a new
            # keypair over the top of a recoverable install.
            raise KeyMaterialError(
                f"Pre-consolidation keychain entries for {service_name}:{app_identifier} "
                f"are incomplete (missing: {', '.join(missing)}); they have been left in "
                f"place. Run export_key_material({service_name!r}, {app_identifier!r}, "
                f"'backup.json') to capture what remains before changing anything."
            )

        store = {
            "version": KEY_STORE_VERSION,
            ENCRYPTOR_TYPE_KEY: stored_type or cls._get_key_type(),
            cls.SALT_KEY: salt,
            cls.NONCE_KEY: nonce,
            cls.TAG_KEY: tag,
            cls.ENCRYPTED_PRIV_KEY: encrypted_priv.hex(),
            cls.PUBLIC_KEY: pub_key.hex(),
        }
        try:
            write_key_store(service_name, app_identifier, store)
        except Exception as e:
            print(f"Could not write key store, keeping legacy entries: {e}")
            print_recovery_material(service_name, app_identifier, store)
            return store  # usable in memory; migration retries next run

        clear_key_store_cache(service_name, app_identifier)
        verified = read_key_store(service_name, app_identifier)
        if verified != store:
            print("Key store did not read back intact; keeping legacy entries")
            print_recovery_material(service_name, app_identifier, store)
            return store

        cls._delete_legacy_keyring_items(service_name, app_identifier)
        print(f"Consolidated key material for {service_name}:{app_identifier}")
        # write_key_store() has already taken the off-drive backup; report where
        # it went so an unwanted copy is visible and can be removed.
        backup = default_key_backup_path(service_name, app_identifier)
        if backup and os.path.exists(backup):
            print(f"  Off-drive backup written to {backup} "
                  f"(contains the passphrase in the clear)")
        return verified

    @classmethod
    def _delete_legacy_keyring_items(cls, service_name: str, app_identifier: str) -> None:
        """Remove the per-item layout. Never call before a verified store read."""
        for base in (cls.ENCRYPTED_PRIV_KEY, cls.PUBLIC_KEY):
            key_base = get_key_base(app_identifier, base)
            count_key = namespaced_key(key_base, "count")
            count_str = keyring.get_password(service_name, count_key)
            if count_str:
                try:
                    for i in range(int(count_str)):
                        cls._delete_key_quietly(service_name, namespaced_key(key_base, i))
                except ValueError:
                    pass
            cls._delete_key_quietly(service_name, count_key)
        for key in (cls.SALT_KEY, cls.NONCE_KEY, cls.TAG_KEY, ENCRYPTOR_TYPE_KEY):
            cls._delete_key_quietly(service_name, namespaced_key(app_identifier, key))

    @staticmethod
    def _delete_key_quietly(service_name: str, key: str) -> None:
        try:
            keyring.delete_password(service_name, key)
        except Exception:
            pass

    @classmethod
    def verify_keys(cls, public_key: bytes, private_key: bytes):
        encapsulated, shared_secret1 = cls.encapsulate_secret(public_key)
        shared_secret2 = cls.decapsulate_secret(private_key, encapsulated)
        
        if shared_secret1 != shared_secret2:
            raise ValueError("WARNING: Public/private key mismatch!")

    @classmethod
    def migrate_keys(
        cls,
        source_service: str,
        source_app: str,
        target_service: str,
        target_app: str,
        delete_source: bool = False
    ):
        """
        Migrate keys from one service/app combination to another
        - Re-encrypts private key with new passphrase
        - Transfers all key components to new namespace
        - Optionally deletes source keys after migration
        
        NOTE: This does not handle migration from one encryptor type to another.
        """
        # Retrieve source keys. _ensure_key_store migrates the source off the
        # per-item layout first if it is still on it, so this reads one place.
        source_priv = cls.load_private_key(source_service, source_app)
        source_store = cls._ensure_key_store(source_service, source_app)
        if not source_store:
            raise ValueError("No source key material to migrate")
        source_pub = bytes.fromhex(source_store[cls.PUBLIC_KEY])

        # Get target passphrase (will create if doesn't exist)
        target_passphrase = PassphraseManager.get_passphrase(target_service, target_app)

        # Re-encrypt private key with new passphrase
        new_salt = os.urandom(16)
        storage_key = cls._derive_key(target_passphrase, new_salt, 32)
        new_nonce = os.urandom(12)

        cipher = Cipher(algorithms.AES(storage_key), modes.GCM(new_nonce), default_backend())
        encryptor = cipher.encryptor()
        reencrypted_priv = encryptor.update(source_priv) + encryptor.finalize()

        # Store components in target namespace. Passwords are carried across
        # as-is: they are encrypted to the public key, which is unchanged.
        write_key_store(target_service, target_app, {
            "version": KEY_STORE_VERSION,
            ENCRYPTOR_TYPE_KEY: source_store.get(ENCRYPTOR_TYPE_KEY, cls._get_key_type()),
            cls.SALT_KEY: new_salt.hex(),
            cls.NONCE_KEY: new_nonce.hex(),
            cls.TAG_KEY: encryptor.tag.hex(),
            cls.ENCRYPTED_PRIV_KEY: reencrypted_priv.hex(),
            cls.PUBLIC_KEY: source_pub.hex(),
            PasswordManager.STORE_SECTION: dict(
                source_store.get(PasswordManager.STORE_SECTION, {})
            ),
        })

        # Optionally delete source keys, only once the target reads back.
        if delete_source:
            if read_key_store(target_service, target_app) is None:
                print("Target key store unreadable; keeping source key material")
                return
            delete_key_store(source_service, source_app)
            cls._delete_legacy_keyring_items(source_service, source_app)
            cls._delete_key_quietly(
                source_service, namespaced_key(source_app, cls.PASSPHRASE_KEY)
            )
            clear_key_store_cache(source_service, source_app)

    @classmethod
    def encrypt_file(
        cls,
        public_key: bytes,
        input_path: str,
        output_path: str,
        compress: bool = True
    ):
        """Encrypt file with optional compression"""
        with open(input_path, 'rb') as f:
            plaintext = f.read()
        return cls.encrypt_data(plaintext, public_key, output_path, compress)

    @classmethod
    def encrypt_data(
        cls,
        data: bytes,
        public_key: bytes,
        output_path: str,
        compress: bool = True
    ):
        encapsulated_key, aes_key = cls.encapsulate_secret(public_key)
        return cls._do_encrypt(data, output_path, compress, aes_key, encapsulated_key)

    @classmethod
    def decrypt_data_from_file(
        cls,
        private_key: bytes,
        encrypted_file: str
    ) -> bytes:
        encapsulated_key, nonce, tag, compression_flag, ciphertext = cls._read_encrypted_file_attributes(encrypted_file)
        aes_key = cls.decapsulate_secret(private_key, encapsulated_key)
        return cls._do_decrypt(None, aes_key, nonce, tag, compression_flag, ciphertext)

    @classmethod
    def decrypt_to_file(
        cls,
        private_key: bytes,
        input_path: str,
        output_path: str
    ):
        encapsulated_key, nonce, tag, compression_flag, ciphertext = cls._read_encrypted_file_attributes(input_path)
        # Decapsulate the shared secret (AES key)
        aes_key = cls.decapsulate_secret(private_key, encapsulated_key)
        cls._do_decrypt(output_path, aes_key, nonce, tag, compression_flag, ciphertext)

    @classmethod
    def purge_keys(
        cls,
        service_name: str,
        app_identifier: str,
        purge_files: bool = True
    ):
        """
        Purge all keys and associated data from keyring and local files
        - service_name: Keyring service namespace
        - purge_files: Also delete public key file and any encrypted files
        """
        purge_files = cls.purge_files if purge_files else []
        cls._purge_keys(service_name, app_identifier, purge_files)

    @classmethod
    def _derive_key(
        cls,
        passphrase: str,
        salt: bytes,
        length: int = 32
    ) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=length,
            salt=salt,
            iterations=1000000,
            backend=default_backend()
        )
        return kdf.derive(passphrase.encode())
    
    @classmethod
    def _retrieve_large_data(
        cls,
        service_name: str,
        app_identifier: str,
        key: str
    ) -> Optional[bytes]:
        """Retrieve chunked large data written by the pre-consolidation layout.

        Read-only: nothing writes chunks any more. The chunking existed to fit
        Windows Credential Manager's blob limit, and cost one macOS prompt per
        chunk. Kept so an existing install can be migrated into the key store.
        """
        key_base = get_key_base(app_identifier, key)
        count_str = keyring.get_password(service_name, namespaced_key(key_base, "count"))
        if not count_str:
            return None
            
        # print(f"Retrieving {count_str} chunks for {key_base}")
        count = int(count_str)
        chunks = []
        for i in range(count):
            chunk = keyring.get_password(service_name, namespaced_key(key_base, i))
            if not chunk:
                return None
            chunks.append(chunk)
            
        return bytes.fromhex(''.join(chunks))

    @classmethod
    def _do_encrypt(
        cls,
        plaintext: bytes,
        output_path: str,
        compress: bool,
        aes_key: bytes,
        encapsulated_key: bytes
    ):
        """Encrypt file"""
        # Apply compression if requested and beneficial
        if compress:
            compressed = zlib.compress(plaintext, level=zlib.Z_BEST_COMPRESSION)
            # Only use if it actually reduces size
            if len(compressed) < len(plaintext):
                plaintext = compressed
                compression_flag = b'\x01'
            else:
                compression_flag = b'\x00'
        else:
            compression_flag = b'\x00'
        
        # Encrypt content with AES
        nonce = os.urandom(12)
        cipher = Cipher(algorithms.AES(aes_key), modes.GCM(nonce), default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(plaintext) + encryptor.finalize()
        
        # Write to output file
        with open(output_path, 'wb') as f:
            f.write(struct.pack('>I', len(encapsulated_key)))  # Key length
            f.write(encapsulated_key)
            f.write(nonce)
            f.write(encryptor.tag)
            f.write(compression_flag)  # Compression marker
            f.write(ciphertext)        

    @classmethod
    def _read_encrypted_file_attributes(
        cls, input_path: str
    ) -> tuple[bytes, bytes, bytes, bytes, bytes]:
        """Read encrypted file attributes"""
        with open(input_path, 'rb') as f:
            # Read encapsulated key length
            key_len = struct.unpack('>I', f.read(4))[0]
            encapsulated_key = f.read(key_len)
            nonce = f.read(12)
            tag = f.read(16)
            compression_flag = f.read(1)
            ciphertext = f.read()

            return encapsulated_key, nonce, tag, compression_flag, ciphertext

    @classmethod
    def _do_decrypt(
        cls,
        output_path: str,
        aes_key: bytes,
        nonce: bytes,
        tag: bytes,
        compression_flag: bytes,
        ciphertext: bytes
    ) -> Optional[bytes]:
        """Decrypt file"""
        # Decrypt content
        cipher = Cipher(
            algorithms.AES(aes_key),
            modes.GCM(nonce, tag),
            default_backend()
        )
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        
        # Decompress if needed
        if compression_flag == b'\x01':
            try:
                plaintext = zlib.decompress(plaintext)
            except zlib.error:
                print("Warning: Decompression failed. Saving as-is.")
        
        if output_path:
            with open(output_path, 'wb') as f:
                f.write(plaintext)
        else:
            return plaintext

    @classmethod
    def _purge_keys(
        cls,
        service_name: str,
        app_identifier: str,
        purge_files: list[str] = []
    ):
        """
        Purge all keys and associated data from keyring and local files
        - service_name: Keyring service namespace
        - app_identifier: Keyring app identifier
        - purge_files: Also delete public key file and any encrypted files
        """
        # Delete the key store, plus any pre-consolidation keychain items that
        # a partial migration may have left behind.
        delete_key_store(service_name, app_identifier)
        cls._delete_legacy_keyring_items(service_name, app_identifier)

        # Delete public key file if exists
        if purge_files:
            for purge_file in purge_files:
                if os.path.exists(purge_file):
                    try:
                        os.remove(purge_file)
                        print(f"Deleted file: {purge_file}")
                    except Exception as e:
                        print(f"Error deleting {purge_file}: {str(e)}")
            
            # Optional: Add patterns for encrypted files to delete
            # Example: 
            # for purge_file in glob.glob("*.bin"):
            #    try:
            #        os.remove(purge_file)
            #    except Exception:
            #        pass
        
        # Add passphrase deletion
        try:
            keyring.delete_password(service_name, namespaced_key(app_identifier, cls.PASSPHRASE_KEY))
        except Exception:
            pass

        print("All keys and associated data have been purged")


class PersonalQuantumEncryptor(BaseEncryptor):
    KEY_TYPE = "quantum"
    KYBER_ALG = "Kyber768"
    purge_files = ["quantum_pub.key"]

    @classmethod
    def _get_key_type(cls):
        """What type of encryptor is this?"""
        return cls.KEY_TYPE

    @classmethod
    def generate_keypair(cls):
        """Generate Kyber key pair using oqs"""
        kem = KeyEncapsulation(PersonalQuantumEncryptor.KYBER_ALG)
        public_key = kem.generate_keypair()
        private_key = kem.export_secret_key()
        kem.free()  # Free resources
        return public_key, private_key

    @classmethod
    def encapsulate_secret(
        cls,
        public_key: bytes
    ) -> tuple[bytes, bytes]:
        """Generate a shared secret and its encapsulation using Kyber"""
        kem = KeyEncapsulation(cls.KYBER_ALG)
        ciphertext, shared_secret = kem.encap_secret(public_key)
        kem.free()
        return ciphertext, shared_secret

    @classmethod
    def decapsulate_secret(
        cls,
        private_key: bytes,
        ciphertext: bytes
    ) -> bytes:
        """Decapsulate the shared secret using Kyber"""
        kem = KeyEncapsulation(cls.KYBER_ALG, private_key)
        shared_secret = kem.decap_secret(ciphertext)
        kem.free()
        return shared_secret




class PersonalStandardEncryptor(BaseEncryptor):
    KEY_TYPE = "standard"
    CURVE = ec.SECP384R1()
    HKDF_INFO = b'PersonalStandardEncryptor'
    purge_files = ["standard_pub.key"]

    @classmethod
    def _get_key_type(cls):
        """What type of encryptor is this?"""
        return cls.KEY_TYPE
    
    @classmethod
    def generate_keypair(cls):
        """Generate ECDH key pair using standard curve"""
        private_key = ec.generate_private_key(cls.CURVE, default_backend())
        public_key = private_key.public_key()
        
        pub_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        priv_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        return pub_bytes, priv_bytes

    @classmethod
    def encapsulate_secret(
        cls,
        public_key: bytes
    ) -> tuple[bytes, bytes]:
        """Generate shared secret using ECDH with HKDF derivation"""
        recipient_public_key = serialization.load_der_public_key(
            public_key,
            backend=default_backend()
        )
        ephemeral_private_key = ec.generate_private_key(
            cls.CURVE,
            default_backend()
        )
        ephemeral_public_key = ephemeral_private_key.public_key()
        
        shared_secret = ephemeral_private_key.exchange(
            ec.ECDH(), 
            recipient_public_key
        )
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=cls.HKDF_INFO,
            backend=default_backend()
        )
        aes_key = hkdf.derive(shared_secret)
        
        ephemeral_pub_bytes = ephemeral_public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return ephemeral_pub_bytes, aes_key

    @classmethod
    def decapsulate_secret(
        cls,
        private_key: bytes,
        ciphertext: bytes
    ) -> bytes:
        """Decapsulate shared secret using ECDH with HKDF derivation"""
        recipient_private_key = serialization.load_der_private_key(
            private_key,
            password=None,
            backend=default_backend()
        )
        ephemeral_public_key = serialization.load_der_public_key(
            ciphertext,
            backend=default_backend()
        )
        
        shared_secret = recipient_private_key.exchange(
            ec.ECDH(), 
            ephemeral_public_key
        )
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=cls.HKDF_INFO,
            backend=default_backend()
        )
        return hkdf.derive(shared_secret)


# =============================================================================
# Encryptor classes - Symmetric
# =============================================================================

class SymmetricEncryptor:
    @staticmethod
    def encrypt_data(
        data: bytes,
        passphrase: bytes,
        output_path: str,
        compress: bool = True
    ):
        """Encrypt data using provided symmetric passphrase"""
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        key = kdf.derive(passphrase)

        # Apply compression if beneficial
        if compress:
            compressed = zlib.compress(data, level=zlib.Z_BEST_COMPRESSION)
            if len(compressed) < len(data):
                data = compressed
                compression_flag = b'\x01'
            else:
                compression_flag = b'\x00'
        else:
            compression_flag = b'\x00'

        # Encrypt with AES-GCM
        nonce = os.urandom(12)
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce), backend=default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(data) + encryptor.finalize()
        tag = encryptor.tag

        # Write to file
        with open(output_path, 'wb') as f:
            f.write(salt)
            f.write(nonce)
            f.write(tag)
            f.write(compression_flag)
            f.write(ciphertext)

    @staticmethod
    def decrypt_data(
        encrypted_file: str,
        passphrase: bytes
    ) -> bytes:
        """Decrypt data using provided symmetric passphrase"""
        with open(encrypted_file, 'rb') as f:
            salt = f.read(16)
            nonce = f.read(12)
            tag = f.read(16)
            compression_flag = f.read(1)
            ciphertext = f.read()

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        key = kdf.derive(passphrase)

        cipher = Cipher(
            algorithms.AES(key),
            modes.GCM(nonce, tag),
            backend=default_backend()
        )
        decryptor = cipher.decryptor()
        data = decryptor.update(ciphertext) + decryptor.finalize()

        if compression_flag == b'\x01':
            data = zlib.decompress(data)

        return data



# =============================================================================
# Assorted public methods
# =============================================================================

def secure_delete(path, passes=3):
    with open(path, "ba+") as f:
        length = f.tell()
        for _ in range(passes):
            f.seek(0)
            f.write(os.urandom(length))
    os.remove(path)

# Anti-memory-scraping technique
def secure_wipe(data):
    import ctypes
    if isinstance(data, bytes):
        buffer = ctypes.create_string_buffer(data)
        ctypes.memset(ctypes.addressof(buffer), 0, len(data))
    del data

# Usage after key operations
# secure_wipe(priv_key)

def load_key_with_expiry(service_name, app_identifier, max_age=3600):
    """Load self-destructing keys"""
    encryptor = get_encryptor(service_name, app_identifier)
    priv_key = encryptor.load_private_key(service_name, app_identifier)
    import threading
    threading.Timer(max_age, secure_wipe, [priv_key]).start()
    return priv_key

def verify_encrypted_file(path):
    with open(path, 'rb') as f:
        key_len = struct.unpack('>I', f.read(4))[0]
        encrypted_aes_key = f.read(key_len)
        nonce = f.read(12)
        tag = f.read(16)
        ciphertext = f.read()
        
        print(f"File structure: key={key_len}, nonce=12, tag=16, ciphertext={len(ciphertext)}")
        return len(encrypted_aes_key) == key_len and len(nonce) == 12 and len(tag) == 16


# =============================================================================
# Encryptor type handling
# =============================================================================

ENCRYPTOR_CLASSES = {}

def get_encryptor(service_name, app_identifier, use_global=False):
    key = _get_encryptor_key(service_name, app_identifier)
    encryptor_class = ENCRYPTOR_CLASSES.get(key, None)
    if encryptor_class is None:
        encryptor_class = _determine_encryptor(service_name, app_identifier)
        if encryptor_class is None:
            raise RuntimeError("Failed to set an encryptor type!")
        ENCRYPTOR_CLASSES[key] = encryptor_class
    return encryptor_class

def _get_encryptor_key(service_name, app_identifier):
    return service_name + ":::" + app_identifier

def _determine_encryptor(service_name, app_identifier, override_stored_type=False):
    # Stored key type, from the key store when present and otherwise from the
    # pre-consolidation keychain item. Reading the item directly (rather than
    # migrating here) keeps migration in one place: it needs a concrete
    # encryptor class, which is what this function is being called to pick.
    store = read_key_store(service_name, app_identifier)
    if store is not None:
        stored_type = store.get(ENCRYPTOR_TYPE_KEY)
    else:
        stored_type = keyring.get_password(
            service_name,
            namespaced_key(app_identifier, ENCRYPTOR_TYPE_KEY)
        )

    # Resolve encryptor based on stored type and current capabilities
    if not override_stored_type and stored_type == "quantum":
        if KeyEncapsulation:
            print("OQS available, using Quantum Encryptor")
            return PersonalQuantumEncryptor
        else:
            raise RuntimeError("Warning: Quantum keys found but OQS unavailable. Switching to standard.")
    elif not override_stored_type and stored_type == "standard":
        if KeyEncapsulation:
            print("OQS is available, but the stored type is using Standard Encryptor, consider migration.")
        else:
            print("No OQS available, using Standard Encryptor")
        return PersonalStandardEncryptor
    else:
        # No stored keys - use current best available
        if KeyEncapsulation:
            if override_stored_type:
                print("Overriding stored type with Quantum Encryptor")
            else:
                print("OQS available, using Quantum Encryptor")
            return PersonalQuantumEncryptor
        else:
            if override_stored_type:
                print("Overriding stored type with Standard Encryptor")
            else:
                print("No OQS available, using Standard Encryptor")
            return PersonalStandardEncryptor


# =============================================================================
# File Interfaces
# =============================================================================

def encrypt_data_to_file(
    data: bytes,
    service_name: str,
    app_identifier: str,
    output_path: str,
    compress: bool = True,
    reset_keys: bool = False
) -> bytes:
    encryptor = get_encryptor(service_name, app_identifier)
    """Encrypt data with public key"""
    public_key = encryptor.generate_and_store_keys(
        service_name=service_name, force_new=reset_keys, app_identifier=app_identifier)
    private_key = encryptor.load_private_key(
        service_name=service_name, app_identifier=app_identifier)
    encryptor.verify_keys(public_key, private_key)
    return encryptor.encrypt_data(data, public_key, output_path, compress)

def decrypt_data_from_file(encrypted_file: str, service_name: str, app_identifier: str) -> bytes:
    """Decrypt data with private key"""
    encryptor = get_encryptor(service_name, app_identifier)
    private_key = encryptor.load_private_key(
        service_name=service_name, app_identifier=app_identifier)
    return encryptor.decrypt_data_from_file(private_key, encrypted_file)

def encrypt_file(
    input_file: str,
    output_file: str,
    service_name: str,
    app_identifier: str,
    reset_keys: bool = False
):
    """Encrypt file with public key"""
    encryptor = get_encryptor(service_name, app_identifier)
    public_key = encryptor.generate_and_store_keys(
        service_name=service_name, app_identifier=app_identifier, force_new=reset_keys)
    private_key = encryptor.load_private_key(
        service_name=service_name, app_identifier=app_identifier)
    encryptor.verify_keys(public_key, private_key)
    return encryptor.encrypt_file(
        public_key=public_key,
        input_path=input_file,
        output_path=output_file
    )

def decrypt_to_file(
    input_file: str,
    output_file: str,
    service_name: str,
    app_identifier: str
):
    """Decrypt file with private key"""
    encryptor = get_encryptor(service_name, app_identifier)
    private_key = encryptor.load_private_key(service_name=service_name, app_identifier=app_identifier)
    return encryptor.decrypt_to_file(
        private_key=private_key,
        input_path=input_file,
        output_path=output_file
    )

# =============================================================================
# Password Interfaces
# =============================================================================

def encrypt_password(
    password: str,
    service_name: str,
    app_identifier: str
) -> bytes:
    """Encrypt password with public key"""
    encryptor = get_encryptor(service_name, app_identifier)
    public_key = encryptor.generate_and_store_keys(service_name=service_name, app_identifier=app_identifier)
    return encryptor.encrypt_password(public_key, password)

def decrypt_password(
    encrypted_password: bytes,
    service_name: str,
    app_identifier: str
) -> str:
    """Decrypt password with private key"""
    encryptor = get_encryptor(service_name, app_identifier)
    private_key = encryptor.load_private_key(service_name=service_name, app_identifier=app_identifier)
    return encryptor.decrypt_password(private_key, encrypted_password)

def store_encrypted_password(
    service_name: str, 
    app_identifier: str, 
    password_id: str, 
    password: str
) -> bool:
    """
    Encrypt and store a password securely
    - password_id: Unique identifier for this password (e.g., "email_password")
    """
    try:
        encrypted = encrypt_password(password, service_name, app_identifier)
        PasswordManager.store_password(
            service_name, app_identifier, password_id, encrypted
        )
        return True
    except Exception as e:
        print(f"Error storing password: {str(e)}")
        return False

def retrieve_encrypted_password(
    service_name: str, 
    app_identifier: str, 
    password_id: str
) -> Optional[str]:
    """
    Retrieve and decrypt a stored password
    """
    try:
        encrypted = PasswordManager.retrieve_password(
            service_name, app_identifier, password_id
        )
        if encrypted is None:
            return None
        return decrypt_password(encrypted, service_name, app_identifier)
    except Exception as e:
        print(f"Error retrieving password: {str(e)}")
        return None

def delete_stored_password(
    service_name: str, 
    app_identifier: str, 
    password_id: str
):
    """
    Delete a stored password
    """
    PasswordManager.delete_password(service_name, app_identifier, password_id)


# =============================================================================
# Management Interfaces
# =============================================================================

def migrate_keys(
    source_service: str,
    source_app: str,
    target_service: str,
    target_app: str,
    delete_source: bool = False
):
    """
    Migrate keys from one service/app combination to another
    - source_service: Original service name
    - source_app: Original app identifier
    - target_service: New service name
    - target_app: New app identifier
    - delete_source: Whether to remove source keys after migration
    """
    encryptor = get_encryptor(source_service, source_app)
    encryptor.migrate_keys(
        source_service,
        source_app,
        target_service,
        target_app,
        delete_source
    )

def purge_legacy_keys(service_name: str):
    """Remove pre-namespaced keys (if any exist)"""
    print("Purging legacy keys...")
    legacy_keys = ["salt", "nonce", "tag", 
                 "encrypted_priv_count", "public_key_count"]
    for base in ["encrypted_priv", "public_key"]:
        if count_str := keyring.get_password(service_name, f"{base}_count"):
            try:
                count = int(count_str)
                for i in range(count):
                    keyring.delete_password(service_name, f"{base}_{i}")
            except ValueError:
                pass
    for key in legacy_keys:
        try:
            keyring.delete_password(service_name, key)
        except Exception:
            pass

def purge_all_keys(service_name: str):
    """Purge ALL keys associated with a service (with confirmation)"""
    if not sys.stdin.isatty():
        print("Error: This function requires an interactive terminal")
        return
        
    confirm = input(f"WARNING: This will delete ALL keys for '{service_name}'. Continue? (y/N): ")
    if confirm.lower() != 'y':
        print("Operation cancelled")
        return
        
    # Get all credentials for the service
    try:
        import keyring.backend
        backend = keyring.get_keyring()
        if hasattr(backend, "get_credentials"):
            creds = backend.get_credentials(service_name)
            for cred in creds:
                try:
                    keyring.delete_password(service_name, cred.username)
                    print(f"Deleted: {cred.username}")
                except Exception as e:
                    print(f"Error deleting {cred.username}: {str(e)}")
        else:
            print("Error: Current keyring backend doesn't support credential listing")
    except Exception as e:
        print(f"Error accessing keyring: {str(e)}")


# =============================================================================
# Public Symmetric Interface
# =============================================================================

def symmetric_encrypt_data_to_file(
    data: bytes,
    output_path: str,
    passphrase: bytes,
    compress: bool = True
):
    """Encrypt data using symmetric key and store to file"""
    SymmetricEncryptor.encrypt_data(data, passphrase, output_path, compress)

def symmetric_decrypt_data_from_file(
    input_path: str,
    passphrase: bytes
) -> bytes:
    """Decrypt data using symmetric key from file"""
    return SymmetricEncryptor.decrypt_data(input_path, passphrase)

def symmetric_encrypt_file(
    input_path: str, 
    output_path: str, 
    passphrase: bytes,
    compress: bool = True
):
    """Encrypt file using symmetric key (portable across installations)"""
    with open(input_path, 'rb') as f:
        data = f.read()
    SymmetricEncryptor.encrypt_data(data, passphrase, output_path, compress)

def symmetric_decrypt_file(
    input_path: str, 
    output_path: str, 
    passphrase: bytes
):
    """Decrypt file using symmetric key"""
    data = SymmetricEncryptor.decrypt_data(input_path, passphrase)
    with open(output_path, 'wb') as f:
        f.write(data)



if __name__ == "__main__":
    reset_keys = True
    #reset_keys = False
    service_name = "TestService"
    app_identifier = "main_app"

    # Proceed with file encryption/decryption
    home_dir = os.path.expanduser("~")
    input_file = os.path.join(home_dir, f"test_{app_identifier}.txt")
    encrypted_file = os.path.join(home_dir, f"test_{app_identifier}_encrypted")
    decrypted_file = os.path.join(home_dir, f"test_{app_identifier}_decrypted.txt")

    if os.path.exists(input_file):
        confirm = input(f"File {input_file} already exists. Overwrite? (y/n): ")
        if len(confirm) == 0 or confirm.strip().lower() != "y":
            print("Exiting...")
            exit()

    # Write test data to a file
    with open(input_file, "w", encoding="utf-8") as f:
        for i in range(1000):
            f.write(f"This is a test file {i}\n")

    encrypt_file(input_file, encrypted_file, service_name, app_identifier, reset_keys=reset_keys)
    # Verify encrypted file structure
    verify_encrypted_file(encrypted_file)
    decrypt_to_file(encrypted_file, decrypted_file, service_name, app_identifier)

    # Verify decryption
    with open(input_file, "rb") as orig, open(decrypted_file, "rb") as dec:
        if orig.read() == dec.read():
            print("Decryption successful! File contents match.")
        else:
            print("WARNING: Decrypted file does not match original!")


    
    # Add password storage/retrieval test
    test_password = "MySuperSecurePassword123!"
    password_id = "test_password"
    
    # Store password
    store_encrypted_password(service_name, app_identifier, password_id, test_password)
    
    # Retrieve password
    retrieved_password = retrieve_encrypted_password(service_name, app_identifier, password_id)
    
    if test_password == retrieved_password:
        print("Password storage/retrieval successful!")
    else:
        print("Password storage/retrieval failed!")
    
    # Cleanup
    delete_stored_password(service_name, app_identifier, password_id)

    print("\nTesting key migration...")
    source_service = service_name
    source_app = app_identifier
    target_service = "MigratedService"
    target_app = "migrated_app"
    
    # Migrate keys
    migrate_keys(source_service, source_app, target_service, target_app, delete_source=True)
    encryptor = get_encryptor(target_service, target_app)
    
    # Test migrated keys
    try:
        public_key = encryptor.generate_and_store_keys(
            service_name=target_service, 
            app_identifier=target_app
        )
        private_key = encryptor.load_private_key(
            service_name=target_service, 
            app_identifier=target_app
        )
        encryptor.verify_keys(public_key, private_key)
        print("Key migration successful!")
    except Exception as e:
        print(f"Key migration failed: {str(e)}")
    
    # Cleanup migrated keys
    get_encryptor(target_service, app_identifier).purge_keys(target_service, app_identifier)
    keyring.delete_password(target_service, namespaced_key(target_app, "passphrase"))
    os.remove(input_file)
    os.remove(encrypted_file)
    os.remove(decrypted_file)

    # Symmetric encryption test
    print("\nTesting symmetric encryption...")
    input_file = os.path.join(home_dir, "test_symmetric.txt")
    encrypted_file = os.path.join(home_dir, "test_symmetric_encrypted")
    decrypted_file = os.path.join(home_dir, "test_symmetric_decrypted.txt")
    
    with open(input_file, "w") as f:
        f.write("Test data for symmetric encryption\n")
    
    # Use a passphrase provided by the user
    test_passphrase = b"my_custom_passphrase"
    
    symmetric_encrypt_file(input_file, encrypted_file, test_passphrase)
    symmetric_decrypt_file(encrypted_file, decrypted_file, test_passphrase)
    
    with open(input_file) as orig, open(decrypted_file) as dec:
        if orig.read() == dec.read():
            print("Symmetric encryption successful!")
        else:
            print("Symmetric encryption failed!")
    
    os.remove(input_file)
    os.remove(encrypted_file)
    os.remove(decrypted_file)

