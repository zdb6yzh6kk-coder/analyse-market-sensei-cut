from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Optional, Union

import duckdb


logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PBKDF2_ITERATIONS = 220_000
DEFAULT_RATE_LIMIT = {
    "enabled": True,
    "window_minutes": 15,
    "password_max_failures": 5,
    "two_factor_max_failures": 5,
    "verification_max_failures": 5,
    "registration_max_attempts": 3,
    "two_factor_send_max_attempts": 3,
    "password_reset_send_max_attempts": 3,
    "password_reset_max_failures": 5,
}


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    message: str
    email: Optional[str] = None
    verification_code: Optional[str] = None


class AuthStore:
    def __init__(self, database_path: Union[str, Path] = "data/auth.duckdb") -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        con = duckdb.connect(str(self.database_path))
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    email VARCHAR PRIMARY KEY,
                    password_hash VARCHAR NOT NULL,
                    salt VARCHAR NOT NULL,
                    is_verified BOOLEAN NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    verified_at TIMESTAMP,
                    last_login_at TIMESTAMP
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS verification_codes (
                    email VARCHAR NOT NULL,
                    code_hash VARCHAR NOT NULL,
                    salt VARCHAR NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    used_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS passkey_credentials (
                    email VARCHAR NOT NULL,
                    credential_id VARCHAR NOT NULL,
                    public_key TEXT NOT NULL,
                    sign_count BIGINT DEFAULT 0,
                    transports VARCHAR,
                    enabled BOOLEAN NOT NULL DEFAULT false,
                    created_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (email, credential_id)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS two_factor_codes (
                    email VARCHAR NOT NULL,
                    code_hash VARCHAR NOT NULL,
                    salt VARCHAR NOT NULL,
                    purpose VARCHAR NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    used_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_attempts (
                    email VARCHAR NOT NULL,
                    purpose VARCHAR NOT NULL,
                    success BOOLEAN NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )
        finally:
            con.close()

    def register_user(
        self,
        email: str,
        password: str,
        allowed_emails: list[str],
        code_minutes: int,
        rate_limit: Optional[dict] = None,
    ) -> AuthResult:
        normalized = normalize_email(email)
        validation = validate_email_and_password(normalized, password)
        if validation:
            return AuthResult(False, validation)
        settings = rate_limit_settings(rate_limit)
        if self.too_many_recent_attempts(
            normalized,
            "registration",
            int(settings["registration_max_attempts"]),
            int(settings["window_minutes"]),
        ):
            return AuthResult(False, "Zu viele Registrierungsversuche. Bitte spaeter erneut versuchen.")
        if allowed_emails and normalized not in [item.lower() for item in allowed_emails]:
            self.record_auth_attempt(normalized, "registration", False)
            return AuthResult(False, "Diese E-Mail ist nicht fuer diese App freigegeben.")

        password_salt = create_salt()
        password_hash = hash_secret(password, password_salt)
        code = create_verification_code()
        code_salt = create_salt()
        code_hash = hash_secret(code, code_salt)
        now = datetime.now()
        expires_at = now + timedelta(minutes=code_minutes)

        con = duckdb.connect(str(self.database_path))
        try:
            existing = con.execute(
                "SELECT email, is_verified FROM users WHERE email = ?",
                [normalized],
            ).fetchone()
            if existing and existing[1]:
                self._record_auth_attempt(con, normalized, "registration", False)
                return AuthResult(False, "Diese E-Mail ist bereits registriert.")

            if existing:
                con.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, salt = ?, is_verified = false, verified_at = NULL
                    WHERE email = ?
                    """,
                    [password_hash, password_salt, normalized],
                )
            else:
                con.execute(
                    """
                    INSERT INTO users VALUES (?, ?, ?, false, ?, NULL, NULL)
                    """,
                    [normalized, password_hash, password_salt, now],
                )

            con.execute(
                """
                INSERT INTO verification_codes VALUES (?, ?, ?, ?, NULL, ?)
                """,
                [normalized, code_hash, code_salt, expires_at, now],
            )
        finally:
            con.close()

        self.record_auth_attempt(normalized, "registration", True)
        return AuthResult(
            True,
            "Registrierung vorbereitet. Bitte bestaetige deine E-Mail.",
            email=normalized,
            verification_code=code,
        )

    def verify_email(self, email: str, code: str, rate_limit: Optional[dict] = None) -> AuthResult:
        normalized = normalize_email(email)
        settings = rate_limit_settings(rate_limit)
        if self.too_many_recent_failures(
            normalized,
            "email_verification",
            int(settings["verification_max_failures"]),
            int(settings["window_minutes"]),
        ):
            return AuthResult(False, "Zu viele falsche Codes. Bitte spaeter erneut versuchen.")

        con = duckdb.connect(str(self.database_path))
        try:
            row = con.execute(
                """
                SELECT code_hash, salt, expires_at
                FROM verification_codes
                WHERE email = ? AND used_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [normalized],
            ).fetchone()
            if not row:
                self._record_auth_attempt(con, normalized, "email_verification", False)
                return AuthResult(False, "Kein offener Bestaetigungscode gefunden.")

            code_hash, salt, expires_at = row
            if datetime.now() > expires_at:
                self._record_auth_attempt(con, normalized, "email_verification", False)
                return AuthResult(False, "Der Bestaetigungscode ist abgelaufen.")
            if not hmac.compare_digest(hash_secret(code.strip(), salt), code_hash):
                self._record_auth_attempt(con, normalized, "email_verification", False)
                return AuthResult(False, "Der Bestaetigungscode ist falsch.")

            now = datetime.now()
            con.execute(
                "UPDATE users SET is_verified = true, verified_at = ? WHERE email = ?",
                [now, normalized],
            )
            con.execute(
                """
                UPDATE verification_codes
                SET used_at = ?
                WHERE email = ? AND used_at IS NULL
                """,
                [now, normalized],
            )
        finally:
            con.close()
        self.record_auth_attempt(normalized, "email_verification", True)
        return AuthResult(True, "E-Mail bestaetigt. Du kannst dich jetzt anmelden.", normalized)

    def login(self, email: str, password: str, rate_limit: Optional[dict] = None) -> AuthResult:
        result = self.verify_password(email, password, rate_limit=rate_limit)
        if not result.ok:
            return result
        self.mark_login_success(result.email or email)
        return AuthResult(True, "Login erfolgreich.", result.email)

    def verify_password(self, email: str, password: str, rate_limit: Optional[dict] = None) -> AuthResult:
        normalized = normalize_email(email)
        settings = rate_limit_settings(rate_limit)
        if self.too_many_recent_failures(
            normalized,
            "password",
            int(settings["password_max_failures"]),
            int(settings["window_minutes"]),
        ):
            return AuthResult(False, "Zu viele falsche Passwortversuche. Bitte spaeter erneut versuchen.")

        con = duckdb.connect(str(self.database_path))
        try:
            row = con.execute(
                """
                SELECT password_hash, salt, is_verified
                FROM users
                WHERE email = ?
                """,
                [normalized],
            ).fetchone()
            if not row:
                self._record_auth_attempt(con, normalized, "password", False)
                return AuthResult(False, "E-Mail oder Passwort ist falsch.")

            password_hash, salt, is_verified = row
            if not hmac.compare_digest(hash_secret(password, salt), password_hash):
                self._record_auth_attempt(con, normalized, "password", False)
                return AuthResult(False, "E-Mail oder Passwort ist falsch.")
            if not is_verified:
                self._record_auth_attempt(con, normalized, "password", False)
                return AuthResult(False, "Bitte bestaetige zuerst deine E-Mail.")
        finally:
            con.close()
        self.record_auth_attempt(normalized, "password", True)
        return AuthResult(True, "Passwort bestaetigt.", normalized)

    def mark_login_success(self, email: str) -> None:
        normalized = normalize_email(email)
        con = duckdb.connect(str(self.database_path))
        try:
            con.execute(
                "UPDATE users SET last_login_at = ? WHERE email = ?",
                [datetime.now(), normalized],
            )
        finally:
            con.close()

    def create_password_reset_code(
        self,
        email: str,
        code_minutes: int,
        rate_limit: Optional[dict] = None,
    ) -> AuthResult:
        normalized = normalize_email(email)
        if not EMAIL_RE.match(normalized):
            return AuthResult(False, "Bitte gib eine gueltige E-Mail-Adresse ein.")

        settings = rate_limit_settings(rate_limit)
        max_attempts = int(
            settings.get(
                "password_reset_send_max_attempts",
                settings.get("two_factor_send_max_attempts", 3),
            )
        )
        if self.too_many_recent_attempts(
            normalized,
            "password_reset_send",
            max_attempts,
            int(settings["window_minutes"]),
        ):
            return AuthResult(False, "Zu viele Passwort-Reset-Anforderungen. Bitte spaeter erneut versuchen.")

        now = datetime.now()
        con = duckdb.connect(str(self.database_path))
        try:
            existing = con.execute(
                """
                SELECT email, is_verified
                FROM users
                WHERE email = ?
                """,
                [normalized],
            ).fetchone()
            if not existing or not existing[1]:
                self._record_auth_attempt(con, normalized, "password_reset_send", False)
                return AuthResult(
                    True,
                    "Wenn die E-Mail registriert ist, wurde ein Reset-Code vorbereitet.",
                    email=normalized,
                )

            code = create_verification_code()
            salt = create_salt()
            code_hash = hash_secret(code, salt)
            expires_at = now + timedelta(minutes=code_minutes)
            con.execute(
                """
                INSERT INTO two_factor_codes VALUES (?, ?, ?, ?, ?, NULL, ?)
                """,
                [normalized, code_hash, salt, "password_reset", expires_at, now],
            )
            self._record_auth_attempt(con, normalized, "password_reset_send", True)
        finally:
            con.close()

        return AuthResult(
            True,
            "Passwort-Reset-Code erstellt.",
            email=normalized,
            verification_code=code,
        )

    def reset_password(
        self,
        email: str,
        code: str,
        new_password: str,
        rate_limit: Optional[dict] = None,
    ) -> AuthResult:
        normalized = normalize_email(email)
        validation = validate_email_and_password(normalized, new_password)
        if validation:
            return AuthResult(False, validation)

        settings = rate_limit_settings(rate_limit)
        max_failures = int(
            settings.get(
                "password_reset_max_failures",
                settings.get("verification_max_failures", 5),
            )
        )
        if self.too_many_recent_failures(
            normalized,
            "password_reset",
            max_failures,
            int(settings["window_minutes"]),
        ):
            return AuthResult(False, "Zu viele falsche Reset-Codes. Bitte spaeter erneut versuchen.")

        con = duckdb.connect(str(self.database_path))
        try:
            row = con.execute(
                """
                SELECT code_hash, salt, expires_at
                FROM two_factor_codes
                WHERE email = ? AND purpose = 'password_reset' AND used_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [normalized],
            ).fetchone()
            if not row:
                self._record_auth_attempt(con, normalized, "password_reset", False)
                return AuthResult(False, "Kein offener Reset-Code gefunden.")

            code_hash, salt, expires_at = row
            if datetime.now() > expires_at:
                self._record_auth_attempt(con, normalized, "password_reset", False)
                return AuthResult(False, "Der Reset-Code ist abgelaufen.")
            if not hmac.compare_digest(hash_secret(code.strip(), salt), code_hash):
                self._record_auth_attempt(con, normalized, "password_reset", False)
                return AuthResult(False, "Der Reset-Code ist falsch.")

            password_salt = create_salt()
            password_hash = hash_secret(new_password, password_salt)
            now = datetime.now()
            con.execute(
                """
                UPDATE users
                SET password_hash = ?, salt = ?, is_verified = true, verified_at = COALESCE(verified_at, ?)
                WHERE email = ?
                """,
                [password_hash, password_salt, now, normalized],
            )
            con.execute(
                """
                UPDATE two_factor_codes
                SET used_at = ?
                WHERE email = ? AND purpose = 'password_reset' AND used_at IS NULL
                """,
                [now, normalized],
            )
            self._record_auth_attempt(con, normalized, "password_reset", True)
        finally:
            con.close()

        return AuthResult(True, "Passwort wurde aktualisiert. Du kannst dich jetzt anmelden.", normalized)

    def create_two_factor_code(
        self,
        email: str,
        code_minutes: int,
        purpose: str = "login",
        rate_limit: Optional[dict] = None,
    ) -> AuthResult:
        normalized = normalize_email(email)
        settings = rate_limit_settings(rate_limit)
        if self.too_many_recent_attempts(
            normalized,
            "two_factor_send",
            int(settings["two_factor_send_max_attempts"]),
            int(settings["window_minutes"]),
        ):
            return AuthResult(False, "Zu viele 2FA-Code-Anforderungen. Bitte spaeter erneut versuchen.")

        code = create_verification_code()
        salt = create_salt()
        code_hash = hash_secret(code, salt)
        now = datetime.now()
        expires_at = now + timedelta(minutes=code_minutes)

        con = duckdb.connect(str(self.database_path))
        try:
            con.execute(
                """
                INSERT INTO two_factor_codes VALUES (?, ?, ?, ?, ?, NULL, ?)
                """,
                [normalized, code_hash, salt, purpose, expires_at, now],
            )
        finally:
            con.close()

        self.record_auth_attempt(normalized, "two_factor_send", True)
        return AuthResult(
            True,
            "Zwei-Faktor-Code erstellt.",
            email=normalized,
            verification_code=code,
        )

    def verify_two_factor_code(
        self,
        email: str,
        code: str,
        purpose: str = "login",
        rate_limit: Optional[dict] = None,
    ) -> AuthResult:
        normalized = normalize_email(email)
        settings = rate_limit_settings(rate_limit)
        if self.too_many_recent_failures(
            normalized,
            "two_factor",
            int(settings["two_factor_max_failures"]),
            int(settings["window_minutes"]),
        ):
            return AuthResult(False, "Zu viele falsche 2FA-Codes. Bitte spaeter erneut versuchen.")

        con = duckdb.connect(str(self.database_path))
        try:
            row = con.execute(
                """
                SELECT code_hash, salt, expires_at
                FROM two_factor_codes
                WHERE email = ? AND purpose = ? AND used_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [normalized, purpose],
            ).fetchone()
            if not row:
                self._record_auth_attempt(con, normalized, "two_factor", False)
                return AuthResult(False, "Kein offener Zwei-Faktor-Code gefunden.")

            code_hash, salt, expires_at = row
            if datetime.now() > expires_at:
                self._record_auth_attempt(con, normalized, "two_factor", False)
                return AuthResult(False, "Der Zwei-Faktor-Code ist abgelaufen.")
            if not hmac.compare_digest(hash_secret(code.strip(), salt), code_hash):
                self._record_auth_attempt(con, normalized, "two_factor", False)
                return AuthResult(False, "Der Zwei-Faktor-Code ist falsch.")

            now = datetime.now()
            con.execute(
                """
                UPDATE two_factor_codes
                SET used_at = ?
                WHERE email = ? AND purpose = ? AND used_at IS NULL
                """,
                [now, normalized, purpose],
            )
        finally:
            con.close()
        self.record_auth_attempt(normalized, "two_factor", True)
        return AuthResult(True, "Zwei-Faktor-Code bestaetigt.", normalized)

    def too_many_recent_failures(
        self,
        email: str,
        purpose: str,
        max_failures: int,
        window_minutes: int,
    ) -> bool:
        if max_failures <= 0:
            return False
        return self.recent_attempt_count(
            email,
            purpose,
            window_minutes,
            success=False,
        ) >= max_failures

    def too_many_recent_attempts(
        self,
        email: str,
        purpose: str,
        max_attempts: int,
        window_minutes: int,
    ) -> bool:
        if max_attempts <= 0:
            return False
        return self.recent_attempt_count(email, purpose, window_minutes) >= max_attempts

    def recent_attempt_count(
        self,
        email: str,
        purpose: str,
        window_minutes: int,
        success: Optional[bool] = None,
    ) -> int:
        cutoff = datetime.now() - timedelta(minutes=max(1, int(window_minutes)))
        normalized = normalize_email(email)
        con = duckdb.connect(str(self.database_path))
        try:
            if success is None:
                return int(
                    con.execute(
                        """
                        SELECT COUNT(*)
                        FROM auth_attempts
                        WHERE email = ? AND purpose = ? AND created_at >= ?
                        """,
                        [normalized, purpose, cutoff],
                    ).fetchone()[0]
                )
            return int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM auth_attempts
                    WHERE email = ? AND purpose = ? AND success = ? AND created_at >= ?
                    """,
                    [normalized, purpose, bool(success), cutoff],
                ).fetchone()[0]
            )
        finally:
            con.close()

    def record_auth_attempt(self, email: str, purpose: str, success: bool) -> None:
        normalized = normalize_email(email)
        con = duckdb.connect(str(self.database_path))
        try:
            self._record_auth_attempt(con, normalized, purpose, success)
        finally:
            con.close()

    def _record_auth_attempt(self, con, email: str, purpose: str, success: bool) -> None:
        con.execute(
            """
            INSERT INTO auth_attempts VALUES (?, ?, ?, ?)
            """,
            [normalize_email(email), purpose, bool(success), datetime.now()],
        )

    def passkey_status(self, email: str) -> dict:
        normalized = normalize_email(email)
        con = duckdb.connect(str(self.database_path))
        try:
            count = con.execute(
                """
                SELECT COUNT(*)
                FROM passkey_credentials
                WHERE email = ? AND enabled = true
                """,
                [normalized],
            ).fetchone()[0]
        finally:
            con.close()
        return {
            "prepared": True,
            "enabled_credentials": int(count),
            "message": "Passkey/WebAuthn Storage ist vorbereitet. WebAuthn-UI ist noch nicht aktiv.",
        }


def send_verification_email(email: str, code: str, settings: dict) -> AuthResult:
    return send_auth_code_email(
        email=email,
        code=code,
        settings=settings,
        subject="Analyse Market Sensei Cut - E-Mail bestaetigen",
        intro="Dein Bestaetigungscode fuer Analyse Market Sensei Cut lautet:",
    )


def send_two_factor_email(email: str, code: str, settings: dict) -> AuthResult:
    return send_auth_code_email(
        email=email,
        code=code,
        settings=settings,
        subject="Analyse Market Sensei Cut - Zwei-Faktor-Code",
        intro="Dein Zwei-Faktor-Code fuer Analyse Market Sensei Cut lautet:",
    )


def send_password_reset_email(email: str, code: str, settings: dict) -> AuthResult:
    return send_auth_code_email(
        email=email,
        code=code,
        settings=settings,
        subject="Analyse Market Sensei Cut - Passwort zuruecksetzen",
        intro="Dein Passwort-Reset-Code fuer Analyse Market Sensei Cut lautet:",
    )


def send_auth_code_email(
    email: str,
    code: str,
    settings: dict,
    subject: str,
    intro: str,
) -> AuthResult:
    required = ["host", "port", "username", "password", "sender"]
    missing = [key for key in required if not settings.get(key)]
    if missing:
        return AuthResult(False, f"SMTP ist nicht vollstaendig konfiguriert: {', '.join(missing)}")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings["sender"]
    message["To"] = email
    message.set_content(
        f"{intro}\n\n"
        f"{code}\n\n"
        "Wenn du diese Anmeldung nicht gestartet hast, ignoriere diese E-Mail.\n"
    )

    try:
        if settings.get("use_tls", True):
            with smtplib.SMTP(settings["host"], int(settings["port"]), timeout=20) as smtp:
                smtp.starttls()
                smtp.login(settings["username"], settings["password"])
                smtp.send_message(message)
        else:
            with smtplib.SMTP_SSL(settings["host"], int(settings["port"]), timeout=20) as smtp:
                smtp.login(settings["username"], settings["password"])
                smtp.send_message(message)
    except Exception as exc:
        logger.exception("Could not send verification email")
        return AuthResult(False, f"Bestaetigungs-E-Mail konnte nicht gesendet werden: {exc}")

    return AuthResult(True, "Code-E-Mail wurde gesendet.", email)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_email_and_password(email: str, password: str) -> Optional[str]:
    if not EMAIL_RE.match(email):
        return "Bitte gib eine gueltige E-Mail-Adresse ein."
    if len(password) < 10:
        return "Das Passwort muss mindestens 10 Zeichen lang sein."
    if password.lower() == password or password.upper() == password:
        return "Das Passwort braucht Gross- und Kleinbuchstaben."
    if not any(char.isdigit() for char in password):
        return "Das Passwort braucht mindestens eine Zahl."
    return None


def rate_limit_settings(rate_limit: Optional[dict]) -> dict:
    settings = DEFAULT_RATE_LIMIT.copy()
    if rate_limit:
        settings.update({key: value for key, value in rate_limit.items() if value is not None})
    if not settings.get("enabled", True):
        for key in [
            "password_max_failures",
            "two_factor_max_failures",
            "verification_max_failures",
            "registration_max_attempts",
            "two_factor_send_max_attempts",
            "password_reset_send_max_attempts",
            "password_reset_max_failures",
        ]:
            settings[key] = 0
    return settings


def create_salt() -> str:
    return secrets.token_hex(16)


def create_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_secret(value: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        value.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    )
    return digest.hex()
