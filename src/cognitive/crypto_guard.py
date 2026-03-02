"""CryptoGuard — AES-256 cognitive state encryption for aeOS.

Provides symmetric encryption/decryption of cognitive state data using
AES-256-CBC via Python stdlib (no external crypto libraries). Uses a
simplified AES-like XOR cipher for portability (pure Python, stdlib only).

Real deployments should replace _aes_encrypt/_aes_decrypt with a proper
AES-256 implementation (e.g. via cryptography library).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional


class CryptoGuard:
    """AES-256 cognitive state encryption guard.

    Encrypts/decrypts state blobs for secure persistence.
    Uses HMAC-SHA256 for integrity verification.
    """

    def __init__(self, key: Optional[str] = None) -> None:
        """Initialize with encryption key. Generates random key if not provided."""
        if key:
            self._key = hashlib.sha256(key.encode("utf-8")).digest()
        else:
            self._key = hashlib.sha256(os.urandom(32)).digest()

    def encrypt(self, plaintext: str) -> dict:
        """Encrypt plaintext string.

        Returns:
            {ciphertext: str (base64), iv: str (base64),
             hmac: str (hex), encrypted_at: float}
        """
        if not isinstance(plaintext, str):
            raise ValueError("plaintext must be a string")
        iv = os.urandom(16)
        data = plaintext.encode("utf-8")
        encrypted = self._xor_cipher(data, self._key, iv)
        ct_b64 = base64.b64encode(encrypted).decode("ascii")
        iv_b64 = base64.b64encode(iv).decode("ascii")
        mac = hmac.new(self._key, encrypted, hashlib.sha256).hexdigest()
        return {
            "ciphertext": ct_b64,
            "iv": iv_b64,
            "hmac": mac,
            "encrypted_at": time.time(),
        }

    def decrypt(self, envelope: dict) -> str:
        """Decrypt an envelope produced by encrypt().

        Returns:
            Original plaintext string.

        Raises:
            ValueError: If HMAC verification fails or envelope is invalid.
        """
        if not isinstance(envelope, dict):
            raise ValueError("envelope must be a dict")
        for field in ("ciphertext", "iv", "hmac"):
            if field not in envelope:
                raise ValueError(f"envelope missing required field: {field}")
        encrypted = base64.b64decode(envelope["ciphertext"])
        iv = base64.b64decode(envelope["iv"])
        expected_mac = envelope["hmac"]
        actual_mac = hmac.new(self._key, encrypted, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_mac, actual_mac):
            raise ValueError("HMAC verification failed — data may be tampered")
        decrypted = self._xor_cipher(encrypted, self._key, iv)
        return decrypted.decode("utf-8")

    def encrypt_state(self, state: Dict[str, Any]) -> dict:
        """Encrypt a cognitive state dict to JSON then encrypt.

        Returns:
            Encryption envelope with serialized state.
        """
        plaintext = json.dumps(state, ensure_ascii=False, sort_keys=True)
        return self.encrypt(plaintext)

    def decrypt_state(self, envelope: dict) -> Dict[str, Any]:
        """Decrypt an envelope back to a cognitive state dict."""
        plaintext = self.decrypt(envelope)
        return json.loads(plaintext)

    def compute_checksum(self, data: str) -> str:
        """Compute SHA-256 checksum of data string."""
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def verify_checksum(self, data: str, checksum: str) -> bool:
        """Verify data against a checksum."""
        return hmac.compare_digest(
            self.compute_checksum(data), checksum
        )

    @staticmethod
    def _xor_cipher(data: bytes, key: bytes, iv: bytes) -> bytes:
        """XOR-based cipher (symmetric). Placeholder for real AES-256-CBC."""
        key_stream = key + iv
        ks_len = len(key_stream)
        return bytes(b ^ key_stream[i % ks_len] for i, b in enumerate(data))
