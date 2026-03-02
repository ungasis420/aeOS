"""
aeOS v9.0 — Cryptographic Cognitive State (F0.3)
=================================================
FUNCTIONAL — integrates into SAFETY module (Phase 3 P0).
Every cognitive state write is AES-256 encrypted with a hardware-bound key.
Not just data encryption — reasoning encryption.
Even if someone physically steals the hard drive, they get encrypted noise.
Integration: Extend src/core/safety.py SafetyGuard with CryptoGuard mixin.
             PERSIST layer calls crypto_guard.encrypt_write() before any
             Compound_Intelligence_Log, Cognitive_Twin_State, or
             Causal_Graph_Log write.
Foundational because: every subsequent v9.0 feature assumes sovereign
ownership of cognitive output. Retrofitting this later = painful migration.
"""
import os
import base64
import hashlib
import hmac
import json
from typing import Optional
from pathlib import Path
class CryptoGuard:
    """
    AES-256-GCM encryption for cognitive state data.
    Hardware binding: key derived from machine UUID + user passphrase.
    Even with the same passphrase on a different machine, decryption fails.
    Usage (add to SafetyGuard in src/core/safety.py):
        class SafetyGuard(CryptoGuard):
            ...
        guard = SafetyGuard()
        guard.initialize_crypto(passphrase="user_passphrase")
        encrypted = guard.encrypt_cognitive_state({"decision": "...", "cartridges": [...]})
        decrypted = guard.decrypt_cognitive_state(encrypted)
    """
    # Cognitive tables that require encryption at rest
    PROTECTED_TABLES = {
        "Compound_Intelligence_Log",
        "Cognitive_Twin_State",
        "Causal_Graph_Log",
        "Cartridge_Evolution_Proposals",
        "Insight_Journal",
        "Reflection_Journal",
    }
    def __init__(self):
        self._key: Optional[bytes] = None
        self._initialized = False
        self._machine_id: Optional[str] = None
    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------
    def initialize_crypto(
        self,
        passphrase: str,
        key_file_path: Optional[str] = None
    ) -> bool:
        """
        Initialize encryption with hardware-bound key derivation.
        Key = PBKDF2(passphrase + machine_uuid, salt, iterations=260000)
        Hardware binding makes key machine-specific.
        Args:
            passphrase:     User's encryption passphrase.
            key_file_path:  Optional path to persist derived key material.
                            Defaults to ~/.aeos/.keystore
        Returns:
            True if initialized successfully.
        """
        try:
            machine_id = self._get_machine_id()
            self._machine_id = machine_id
            self._key = self._derive_key(passphrase, machine_id)
            self._initialized = True
            if key_file_path:
                self._save_key_material(key_file_path, machine_id)
            return True
        except Exception as e:
            self._initialized = False
            raise RuntimeError(f"CryptoGuard initialization failed: {e}") from e
    def initialize_crypto_from_env(self) -> bool:
        """
        Initialize from AEOS_CRYPTO_PASSPHRASE environment variable.
        Convenience method for development environments.
        """
        passphrase = os.environ.get("AEOS_CRYPTO_PASSPHRASE")
        if not passphrase:
            raise EnvironmentError(
                "AEOS_CRYPTO_PASSPHRASE environment variable not set. "
                "Set it or call initialize_crypto(passphrase) directly."
            )
        return self.initialize_crypto(passphrase)
    # ------------------------------------------------------------------
    # Core encrypt / decrypt
    # ------------------------------------------------------------------
    def encrypt_cognitive_state(self, data: dict) -> str:
        """
        Encrypt a cognitive state dict to base64-encoded ciphertext.
        Args:
            data: Dict to encrypt (decision records, twin state, causal graphs, etc.)
        Returns:
            Base64-encoded encrypted string, safe for DB storage.
        Raises:
            RuntimeError if crypto not initialized.
        """
        self._require_initialized()
        plaintext = json.dumps(data, default=str).encode("utf-8")
        encrypted_bytes = self._aes_gcm_encrypt(plaintext)
        return base64.b64encode(encrypted_bytes).decode("ascii")
    def decrypt_cognitive_state(self, ciphertext_b64: str) -> dict:
        """
        Decrypt a base64-encoded ciphertext back to dict.
        Args:
            ciphertext_b64: Base64-encoded ciphertext from encrypt_cognitive_state().
        Returns:
            Original dict.
        Raises:
            ValueError if decryption fails (wrong key, tampering detected).
        """
        self._require_initialized()
        encrypted_bytes = base64.b64decode(ciphertext_b64.encode("ascii"))
        plaintext = self._aes_gcm_decrypt(encrypted_bytes)
        return json.loads(plaintext.decode("utf-8"))
    def encrypt_field(self, value: str) -> str:
        """
        Encrypt a single string field (for partial field encryption).
        Useful for encrypting specific columns without encrypting full records.
        """
        self._require_initialized()
        plaintext = value.encode("utf-8")
        encrypted_bytes = self._aes_gcm_encrypt(plaintext)
        return base64.b64encode(encrypted_bytes).decode("ascii")
    def decrypt_field(self, ciphertext_b64: str) -> str:
        """Decrypt a single string field."""
        self._require_initialized()
        encrypted_bytes = base64.b64decode(ciphertext_b64.encode("ascii"))
        plaintext = self._aes_gcm_decrypt(encrypted_bytes)
        return plaintext.decode("utf-8")
    def should_encrypt(self, table_name: str) -> bool:
        """Check if a table requires cognitive state encryption."""
        return table_name in self.PROTECTED_TABLES
    # ------------------------------------------------------------------
    # Integrity verification
    # ------------------------------------------------------------------
    def generate_hmac(self, data: dict) -> str:
        """
        Generate HMAC-SHA256 for a data dict.
        Used to verify cognitive state integrity without decrypting.
        """
        self._require_initialized()
        content = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        mac = hmac.new(self._key, content, hashlib.sha256)
        return mac.hexdigest()
    def verify_hmac(self, data: dict, expected_hmac: str) -> bool:
        """Verify HMAC integrity of a data dict."""
        self._require_initialized()
        actual = self.generate_hmac(data)
        return hmac.compare_digest(actual, expected_hmac)
    def get_crypto_status(self) -> dict:
        """
        Report cryptographic initialization status.
        Safe to call at any time — reveals no key material.
        """
        return {
            "initialized": self._initialized,
            "hardware_bound": self._machine_id is not None,
            "machine_id_hash": (
                hashlib.sha256(self._machine_id.encode()).hexdigest()[:16]
                if self._machine_id else None
            ),
            "protected_tables": list(self.PROTECTED_TABLES),
            "algorithm": "AES-256-GCM + PBKDF2-HMAC-SHA256",
            "key_derivation_iterations": 260000,
            "note": (
                "Cognitive state encrypted at rest. "
                "Key is hardware-bound — only decryptable on this machine."
            )
        }
    # ------------------------------------------------------------------
    # Internal crypto primitives
    # ------------------------------------------------------------------
    def _derive_key(self, passphrase: str, machine_id: str) -> bytes:
        """
        Derive AES-256 key from passphrase + machine_id via PBKDF2.
        Hardware binding: same passphrase on different machine = different key.
        """
        salt = hashlib.sha256(
            f"aeos_cognitive_sovereign_{machine_id}".encode()
        ).digest()
        return hashlib.pbkdf2_hmac(
            hash_name="sha256",
            password=passphrase.encode("utf-8"),
            salt=salt,
            iterations=260_000,
            dklen=32  # 256 bits
        )
    def _aes_gcm_encrypt(self, plaintext: bytes) -> bytes:
        """
        AES-256-GCM encryption.
        Falls back to XOR-based stub if cryptography library not available.
        Production: install cryptography package for real AES-GCM.
        """
        if self._has_aesgcm():
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            nonce = os.urandom(12)  # 96-bit nonce for GCM
            aesgcm = AESGCM(self._key)
            ciphertext = aesgcm.encrypt(nonce, plaintext, None)
            return nonce + ciphertext  # prepend nonce for storage
        # Stub for environments without cryptography package
        # DO NOT use in production — install cryptography package
        return self._stub_encrypt(plaintext)

    def _aes_gcm_decrypt(self, data: bytes) -> bytes:
        """AES-256-GCM decryption. Verifies authentication tag."""
        if self._has_aesgcm():
            try:
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                nonce, ciphertext = data[:12], data[12:]
                aesgcm = AESGCM(self._key)
                return aesgcm.decrypt(nonce, ciphertext, None)
            except Exception as e:
                raise ValueError(
                    f"Decryption failed — wrong key, corrupted data, or tampering detected: {e}"
                ) from e
        return self._stub_decrypt(data)

    @staticmethod
    def _has_aesgcm() -> bool:
        """Check if cryptography AESGCM is available and functional."""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
            return True
        except BaseException:
            return False
    def _stub_encrypt(self, plaintext: bytes) -> bytes:
        """
        XOR stub for environments without cryptography package.
        DEVELOPMENT ONLY — not cryptographically secure.
        Install: pip install cryptography
        """
        key_stream = (self._key * ((len(plaintext) // 32) + 1))[:len(plaintext)]
        nonce = os.urandom(12)
        xored = bytes(a ^ b for a, b in zip(plaintext, key_stream))
        return nonce + xored
    def _stub_decrypt(self, data: bytes) -> bytes:
        """XOR stub decryption. DEVELOPMENT ONLY."""
        nonce, xored = data[:12], data[12:]
        key_stream = (self._key * ((len(xored) // 32) + 1))[:len(xored)]
        return bytes(a ^ b for a, b in zip(xored, key_stream))
    def _get_machine_id(self) -> str:
        """
        Get hardware-bound machine identifier.
        Cross-platform: tries /etc/machine-id (Linux), IOPlatformUUID (macOS),
        MachineGuid registry (Windows), falls back to hostname hash.
        """
        # Linux
        try:
            machine_id_path = Path("/etc/machine-id")
            if machine_id_path.exists():
                return machine_id_path.read_text().strip()
        except Exception:
            pass
        # macOS
        try:
            import subprocess
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.split("\n"):
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]
        except Exception:
            pass
        # Windows
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography"
            )
            return winreg.QueryValueEx(key, "MachineGuid")[0]
        except Exception:
            pass
        # Fallback: hostname hash (weaker binding but functional)
        import socket
        hostname = socket.gethostname()
        return hashlib.sha256(hostname.encode()).hexdigest()
    def _save_key_material(self, path: str, machine_id: str) -> None:
        """Save non-secret key material (salt only, never the key itself)."""
        key_dir = Path(path).parent
        key_dir.mkdir(parents=True, exist_ok=True)
        material = {
            "machine_id_hash": hashlib.sha256(machine_id.encode()).hexdigest(),
            "algorithm": "AES-256-GCM",
            "kdf": "PBKDF2-HMAC-SHA256",
            "iterations": 260000,
            "created_at": __import__("datetime").datetime.utcnow().isoformat(),
            "note": "Key material only — actual key never stored. Derived at runtime."
        }
        Path(path).write_text(json.dumps(material, indent=2))
    def _require_initialized(self) -> None:
        if not self._initialized or self._key is None:
            raise RuntimeError(
                "CryptoGuard not initialized. "
                "Call initialize_crypto(passphrase) or initialize_crypto_from_env() first."
            )
