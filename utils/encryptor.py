import os
import struct
import sys
from typing import Optional
import zlib

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
import keyring

try:
    from oqs import KeyEncapsulation
    print("oqs library found. OQS key encapsulation will be available.")
except ImportError:
    print("Warning: oqs library not found. OQS key encapsulation will not be available.")
    KeyEncapsulation = None


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
        passphrase = keyring.get_password(service_name, f"{app_identifier}_passphrase")
        
        if not passphrase:
            # Generate and store new passphrase
            passphrase = os.urandom(32).hex()
            keyring.set_password(service_name, f"{app_identifier}_passphrase", passphrase)
            
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
        passphrase = keyring.get_password(service_name, f"{app_identifier}_passphrase")
        
        if not passphrase:
            passphrase = os.urandom(32).hex()
            keyring.set_password(service_name, f"{app_identifier}_passphrase", passphrase)
            
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
        passphrase = keyring.get_password(service_name, f"{app_identifier}_passphrase")
        
        if not passphrase:
            passphrase = os.urandom(32).hex()
            keyring.set_password(service_name, f"{app_identifier}_passphrase", passphrase)
            
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


class BaseEncryptor:
    @staticmethod
    def _derive_key(passphrase: str, salt: bytes, length=32) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=length,
            salt=salt,
            iterations=1000000,
            backend=default_backend()
        )
        return kdf.derive(passphrase.encode())
    
    @staticmethod
    def _store_large_data(service_name: str, key: str, data: bytes):
        """Store large data in chunks to work around credential size limits"""
        hex_data = data.hex()
        chunk_size = 500
        chunks = [hex_data[i:i+chunk_size] for i in range(0, len(hex_data), chunk_size)]
        
        keyring.set_password(service_name, f"{key}_count", str(len(chunks)))
        for i, chunk in enumerate(chunks):
            keyring.set_password(service_name, f"{key}_{i}", chunk)
    
    @staticmethod
    def _retrieve_large_data(service_name: str, key: str) -> bytes:
        """Retrieve chunked large data"""
        count_str = keyring.get_password(service_name, f"{key}_count")
        if not count_str:
            return None
            
        count = int(count_str)
        chunks = []
        for i in range(count):
            chunk = keyring.get_password(service_name, f"{key}_{i}")
            if not chunk:
                return None
            chunks.append(chunk)
            
        return bytes.fromhex(''.join(chunks))
    
    @staticmethod
    def generate_keypair() -> tuple[bytes, bytes]:
        """Generate key pair"""
        raise NotImplementedError("Subclass must implement this method")
    
    @staticmethod
    def generate_and_store_keys(service_name="MyApp", force_new=False, app_identifier="main_app") -> bytes:
        """Generate and store keys"""
        raise NotImplementedError("Subclass must implement this method")

    @staticmethod
    def load_private_key(service_name="MyApp", app_identifier="main_app") -> bytes:
        """Load private key"""
        salt = bytes.fromhex(keyring.get_password(service_name, "salt"))
        nonce = bytes.fromhex(keyring.get_password(service_name, "nonce"))
        tag = bytes.fromhex(keyring.get_password(service_name, "tag"))
        encrypted_priv = BaseEncryptor._retrieve_large_data(service_name, "encrypted_priv")
        
        if None in (salt, nonce, tag, encrypted_priv):
            raise ValueError("Failed to retrieve key components from keyring")
        
        passphrase = PassphraseManager.get_passphrase(service_name, app_identifier)
        storage_key = BaseEncryptor._derive_key(passphrase, salt, 32)
        
        cipher = Cipher(
            algorithms.AES(storage_key),
            modes.GCM(nonce, tag),
            default_backend()
        )
        decryptor = cipher.decryptor()
        return decryptor.update(encrypted_priv) + decryptor.finalize()
    
    @staticmethod
    def encapsulate_secret(public_key: bytes) -> tuple[bytes, bytes]:
        """Encapsulate secret"""
        raise NotImplementedError("Subclass must implement this method")
    
    @staticmethod
    def decapsulate_secret(private_key: bytes, ciphertext: bytes) -> bytes:
        """Decapsulate secret"""
        raise NotImplementedError("Subclass must implement this method")
    
    @staticmethod
    def encrypt_file(public_key: bytes, input_path: str, output_path: str, compress=True):
        """Encrypt file"""
        raise NotImplementedError("Subclass must implement this method")
    
    @staticmethod
    def decrypt_to_file(private_key: bytes, input_path: str, output_path: str):
        """Decrypt file"""
        raise NotImplementedError("Subclass must implement this method")
    
    @staticmethod
    def purge_keys(service_name="MyApp", purge_files=True):
        """Purge keys"""
        raise NotImplementedError("Subclass must implement this method")

    @staticmethod
    def _do_encrypt(plaintext: bytes, output_path: str, compress: bool, aes_key: bytes, encapsulated_key: bytes):
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

    @staticmethod
    def _read_encrypted_file_attributes(input_path: str) -> tuple[bytes, bytes, bytes, bytes, bytes]:
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

    @staticmethod
    def _do_decrypt(output_path: str, aes_key: bytes, nonce: bytes, tag: bytes, compression_flag: bytes, ciphertext: bytes) -> Optional[bytes]:
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

    @staticmethod
    def _purge_keys(service_name="MyApp", purge_files=[]):
        """Purge keys"""
        """
        Purge all keys and associated data from keyring and local files
        - service_name: Keyring service namespace
        - purge_files: Also delete public key file and any encrypted files
        """
        # Delete all keyring entries
        keys_to_delete = ["salt", "nonce", "tag"]
        
        # Add chunked entries
        for base in ["encrypted_priv", "public_key"]:
            # Get chunk count
            count_str = keyring.get_password(service_name, f"{base}_count")
            if count_str:
                try:
                    count = int(count_str)
                    for i in range(count):
                        keyring.delete_password(service_name, f"{base}_{i}")
                except ValueError:
                    pass
            
            # Delete the count entry
            keys_to_delete.append(f"{base}_count")
        
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
            
            # Optional: Add patterns for encrypted files you want to delete
            # Example: 
            # for purge_file in glob.glob("*.bin"):
            #    try:
            #        os.remove(purge_file)
            #    except Exception:
            #        pass
        
        print("All keys and associated data have been purged")


class PersonalQuantumEncryptor(BaseEncryptor):
    KYBER_ALG = "Kyber768"
    
    @staticmethod
    def generate_keypair():
        """Generate Kyber key pair using oqs"""
        kem = KeyEncapsulation(PersonalQuantumEncryptor.KYBER_ALG)
        public_key = kem.generate_keypair()
        private_key = kem.export_secret_key()
        kem.free()  # Free resources
        return public_key, private_key

    @staticmethod
    def generate_and_store_keys(service_name="MyApp", force_new=False, app_identifier="main_app"):
        # Check if keys already exist
        if keyring.get_password(service_name, "salt"):
            if force_new:
                print("Keys already exist. Generating new keys.")
                PersonalQuantumEncryptor.purge_keys(service_name)
                return PersonalQuantumEncryptor.generate_and_store_keys(service_name, force_new=False)
            # print("Keys already exist. Using existing configuration.")
            pub_key = BaseEncryptor._retrieve_large_data(service_name, "public_key")
            return pub_key
        
        # Generate new keys
        pub_key, priv_key = PersonalQuantumEncryptor.generate_keypair()
        salt = os.urandom(16)
        
        # Get passphrase automatically
        passphrase = PassphraseManager.get_passphrase(service_name, app_identifier)
        
        # Derive storage key
        storage_key = PersonalQuantumEncryptor._derive_key(passphrase, salt, 32)
        nonce = os.urandom(12)
        
        # Encrypt private key
        cipher = Cipher(algorithms.AES(storage_key), modes.GCM(nonce), default_backend())
        encryptor = cipher.encryptor()
        encrypted_priv = encryptor.update(priv_key) + encryptor.finalize()
        
        # Store components
        keyring.set_password(service_name, "salt", salt.hex())
        keyring.set_password(service_name, "nonce", nonce.hex())
        keyring.set_password(service_name, "tag", encryptor.tag.hex())
        
        # Store large data using chunking
        BaseEncryptor._store_large_data(service_name, "encrypted_priv", encrypted_priv)
        BaseEncryptor._store_large_data(service_name, "public_key", pub_key)
        
        return pub_key

    @staticmethod
    def encapsulate_secret(public_key: bytes) -> tuple[bytes, bytes]:
        """Generate a shared secret and its encapsulation using Kyber"""
        kem = KeyEncapsulation(PersonalQuantumEncryptor.KYBER_ALG)
        ciphertext, shared_secret = kem.encap_secret(public_key)
        kem.free()
        return ciphertext, shared_secret

    @staticmethod
    def decapsulate_secret(private_key: bytes, ciphertext: bytes) -> bytes:
        """Decapsulate the shared secret using Kyber"""
        kem = KeyEncapsulation(PersonalQuantumEncryptor.KYBER_ALG, private_key)
        shared_secret = kem.decap_secret(ciphertext)
        kem.free()
        return shared_secret

    @staticmethod
    def encrypt_file(public_key: bytes, input_path: str, output_path: str, compress=True):
        """Encrypt file with optional compression"""
        with open(input_path, 'rb') as f:
            plaintext = f.read()
        return PersonalQuantumEncryptor.encrypt_data(plaintext, public_key, output_path, compress)

    @staticmethod
    def encrypt_data(data: bytes, public_key: bytes, output_path: str, compress=True):
        encapsulated_key, aes_key = PersonalQuantumEncryptor.encapsulate_secret(public_key)
        return BaseEncryptor._do_encrypt(data, output_path, compress, aes_key, encapsulated_key)

    @staticmethod
    def decrypt_data_from_file(private_key: bytes, encrypted_file: str) -> bytes:
        encapsulated_key, nonce, tag, compression_flag, ciphertext = BaseEncryptor._read_encrypted_file_attributes(encrypted_file)
        aes_key = PersonalQuantumEncryptor.decapsulate_secret(private_key, encapsulated_key)
        return BaseEncryptor._do_decrypt(None, aes_key, nonce, tag, compression_flag, ciphertext)

    @staticmethod
    def decrypt_to_file(private_key: bytes, input_path: str, output_path: str):
        encapsulated_key, nonce, tag, compression_flag, ciphertext = BaseEncryptor._read_encrypted_file_attributes(input_path)
        # Decapsulate the shared secret (AES key)
        aes_key = PersonalQuantumEncryptor.decapsulate_secret(private_key, encapsulated_key)
        BaseEncryptor._do_decrypt(output_path, aes_key, nonce, tag, compression_flag, ciphertext)
    
    @staticmethod
    def purge_keys(service_name="MyApp", purge_files=True):
        """
        Purge all keys and associated data from keyring and local files
        - service_name: Keyring service namespace
        - purge_files: Also delete public key file and any encrypted files
        """
        purge_files = ["quantum_pub.key"] if purge_files else []
        BaseEncryptor._purge_keys(service_name, purge_files)



class PersonalStandardEncryptor(BaseEncryptor):
    CURVE = ec.SECP384R1()
    HKDF_INFO = b'PersonalStandardEncryptor'
    
    @staticmethod
    def generate_keypair():
        """Generate ECDH key pair using standard curve"""
        private_key = ec.generate_private_key(PersonalStandardEncryptor.CURVE, default_backend())
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

    @staticmethod
    def generate_and_store_keys(service_name="MyApp", force_new=False, app_identifier="main_app"):
        if keyring.get_password(service_name, "salt"):
            if force_new:
                PersonalStandardEncryptor.purge_keys(service_name)
                return PersonalStandardEncryptor.generate_and_store_keys(service_name, force_new=False)
            pub_key = BaseEncryptor._retrieve_large_data(service_name, "public_key")
            return pub_key
        
        pub_key, priv_key = PersonalStandardEncryptor.generate_keypair()
        salt = os.urandom(16)
        passphrase = PassphraseManager.get_passphrase(service_name, app_identifier)
        storage_key = PersonalStandardEncryptor._derive_key(passphrase, salt, 32)
        nonce = os.urandom(12)
        
        cipher = Cipher(algorithms.AES(storage_key), modes.GCM(nonce), default_backend())
        encryptor = cipher.encryptor()
        encrypted_priv = encryptor.update(priv_key) + encryptor.finalize()
        
        keyring.set_password(service_name, "salt", salt.hex())
        keyring.set_password(service_name, "nonce", nonce.hex())
        keyring.set_password(service_name, "tag", encryptor.tag.hex())
        
        BaseEncryptor._store_large_data(service_name, "encrypted_priv", encrypted_priv)
        BaseEncryptor._store_large_data(service_name, "public_key", pub_key)
        
        return pub_key

    @staticmethod
    def encapsulate_secret(public_key: bytes) -> tuple[bytes, bytes]:
        """Generate shared secret using ECDH with HKDF derivation"""
        recipient_public_key = serialization.load_der_public_key(
            public_key,
            backend=default_backend()
        )
        ephemeral_private_key = ec.generate_private_key(
            PersonalStandardEncryptor.CURVE,
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
            info=PersonalStandardEncryptor.HKDF_INFO,
            backend=default_backend()
        )
        aes_key = hkdf.derive(shared_secret)
        
        ephemeral_pub_bytes = ephemeral_public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return ephemeral_pub_bytes, aes_key

    @staticmethod
    def decapsulate_secret(private_key: bytes, ciphertext: bytes) -> bytes:
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
            info=PersonalStandardEncryptor.HKDF_INFO,
            backend=default_backend()
        )
        return hkdf.derive(shared_secret)

    @staticmethod
    def encrypt_file(public_key: bytes, input_path: str, output_path: str, compress=True):
        with open(input_path, 'rb') as f:
            plaintext = f.read()
        return PersonalStandardEncryptor.encrypt_data(plaintext, public_key, output_path, compress)

    @staticmethod
    def encrypt_data(data: bytes, public_key: bytes, output_path: str, compress=True):
        encapsulated_key, aes_key = PersonalStandardEncryptor.encapsulate_secret(public_key)
        return BaseEncryptor._do_encrypt(data, output_path, compress, aes_key, encapsulated_key)

    @staticmethod
    def decrypt_data_from_file(private_key: bytes, encrypted_file: str) -> bytes:
        encapsulated_key, nonce, tag, compression_flag, ciphertext = BaseEncryptor._read_encrypted_file_attributes(encrypted_file)
        aes_key = PersonalStandardEncryptor.decapsulate_secret(private_key, encapsulated_key)
        return BaseEncryptor._do_decrypt(None, aes_key, nonce, tag, compression_flag, ciphertext)

    @staticmethod
    def decrypt_to_file(private_key: bytes, input_path: str, output_path: str):
        encapsulated_key, nonce, tag, compression_flag, ciphertext = BaseEncryptor._read_encrypted_file_attributes(input_path)
        aes_key = PersonalStandardEncryptor.decapsulate_secret(private_key, encapsulated_key)
        BaseEncryptor._do_decrypt(output_path, aes_key, nonce, tag, compression_flag, ciphertext)
    
    @staticmethod
    def purge_keys(service_name="MyApp", purge_files=True):
        """
        Purge all keys and associated data from keyring and local files
        - service_name: Keyring service namespace
        - purge_files: Also delete public key file and any encrypted files
        """
        purge_files = ["standard_pub.key"] if purge_files else []
        BaseEncryptor._purge_keys(service_name, purge_files)

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


def encrypt_data_to_file(data: bytes, service_name: str, app_identifier: str, output_path: str, compress=True, reset_keys=False) -> bytes:
    """Encrypt data with public key"""
    public_key = ENCRYPTOR.generate_and_store_keys(service_name=service_name, force_new=reset_keys, app_identifier=app_identifier)
    private_key = BaseEncryptor.load_private_key(service_name=service_name, app_identifier=app_identifier)
    verify_keys(public_key, private_key)
    return ENCRYPTOR.encrypt_data(data, public_key, output_path, compress)


def decrypt_data_from_file(encrypted_file: str, service_name: str, app_identifier: str) -> bytes:
    """Decrypt data with private key"""
    private_key = BaseEncryptor.load_private_key(service_name=service_name, app_identifier=app_identifier)
    return ENCRYPTOR.decrypt_data_from_file(private_key, encrypted_file)


def encrypt_file(input_file: str, output_file: str, service_name: str, app_identifier: str):
    """Encrypt file with public key"""
    public_key = ENCRYPTOR.generate_and_store_keys(service_name=service_name, force_new=reset_keys, app_identifier=app_identifier)
    private_key = BaseEncryptor.load_private_key(service_name=service_name, app_identifier=app_identifier)
    verify_keys(public_key, private_key)
    return ENCRYPTOR.encrypt_file(
        public_key=public_key,
        input_path=input_file,
        output_path=output_file
    )

def decrypt_to_file(input_file: str, output_file: str, service_name: str, app_identifier: str):
    """Decrypt file with private key"""
    private_key = BaseEncryptor.load_private_key(service_name=service_name, app_identifier=app_identifier)
    return ENCRYPTOR.decrypt_to_file(
        private_key=private_key,
        input_path=input_file,
        output_path=output_file
    )


if __name__ == "__main__":
    # reset_keys = True
    reset_keys = False
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
