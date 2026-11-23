import hashlib
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from werkzeug.security import check_password_hash

SSO_COOKIE_NAME = "gotuplas_sso"
SSO_SESSION_SECONDS = 8 * 60 * 60


def _database_path() -> Path:
    configured = os.environ.get("GOTUPLAS_SSO_DB_PATH")
    if configured:
        return Path(configured)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "GOTUPLAS" / "shared_sso.db"
    return Path.home() / "AppData" / "Local" / "GOTUPLAS" / "shared_sso.db"


@contextmanager
def sso_connection() -> Iterator[sqlite3.Connection]:
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_sso_db() -> None:
    with sso_connection() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sso_accounts (
                usuario TEXT PRIMARY KEY COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                rol_visitantes TEXT CHECK (
                    rol_visitantes IS NULL
                    OR rol_visitantes IN ('recepcion', 'administrador')
                ),
                rol_ingresos TEXT CHECK (
                    rol_ingresos IS NULL OR rol_ingresos IN ('lectura', 'admin')
                ),
                creado_en TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sso_sessions (
                token_hash TEXT PRIMARY KEY,
                usuario TEXT NOT NULL REFERENCES sso_accounts(usuario) ON DELETE CASCADE,
                expira_en INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sso_migrations (
                source TEXT PRIMARY KEY,
                completed_en TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_sso_sessions_expiry ON sso_sessions(expira_en)"
        )


def migrate_legacy_accounts(
    source: str, accounts: list[dict[str, Any]]
) -> None:
    if source not in {"visitantes", "ingresos"}:
        raise ValueError("Origen de cuentas SSO no válido.")

    with sso_connection() as connection:
        if connection.execute(
            "SELECT 1 FROM sso_migrations WHERE source = ?",
            (source,),
        ).fetchone():
            return
        for account in accounts:
            username = str(account["usuario"]).strip()
            if not username:
                continue
            password_hash = str(account["password_hash"])
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if source == "visitantes":
                visitor_role = str(account["rol"])
                attendance_role = (
                    "admin" if visitor_role == "administrador" else "lectura"
                )
                connection.execute(
                    """
                    INSERT INTO sso_accounts
                        (usuario, password_hash, rol_visitantes, rol_ingresos, creado_en)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(usuario) DO UPDATE SET
                        password_hash = excluded.password_hash,
                        rol_visitantes = excluded.rol_visitantes,
                        rol_ingresos = COALESCE(
                            sso_accounts.rol_ingresos, excluded.rol_ingresos
                        )
                    """,
                    (username, password_hash, visitor_role, attendance_role, now),
                )
            else:
                attendance_role = str(account["rol"])
                connection.execute(
                    """
                    INSERT INTO sso_accounts
                        (usuario, password_hash, rol_visitantes, rol_ingresos, creado_en)
                    VALUES (?, ?, NULL, ?, ?)
                    ON CONFLICT(usuario) DO UPDATE SET
                        rol_ingresos = COALESCE(
                            sso_accounts.rol_ingresos, excluded.rol_ingresos
                        )
                    """,
                    (username, password_hash, attendance_role, now),
                )
        connection.execute(
            "INSERT INTO sso_migrations (source, completed_en) VALUES (?, ?)",
            (source, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


def get_account(usuario: str) -> dict[str, Any] | None:
    with sso_connection() as connection:
        row = connection.execute(
            """
            SELECT usuario, password_hash, rol_visitantes, rol_ingresos, creado_en
            FROM sso_accounts
            WHERE usuario = ? COLLATE NOCASE
            """,
            (usuario.strip(),),
        ).fetchone()
    return dict(row) if row is not None else None


def authenticate(usuario: str, clave: str) -> dict[str, Any] | None:
    account = get_account(usuario)
    if account is None or not check_password_hash(account["password_hash"], clave):
        return None
    if not account["rol_visitantes"] and not account["rol_ingresos"]:
        return None
    return account


def create_account(
    usuario: str,
    password_hash: str,
    visitor_role: str | None,
    attendance_role: str | None,
    allow_existing_without_visitor_role: bool = False,
) -> bool:
    username = usuario.strip()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sso_connection() as connection:
        existing = connection.execute(
            "SELECT rol_visitantes FROM sso_accounts WHERE usuario = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO sso_accounts
                    (usuario, password_hash, rol_visitantes, rol_ingresos, creado_en)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, password_hash, visitor_role, attendance_role, now),
            )
            return True
        if (
            not allow_existing_without_visitor_role
            or visitor_role is None
            or existing["rol_visitantes"] is not None
        ):
            return False
        connection.execute(
            """
            UPDATE sso_accounts
            SET password_hash = ?, rol_visitantes = ?,
                rol_ingresos = COALESCE(rol_ingresos, ?)
            WHERE usuario = ? COLLATE NOCASE
            """,
            (password_hash, visitor_role, attendance_role, username),
        )
        return True


def update_password(usuario: str, password_hash: str) -> bool:
    with sso_connection() as connection:
        cursor = connection.execute(
            "UPDATE sso_accounts SET password_hash = ? WHERE usuario = ? COLLATE NOCASE",
            (password_hash, usuario.strip()),
        )
        if cursor.rowcount:
            connection.execute(
                "DELETE FROM sso_sessions WHERE usuario = ? COLLATE NOCASE",
                (usuario.strip(),),
            )
    return cursor.rowcount == 1


def has_role(application: str, role: str | None = None) -> bool:
    column = {
        "visitantes": "rol_visitantes",
        "ingresos": "rol_ingresos",
    }.get(application)
    if column is None:
        raise ValueError("Aplicación SSO no válida.")
    query = f"SELECT 1 FROM sso_accounts WHERE {column} IS NOT NULL"
    parameters: tuple[str, ...] = ()
    if role is not None:
        query += f" AND {column} = ?"
        parameters = (role,)
    with sso_connection() as connection:
        return connection.execute(query + " LIMIT 1", parameters).fetchone() is not None


def list_accounts(application: str) -> list[dict[str, Any]]:
    column = {
        "visitantes": "rol_visitantes",
        "ingresos": "rol_ingresos",
    }.get(application)
    if column is None:
        raise ValueError("Aplicación SSO no válida.")
    with sso_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT usuario, {column} AS rol, rol_visitantes, rol_ingresos,
                   datetime(creado_en) AS creado_en
            FROM sso_accounts
            WHERE {column} IS NOT NULL
            ORDER BY {column}, usuario
            """
        ).fetchall()
    accounts = []
    for row in rows:
        account = dict(row)
        account["creado_en"] = datetime.fromisoformat(account["creado_en"])
        accounts.append(account)
    return accounts


def delete_visitor_role(usuario: str) -> str | None:
    with sso_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        account = connection.execute(
            """
            SELECT rol_visitantes, rol_ingresos
            FROM sso_accounts WHERE usuario = ? COLLATE NOCASE
            """,
            (usuario.strip(),),
        ).fetchone()
        if account is None:
            return None
        role = account["rol_visitantes"]
        if role is None:
            return None
        count = connection.execute(
            "SELECT COUNT(*) FROM sso_accounts WHERE rol_visitantes = ?",
            (role,),
        ).fetchone()[0]
        if count <= 1:
            return None
        if account["rol_ingresos"] is None:
            connection.execute(
                "DELETE FROM sso_accounts WHERE usuario = ? COLLATE NOCASE",
                (usuario.strip(),),
            )
        else:
            connection.execute(
                """
                UPDATE sso_accounts SET rol_visitantes = NULL
                WHERE usuario = ? COLLATE NOCASE
                """,
                (usuario.strip(),),
            )
        return str(role)


def create_session(usuario: str) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires = int(datetime.now(timezone.utc).timestamp()) + SSO_SESSION_SECONDS
    with sso_connection() as connection:
        connection.execute(
            "DELETE FROM sso_sessions WHERE expira_en <= ?",
            (int(datetime.now(timezone.utc).timestamp()),),
        )
        connection.execute(
            "INSERT INTO sso_sessions (token_hash, usuario, expira_en) VALUES (?, ?, ?)",
            (token_hash, usuario, expires),
        )
    return token


def get_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = int(datetime.now(timezone.utc).timestamp())
    with sso_connection() as connection:
        row = connection.execute(
            """
            SELECT a.usuario, a.rol_visitantes, a.rol_ingresos
            FROM sso_sessions s
            JOIN sso_accounts a ON a.usuario = s.usuario
            WHERE s.token_hash = ? AND s.expira_en > ?
            """,
            (token_hash, now),
        ).fetchone()
    return dict(row) if row is not None else None


def revoke_session(token: str | None) -> None:
    if not token:
        return
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with sso_connection() as connection:
        connection.execute(
            "DELETE FROM sso_sessions WHERE token_hash = ?",
            (token_hash,),
        )
