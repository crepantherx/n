from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .config_store import REPO_ROOT
from .runtime import data_root, is_cloud_runtime

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SESSION_COOKIE = "naukri_session"
SESSION_TTL_SECONDS = 86400 * 30
PBKDF2_ROUNDS = 260_000


def normalize_email(value: str) -> str:
    email = (value or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address")
    return email


def safe_user_slug(email: str) -> str:
    normalized = normalize_email(email)
    slug = re.sub(r"[^a-z0-9_.@-]+", "_", normalized)
    slug = slug.strip("._-") or "user"
    if slug in {".", ".."} or ".." in slug:
        slug = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return slug


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    value = value.strip()
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password cannot be empty")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${_b64url(salt)}${_b64url(dk)}"


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, rounds_s, salt_s, digest_s = stored.split("$", 3)
            salt = _b64url_decode(salt_s)
            expected = _b64url_decode(digest_s)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds_s))
            return hmac.compare_digest(actual, expected)
        except Exception:
            return False
    # Legacy plaintext support so older local installs can be migrated after a successful login.
    return hmac.compare_digest(password, stored)


@dataclass
class AuthResult:
    email: str
    created: bool = False
    migrated: bool = False


class AuthStore:
    def __init__(self, repo_root: Path = REPO_ROOT):
        self.repo_root = Path(repo_root)
        self.data_dir = data_root(self.repo_root)
        self.users_file = self.data_dir / "users.json"
        self.legacy_users_file = self.repo_root / "backend" / "users.json"
        self.secret_file = self.data_dir / ".session_secret"

    def _ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            if not path.exists():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        self._ensure_dirs()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    def _env_users(self) -> dict[str, dict[str, Any]]:
        """Users configured through environment variables.

        This is primarily for Vercel/serverless deployments where writing a
        persistent users.json file is not available. Local installs still use
        data/users.json exactly as before unless these optional variables are set.
        """
        users: dict[str, dict[str, Any]] = {}

        allowed_google = os.getenv("GOOGLE_ALLOWED_EMAILS") or os.getenv("NAUKRI_GOOGLE_ALLOWED_EMAILS") or ""
        for item in allowed_google.split(","):
            raw = item.strip()
            if not raw:
                continue
            try:
                email = normalize_email(raw)
            except Exception:
                continue
            users[email] = {
                "password_hash": "",
                "google": True,
                "created_at": None,
                "source": "env",
            }

        admin_email_raw = os.getenv("NAUKRI_ADMIN_EMAIL") or os.getenv("ADMIN_EMAIL") or ""
        if admin_email_raw:
            try:
                email = normalize_email(admin_email_raw)
            except Exception:
                email = ""
            if email:
                password_hash = os.getenv("NAUKRI_ADMIN_PASSWORD_HASH", "").strip()
                password_plain = os.getenv("NAUKRI_ADMIN_PASSWORD", "")
                users[email] = {
                    "password_hash": password_hash,
                    "google": users.get(email, {}).get("google", False),
                    "created_at": None,
                    "source": "env",
                }
                if password_plain:
                    users[email]["_env_password"] = password_plain

        return users

    def load_users(self) -> dict[str, dict[str, Any]]:
        env_users = self._env_users()
        raw = self._read_json(self.users_file)
        if not raw:
            raw = self._read_json(self.legacy_users_file)

        users: dict[str, dict[str, Any]] = {}
        changed = False
        for email_raw, record_raw in raw.items():
            try:
                email = normalize_email(email_raw)
            except Exception:
                changed = True
                continue

            if isinstance(record_raw, str):
                users[email] = {
                    "password_hash": record_raw,
                    "google": False,
                    "created_at": None,
                    "legacy_plaintext": not record_raw.startswith("pbkdf2_sha256$"),
                }
                changed = True
            elif isinstance(record_raw, dict):
                record = dict(record_raw)
                if "password" in record and "password_hash" not in record:
                    record["password_hash"] = str(record.pop("password") or "")
                    record["legacy_plaintext"] = not str(record["password_hash"]).startswith("pbkdf2_sha256$")
                    changed = True
                record.setdefault("password_hash", "")
                record.setdefault("google", False)
                record.setdefault("created_at", None)
                users[email] = record
            else:
                changed = True

        # Environment users override file users so Vercel deployments can be
        # administered entirely through encrypted project environment variables.
        users.update(env_users)

        if changed and users and not is_cloud_runtime():
            self._write_json(self.users_file, {k: v for k, v in users.items() if v.get("source") != "env"})
        return users

    def save_users(self, users: dict[str, dict[str, Any]]) -> None:
        clean: dict[str, dict[str, Any]] = {}
        for email, record in users.items():
            clean[normalize_email(email)] = {
                k: v for k, v in dict(record).items() if k not in {"legacy_plaintext", "_env_password", "source"}
            }
        self._write_json(self.users_file, clean)

    def list_users(self) -> list[str]:
        return sorted(self.load_users().keys())

    def has_users(self) -> bool:
        return bool(self.load_users())

    def create_user(self, email: str, password: Optional[str] = None, *, google: bool = False) -> None:
        email = normalize_email(email)
        users = self.load_users()
        if email in users:
            raise ValueError("User already exists")
        users[email] = {
            "password_hash": hash_password(password) if password else "",
            "google": bool(google),
            "created_at": int(time.time()),
        }
        self.save_users(users)

    def authenticate_password(self, email: str, password: str) -> Optional[AuthResult]:
        email = normalize_email(email)
        password = password or ""
        users = self.load_users()

        if not users:
            if is_cloud_runtime():
                raise ValueError("Set NAUKRI_ADMIN_EMAIL and NAUKRI_ADMIN_PASSWORD in Vercel Environment Variables before logging in")
            if os.getenv("NAUKRI_DISABLE_FIRST_RUN_SIGNUP", "").lower() in {"1", "true", "yes"}:
                return None
            if len(password) < 8:
                raise ValueError("First-run admin password must be at least 8 characters")
            self.create_user(email, password)
            return AuthResult(email=email, created=True)

        record = users.get(email)
        if not record:
            return None
        if record.get("_env_password") is not None:
            if not hmac.compare_digest(password, str(record.get("_env_password") or "")):
                return None
            return AuthResult(email=email)

        stored = str(record.get("password_hash") or "")
        if not verify_password(password, stored):
            return None

        migrated = False
        if record.get("source") != "env" and not stored.startswith("pbkdf2_sha256$"):
            record["password_hash"] = hash_password(password)
            record.pop("legacy_plaintext", None)
            users[email] = record
            self.save_users(users)
            migrated = True
        return AuthResult(email=email, migrated=migrated)

    def authenticate_google_email(self, email: str) -> Optional[AuthResult]:
        email = normalize_email(email)
        users = self.load_users()
        if not users:
            if is_cloud_runtime():
                raise ValueError("Set GOOGLE_ALLOWED_EMAILS or NAUKRI_ADMIN_EMAIL in Vercel Environment Variables before using Google login")
            self.create_user(email, None, google=True)
            return AuthResult(email=email, created=True)
        record = users.get(email)
        if not record:
            return None
        if not record.get("google", False):
            if record.get("source") == "env":
                return None
            # Local-password users may also use Google only when the address matches.
            record["google"] = True
            users[email] = record
            self.save_users(users)
        return AuthResult(email=email)

    def _secret(self) -> bytes:
        env_secret = os.getenv("NAUKRI_SECRET_KEY", "").strip()
        if env_secret:
            return env_secret.encode("utf-8")
        if is_cloud_runtime():
            seed = (
                os.getenv("NAUKRI_ADMIN_PASSWORD_HASH")
                or os.getenv("NAUKRI_ADMIN_PASSWORD")
                or os.getenv("GOOGLE_CLIENT_ID")
                or os.getenv("VERCEL_URL")
                or "naukri-cloud-session"
            )
            return hashlib.sha256(("naukri-session:" + seed).encode("utf-8")).hexdigest().encode("utf-8")
        self._ensure_dirs()
        if not self.secret_file.exists():
            self.secret_file.write_text(secrets.token_urlsafe(48), encoding="utf-8")
            try:
                os.chmod(self.secret_file, 0o600)
            except Exception:
                pass
        return self.secret_file.read_text(encoding="utf-8").strip().encode("utf-8")

    def create_session(self, email: str, *, ttl_seconds: int = SESSION_TTL_SECONDS) -> str:
        email = normalize_email(email)
        exp = int(time.time() + ttl_seconds)
        payload = f"{email}|{exp}"
        sig = hmac.new(self._secret(), payload.encode("utf-8"), hashlib.sha256).digest()
        return f"v1.{_b64url(payload.encode('utf-8'))}.{_b64url(sig)}"

    def verify_session(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        token = token.strip().strip('"')
        try:
            if not token.startswith("v1."):
                return None
            _, payload_s, sig_s = token.split(".", 2)
            payload = _b64url_decode(payload_s).decode("utf-8")
            expected_sig = hmac.new(self._secret(), payload.encode("utf-8"), hashlib.sha256).digest()
            supplied_sig = _b64url_decode(sig_s)
            if not hmac.compare_digest(expected_sig, supplied_sig):
                return None
            email, exp_s = payload.rsplit("|", 1)
            if int(exp_s) < int(time.time()):
                return None
            email = normalize_email(email)
            if email not in self.load_users():
                return None
            return email
        except Exception:
            return None
