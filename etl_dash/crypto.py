"""Envelope encryption for the static dashboard (decrypted in the browser with WebCrypto, see web/crypto.js).

payload = {
  v, kdf: {name: PBKDF2, hash: SHA-256, iterations, salt},
  data:  AES-256-GCM(DEK, json(data))               admin: AES-256-GCM(ASK, json(admin_secrets))
  extra: {data, admin} – test data under its own keys, or random filler of similar shape when there is none
  keys:  three unlabeled wraps in random order: AES-GCM(KEK(pw), key material), AAD bound to the role
         viewer -> DEK; admin -> DEK || ASK; test -> test DEK || test ASK
}
Wraps carry no role label: the role is whichever AAD authenticates, so it cannot be relabeled, and the page
looks the same with or without test data. One salt for all wraps: one key derivation per login attempt.
"""
import base64
import json
import os
import random
import unicodedata

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERATIONS = 600_000            # OWASP 2023 recommendation for PBKDF2-HMAC-SHA256
MIN_PASSWORD_LENGTH = 20        # the ciphertext is public: long passphrases only (e.g. 4–5 random words)
TEST_MIN_PASSWORD_LENGTH = 4    # local / test builds only (explicit opt-in)
ROLES = ("viewer", "admin", "test")


def aad(kind, role=""):
    return f"etl-dash:v2:{kind}{':' + role if role else ''}".encode()


def b64(b):
    return base64.b64encode(b).decode()


def unb64(s):
    return base64.b64decode(s)


def norm_password(pw):
    return unicodedata.normalize("NFC", pw)


def derive(password, salt, iterations=ITERATIONS):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(norm_password(password).encode("utf-8"))


def seal(key, plaintext, ad):
    iv = os.urandom(12)
    return {"iv": b64(iv), "ct": b64(AESGCM(key).encrypt(iv, plaintext, ad))}


def unseal(key, box, ad):
    return AESGCM(key).decrypt(unb64(box["iv"]), unb64(box["ct"]), ad)


def check_passwords(passwords, min_length=MIN_PASSWORD_LENGTH):
    for role, pw in passwords.items():
        if not pw or len(norm_password(pw)) < min_length:
            raise ValueError(f"{role} password must have at least {min_length} characters")
    if len({norm_password(p) for p in passwords.values()}) != len(passwords):
        raise ValueError("all passwords must differ")


PAD = 64 * 1024


def _dump(o):
    """JSON padded with spaces to a multiple of PAD (sizes do not reveal the content or the test mode)."""
    raw = json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return raw + b" " * (-len(raw) % PAD)


def encrypt(data, admin_secrets, viewer_password, admin_password, test=None, iterations=ITERATIONS,
            min_length=MIN_PASSWORD_LENGTH):
    """test = (test_data, test_admin_secrets, test_password) or None."""
    passwords = {"viewer": viewer_password, "admin": admin_password}
    if test:
        passwords["test"] = test[2]
    check_passwords(passwords, min_length)
    salt = os.urandom(16)
    dek, ask, tdek, task = (os.urandom(32) for _ in range(4))
    keks = {role: derive(pw, salt, iterations) for role, pw in passwords.items()}
    if test:
        extra = {"data": seal(tdek, _dump(test[0]), aad("data", "test")), "admin": seal(task, _dump(test[1]), aad("admin", "test"))}
    else:  # filler, indistinguishable from a real block without the key
        extra = {"data": seal(os.urandom(32), os.urandom(PAD), b""), "admin": seal(os.urandom(32), os.urandom(PAD), b"")}
    keys = [seal(keks["viewer"], dek, aad("key", "viewer")), seal(keks["admin"], dek + ask, aad("key", "admin")),
            seal(keks["test"], tdek + task, aad("key", "test")) if test else seal(os.urandom(32), os.urandom(64), b"")]
    random.SystemRandom().shuffle(keys)
    return {
        "v": 2,
        "kdf": {"name": "PBKDF2", "hash": "SHA-256", "iterations": iterations, "salt": b64(salt)},
        "data": seal(dek, _dump(data), aad("data")),
        "admin": seal(ask, _dump(admin_secrets), aad("admin")),
        "extra": extra,
        "keys": keys,
    }


def decrypt(payload, password):
    """Reference implementation of the browser logic (used by tests). -> (role, data, admin_secrets|None)."""
    kdf = payload["kdf"]
    kek = derive(password, unb64(kdf["salt"]), kdf["iterations"])
    for wrap in payload["keys"]:
        for role in ROLES:
            try:
                keys = unseal(kek, wrap, aad("key", role))
            except Exception:
                continue
            if role == "test":
                box, tag = payload["extra"], "test"
            else:
                box, tag = payload, ""
            data = json.loads(unseal(keys[:32], box["data"], aad("data", tag)))
            secrets = json.loads(unseal(keys[32:], box["admin"], aad("admin", tag))) if len(keys) == 64 else None
            return role, data, secrets
    raise ValueError("wrong password")
