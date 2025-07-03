import os
import struct
import sys
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


def namespaced_key(*keyparts):
    return f"__".join(str(part) for part in keyparts if part)

def get_key_base(app_identifier, key):
    if app_identifier:
        return namespaced_key(app_identifier, key) if key else app_identifier
    return key


class PassphraseManager:
    @staticmethod
    def get_passphrase(service_name="MyApp", app_identifier="main_app"):
        """
        Retrieve passphrase from secure storage with platform-specific methods
        """
        # 1. Try environment variable first (for containerized environments)
        env_var = f"{service_name.upper()}_PASSPHRASE"
        if env_var in os.environ:
            return os.environ[env_var]
        
        # 2. Try platform-specific secure storage
        platform_handler = {
            'win32': PassphraseManager._windows_get_passphrase,
            'darwin': PassphraseManager._macos_get_passphrase,
            'linux': PassphraseManager._linux_get_passphrase
        }.get(sys.platform, PassphraseManager._fallback_get_passphrase)
        
        return platform_handler(service_name, app_identifier)

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
        from Foundation import NSBundle, kSecUseAuthenticationUI
        
        key = namespaced_key(app_identifier, "passphrase")
        passphrase = keyring.get_password(service_name, key)
        
        if not passphrase:
            passphrase = os.urandom(32).hex()
            keyring.set_password(service_name, key, passphrase)
            
            # Set keychain item ACL (requires PyObjC)
            try:
                from Security import kSecAttrAccessible, kSecAttrAccessGroup
                keyring.set_keyring_properties(
                    label=f"{service_name} Passphrase",
                    accessible=kSecAttrAccessible.AccessibleWhenUnlockedThisDeviceOnly,
                    access_group=NSBundle.mainBundle().bundleIdentifier()
                )
            except ImportError:
                pass  # Fallback if PyObjC not available
        
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
    @staticmethod
    def store_password(
        service_name: str,
        app_identifier: str,
        password_id: str,
        encrypted_password: bytes
    ):
        """
        Store encrypted password using platform-specific secure storage
        with chunking for large data
        """
        # Use the same chunking mechanism as BaseEncryptor
        BaseEncryptor._store_large_data(
            service_name, 
            app_identifier,
            password_id, 
            encrypted_password
        )

    @staticmethod
    def retrieve_password(
        service_name: str,
        app_identifier: str,
        password_id: str
    ) -> Optional[bytes]:
        """
        Retrieve encrypted password from platform-specific secure storage
        """
        return BaseEncryptor._retrieve_large_data(
            service_name, 
            app_identifier,
            password_id
        )

    @staticmethod
    def delete_password(
        service_name: str,
        app_identifier: str,
        password_id: str
    ):
        """
        Delete stored password from all storage locations
        """
        # Delete all chunks and count entry
        key_base = get_key_base(app_identifier, password_id)
        count_key = namespaced_key(key_base, "count")
        count_str = keyring.get_password(service_name, count_key)
        if count_str:
            try:
                count = int(count_str)
                for i in range(count):
                    keyring.delete_password(service_name, namespaced_key(key_base, i))
                keyring.delete_password(service_name, count_key)
            except ValueError:
                pass


class BaseEncryptor:
    SALT_KEY = "salt"
    NONCE_KEY = "nonce"
    TAG_KEY = "tag"
    ENCRYPTED_PRIV_KEY = "encrypted_priv"
    PUBLIC_KEY = "public_key"
    PASSPHRASE_KEY = "passphrase"

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
        # Check if keys already exist
        if keyring.get_password(service_name, namespaced_key(app_identifier, cls.SALT_KEY)):
            if force_new:
                print(f"{service_name}:{app_identifier} keys already exist. Generating new keys.")
                cls.purge_keys(service_name, app_identifier)
                return cls.generate_and_store_keys(service_name, app_identifier, force_new=False)
            # print("Keys already exist. Using existing configuration.")
            pub_key = cls._retrieve_large_data(service_name, app_identifier, cls.PUBLIC_KEY)
            return pub_key
        
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
        
        # Store components
        keyring.set_password(service_name, namespaced_key(app_identifier, cls.SALT_KEY), salt.hex())
        keyring.set_password(service_name, namespaced_key(app_identifier, cls.NONCE_KEY), nonce.hex())
        keyring.set_password(service_name, namespaced_key(app_identifier, cls.TAG_KEY), encryptor.tag.hex())
        
        # Store large data using chunking
        cls._store_large_data(service_name, app_identifier, cls.ENCRYPTED_PRIV_KEY, encrypted_priv)
        cls._store_large_data(service_name, app_identifier, cls.PUBLIC_KEY, pub_key)
        
        return pub_key

    @classmethod
    def load_private_key(
        cls,
        service_name: str,
        app_identifier: str
    ) -> bytes:
        """Load private key"""
        salt = bytes.fromhex(keyring.get_password(service_name, namespaced_key(app_identifier, cls.SALT_KEY)))
        nonce = bytes.fromhex(keyring.get_password(service_name, namespaced_key(app_identifier, cls.NONCE_KEY)))
        tag = bytes.fromhex(keyring.get_password(service_name, namespaced_key(app_identifier, cls.TAG_KEY)))
        encrypted_priv = cls._retrieve_large_data(service_name, app_identifier, cls.ENCRYPTED_PRIV_KEY)
        
        if None in (salt, nonce, tag, encrypted_priv):
            raise ValueError("Failed to retrieve key components from keyring")
        
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
        """
        # Retrieve source keys
        source_priv = cls.load_private_key(source_service, source_app)
        source_pub = cls._retrieve_large_data(source_service, source_app, cls.PUBLIC_KEY)
        source_salt = bytes.fromhex(keyring.get_password(source_service, namespaced_key(source_app, cls.SALT_KEY)))
        source_nonce = bytes.fromhex(keyring.get_password(source_service, namespaced_key(source_app, cls.NONCE_KEY)))
        source_tag = bytes.fromhex(keyring.get_password(source_service, namespaced_key(source_app, cls.TAG_KEY)))
        
        # Get source passphrase
        source_passphrase = PassphraseManager.get_passphrase(source_service, source_app)
        
        # Get target passphrase (will create if doesn't exist)
        target_passphrase = PassphraseManager.get_passphrase(target_service, target_app)
        
        # Re-encrypt private key with new passphrase
        new_salt = os.urandom(16)
        storage_key = cls._derive_key(target_passphrase, new_salt, 32)
        new_nonce = os.urandom(12)
        
        cipher = Cipher(algorithms.AES(storage_key), modes.GCM(new_nonce), default_backend())
        encryptor = cipher.encryptor()
        reencrypted_priv = encryptor.update(source_priv) + encryptor.finalize()
        
        # Store components in target namespace
        keyring.set_password(target_service, namespaced_key(target_app, cls.SALT_KEY), new_salt.hex())
        keyring.set_password(target_service, namespaced_key(target_app, cls.NONCE_KEY), new_nonce.hex())
        keyring.set_password(target_service, namespaced_key(target_app, cls.TAG_KEY), encryptor.tag.hex())
        
        cls._store_large_data(target_service, target_app, cls.ENCRYPTED_PRIV_KEY, reencrypted_priv)
        cls._store_large_data(target_service, target_app, cls.PUBLIC_KEY, source_pub)
        
        # Optionally delete source keys
        if delete_source:
            # Delete key components
            keys_to_delete = [namespaced_key(source_app, cls.SALT_KEY),
                              namespaced_key(source_app, cls.NONCE_KEY),
                              namespaced_key(source_app, cls.TAG_KEY)]
            for base in [cls.ENCRYPTED_PRIV_KEY, cls.PUBLIC_KEY]:
                base_key = namespaced_key(source_app, base)
                count_key = namespaced_key(base_key, "count")
                count_str = keyring.get_password(source_service, count_key)
                if count_str:
                    try:
                        count = int(count_str)
                        for i in range(count):
                            keyring.delete_password(source_service, namespaced_key(base_key, i))
                    except ValueError:
                        pass
                keys_to_delete.append(count_key)
            
            for key in keys_to_delete:
                try:
                    keyring.delete_password(source_service, key)
                except Exception:
                    pass
            
            # Delete source passphrase
            try:
                keyring.delete_password(source_service, namespaced_key(source_app, cls.PASSPHRASE_KEY))
            except Exception:
                pass

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
    def _store_large_data(
        cls,
        service_name: str,
        app_identifier: str,
        key: str,
        data: bytes
    ):
        """Store large data in chunks to work around credential size limits"""
        key_base = get_key_base(app_identifier, key)
        hex_data = data.hex()
        chunk_size = 500
        chunks = [hex_data[i:i+chunk_size] for i in range(0, len(hex_data), chunk_size)]
        
        # print(f"Storing {len(chunks)} chunks for {key_base}")
        keyring.set_password(service_name, namespaced_key(key_base, "count"), str(len(chunks)))
        for i, chunk in enumerate(chunks):
            keyring.set_password(service_name, namespaced_key(key_base, i), chunk)
    
    @classmethod
    def _retrieve_large_data(
        cls,
        service_name: str,
        app_identifier: str,
        key: str
    ) -> Optional[bytes]:
        """Retrieve chunked large data"""
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
        """Purge keys"""
        """
        Purge all keys and associated data from keyring and local files
        - service_name: Keyring service namespace
        - purge_files: Also delete public key file and any encrypted files
        """
        # Delete all keyring entries
        keys_to_delete = [namespaced_key(app_identifier, cls.SALT_KEY),
                          namespaced_key(app_identifier, cls.NONCE_KEY),
                          namespaced_key(app_identifier, cls.TAG_KEY)]
        
        # Add chunked entries
        for base in [cls.ENCRYPTED_PRIV_KEY, cls.PUBLIC_KEY]:
            # Get chunk count
            key_base = get_key_base(app_identifier, base)
            count_key = namespaced_key(key_base, "count")
            count_str = keyring.get_password(service_name, count_key)
            if count_str:
                try:
                    count = int(count_str)
                    for i in range(count):
                        keyring.delete_password(service_name, namespaced_key(key_base, i))
                except Exception:
                    pass
            
            # Delete the count entry
            keys_to_delete.append(count_key)
        
        # Delete all standard keys
        for key in keys_to_delete:
            try:
                keyring.delete_password(service_name, key)
            except Exception:
                pass
        
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
    KYBER_ALG = "Kyber768"
    purge_files = ["quantum_pub.key"]
    
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
    CURVE = ec.SECP384R1()
    HKDF_INFO = b'PersonalStandardEncryptor'
    purge_files = ["standard_pub.key"]
    
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

# Self-destructing keys
def load_key_with_expiry(max_age=3600):
    priv_key = BaseEncryptor.load_private_key()
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


if KeyEncapsulation:
    ENCRYPTOR = PersonalQuantumEncryptor
    print("Using Quantum Encryptor")
else:
    ENCRYPTOR = PersonalStandardEncryptor
    print("Using Standard Encryptor")


def verify_keys(public_key: bytes, private_key: bytes):
    encapsulated, shared_secret1 = ENCRYPTOR.encapsulate_secret(public_key)
    shared_secret2 = ENCRYPTOR.decapsulate_secret(private_key, encapsulated)
    
    if shared_secret1 != shared_secret2:
        raise ValueError("WARNING: Public/private key mismatch!")

# File Interfaces

def encrypt_data_to_file(
    data: bytes,
    service_name: str,
    app_identifier: str,
    output_path: str,
    compress: bool = True,
    reset_keys: bool = False
) -> bytes:
    """Encrypt data with public key"""
    public_key = ENCRYPTOR.generate_and_store_keys(
        service_name=service_name, force_new=reset_keys, app_identifier=app_identifier)
    private_key = BaseEncryptor.load_private_key(
        service_name=service_name, app_identifier=app_identifier)
    verify_keys(public_key, private_key)
    return ENCRYPTOR.encrypt_data(data, public_key, output_path, compress)

def decrypt_data_from_file(encrypted_file: str, service_name: str, app_identifier: str) -> bytes:
    """Decrypt data with private key"""
    private_key = BaseEncryptor.load_private_key(
        service_name=service_name, app_identifier=app_identifier)
    return ENCRYPTOR.decrypt_data_from_file(private_key, encrypted_file)

def encrypt_file(
    input_file: str,
    output_file: str,
    service_name: str,
    app_identifier: str,
    reset_keys: bool = False
):
    """Encrypt file with public key"""
    public_key = ENCRYPTOR.generate_and_store_keys(
        service_name=service_name, app_identifier=app_identifier, force_new=reset_keys)
    private_key = BaseEncryptor.load_private_key(
        service_name=service_name, app_identifier=app_identifier)
    verify_keys(public_key, private_key)
    return ENCRYPTOR.encrypt_file(
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
    private_key = BaseEncryptor.load_private_key(service_name=service_name, app_identifier=app_identifier)
    return ENCRYPTOR.decrypt_to_file(
        private_key=private_key,
        input_path=input_file,
        output_path=output_file
    )

# Password Interfaces

def encrypt_password(
    password: str,
    service_name: str,
    app_identifier: str
) -> bytes:
    """Encrypt password with public key"""
    public_key = ENCRYPTOR.generate_and_store_keys(service_name=service_name, app_identifier=app_identifier)
    return ENCRYPTOR.encrypt_password(public_key, password)

def decrypt_password(
    encrypted_password: bytes,
    service_name: str,
    app_identifier: str
) -> str:
    """Decrypt password with private key"""
    private_key = BaseEncryptor.load_private_key(service_name=service_name, app_identifier=app_identifier)
    return ENCRYPTOR.decrypt_password(private_key, encrypted_password)

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


# Management Interfaces

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
    BaseEncryptor.migrate_keys(
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



if __name__ == "__main__":
    reset_keys = True
    #reset_keys = False
    service_name = "TestService"
    app_identifier = "main_app"
    # WARNING - Only uncomment below if you want to risk invalidating your
    # current key, which may invalidate the encryption of your app cache.
    # service_name = "MyPersonalApplicationsService"
    # app_identifier = "sd_runner"

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
    
    # Test migrated keys
    try:
        public_key = ENCRYPTOR.generate_and_store_keys(
            service_name=target_service, 
            app_identifier=target_app
        )
        private_key = BaseEncryptor.load_private_key(
            service_name=target_service, 
            app_identifier=target_app
        )
        verify_keys(public_key, private_key)
        print("Key migration successful!")
    except Exception as e:
        print(f"Key migration failed: {str(e)}")
    
    # Cleanup migrated keys
    ENCRYPTOR.purge_keys(target_service, app_identifier)
    keyring.delete_password(target_service, namespaced_key(target_app, "passphrase"))
    os.remove(input_file)
    os.remove(encrypted_file)
    os.remove(decrypted_file)

