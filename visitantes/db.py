import atexit
import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Generator

from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

load_dotenv()

logger = logging.getLogger(__name__)

DatabaseError = psycopg.Error

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def get_conninfo() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    user = os.environ.get("PGUSER", "postgres")
    password = os.environ.get("PGPASSWORD", "")
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    dbname = os.environ.get("PGDATABASE", "visitantes_gotuplas")

    params = {"user": user, "host": host, "port": port, "dbname": dbname}
    if password:
        params["password"] = password
    return psycopg.conninfo.make_conninfo(**params)


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                conninfo = get_conninfo()
                _pool = ConnectionPool(
                    conninfo=conninfo,
                    min_size=1,
                    max_size=10,
                    kwargs={"row_factory": dict_row},
                    open=True,
                )
    return _pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


atexit.register(close_pool)


@contextmanager
def db_connection() -> Generator[psycopg.Connection, None, None]:
    pool = get_pool()
    with pool.connection() as connection:
        with connection.transaction():
            yield connection


def init_db() -> None:
    with db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS visitantes (
                cedula VARCHAR(50) PRIMARY KEY,
                nombre VARCHAR(255) NOT NULL,
                empresa VARCHAR(255) NOT NULL,
                arl VARCHAR(255) NOT NULL,
                eps VARCHAR(255) NOT NULL,
                telefono VARCHAR(50) NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS registros (
                id SERIAL PRIMARY KEY,
                fecha VARCHAR(10) NOT NULL,
                hora_ingreso VARCHAR(10) NOT NULL,
                hora_salida VARCHAR(10),
                empresa VARCHAR(255) NOT NULL,
                nombre VARCHAR(255) NOT NULL,
                cedula VARCHAR(50) NOT NULL,
                arl VARCHAR(255) NOT NULL,
                eps VARCHAR(255) NOT NULL,
                telefono VARCHAR(50) NOT NULL,
                persona_visita VARCHAR(255) NOT NULL,
                equipos TEXT NOT NULL DEFAULT '',
                estado VARCHAR(50) NOT NULL,
                autorizacion_datos INTEGER NOT NULL DEFAULT 0,
                acuerdo_confidencialidad INTEGER NOT NULL DEFAULT 1,
                firma BYTEA,
                categoria VARCHAR(100) NOT NULL DEFAULT 'No especificada'
            )
            """
        )
        connection.execute(
            """
            ALTER TABLE registros
            ADD COLUMN IF NOT EXISTS acuerdo_confidencialidad INTEGER NOT NULL DEFAULT 1
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_registros_estado ON registros (estado)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cuentas_recepcion (
                usuario VARCHAR(100) PRIMARY KEY,
                password_hash VARCHAR(255) NOT NULL,
                rol VARCHAR(20) NOT NULL DEFAULT 'recepcion',
                creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            ALTER TABLE cuentas_recepcion
            ADD COLUMN IF NOT EXISTS rol VARCHAR(20) NOT NULL DEFAULT 'recepcion'
            """
        )


def obtener_visitante(cedula: str) -> dict[str, Any] | None:
    with db_connection() as connection:
        return connection.execute(
            """
            SELECT visitantes.nombre, visitantes.empresa, visitantes.arl,
                   visitantes.eps, visitantes.telefono,
                   (
                       SELECT registros.categoria
                       FROM registros
                       WHERE registros.cedula = visitantes.cedula
                       ORDER BY registros.id DESC
                       LIMIT 1
                   ) AS categoria
            FROM visitantes
            WHERE visitantes.cedula = %s
            """,
            (cedula,),
        ).fetchone()


def obtener_visitantes_activos() -> list[dict[str, Any]]:
    with db_connection() as connection:
        return connection.execute(
            """
            SELECT id, fecha, hora_ingreso, empresa, nombre, cedula, categoria,
                   persona_visita, equipos, acuerdo_confidencialidad
            FROM registros
            WHERE estado = 'ACTIVO'
            ORDER BY id DESC
            """
        ).fetchall()


def obtener_historial(fecha: str | None = None) -> list[dict[str, Any]]:
    with db_connection() as connection:
        consulta = """
            SELECT id, fecha, hora_ingreso, hora_salida, estado, cedula,
                   nombre, empresa, arl, eps, telefono, persona_visita, equipos,
                   categoria,
                   autorizacion_datos,
                   acuerdo_confidencialidad,
                   CASE WHEN firma IS NOT NULL THEN 1 ELSE 0 END AS tiene_firma
            FROM registros
        """
        parametros: tuple[str, ...] = ()
        if fecha is not None:
            consulta += " WHERE fecha = %s"
            parametros = (fecha,)
        consulta += " ORDER BY id DESC"
        return connection.execute(
            consulta,
            parametros,
        ).fetchall()


def obtener_registro(registro_id: int) -> dict[str, Any] | None:
    with db_connection() as connection:
        return connection.execute(
            """
            SELECT id, fecha, hora_ingreso, hora_salida, estado, cedula,
                   nombre, empresa, arl, eps, telefono, persona_visita, equipos,
                   categoria, autorizacion_datos, acuerdo_confidencialidad,
                   firma
            FROM registros
            WHERE id = %s
            """,
            (registro_id,),
        ).fetchone()


def obtener_firma(registro_id: int) -> bytes | None:
    with db_connection() as connection:
        registro = connection.execute(
            "SELECT firma FROM registros WHERE id = %s",
            (registro_id,),
        ).fetchone()
    if registro is None or registro.get("firma") is None:
        return None
    firma_data = registro["firma"]
    if isinstance(firma_data, memoryview):
        return firma_data.tobytes()
    return bytes(firma_data)


def obtener_cuenta_recepcion(usuario: str) -> dict[str, Any] | None:
    with db_connection() as connection:
        return connection.execute(
            """
            SELECT usuario, password_hash, rol
            FROM cuentas_recepcion
            WHERE usuario = %s
            """,
            (usuario,),
        ).fetchone()


def existe_cuenta_recepcion() -> bool:
    with db_connection() as connection:
        return connection.execute(
            "SELECT 1 FROM cuentas_recepcion LIMIT 1"
        ).fetchone() is not None


def crear_cuenta_recepcion(usuario: str, password_hash: str) -> bool:
    with db_connection() as connection:
        if connection.execute(
            "SELECT 1 FROM cuentas_recepcion LIMIT 1"
        ).fetchone():
            return False
        connection.execute(
            """
            INSERT INTO cuentas_recepcion (usuario, password_hash, creado_en)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            """,
            (usuario, password_hash),
        )
    return True


def existe_cuenta_administracion() -> bool:
    with db_connection() as connection:
        return connection.execute(
            "SELECT 1 FROM cuentas_recepcion WHERE rol = 'administrador' LIMIT 1"
        ).fetchone() is not None


def listar_cuentas_recepcion() -> list[dict[str, Any]]:
    with db_connection() as connection:
        return connection.execute(
            """
            SELECT usuario, rol, creado_en
            FROM cuentas_recepcion
            ORDER BY rol, usuario
            """
        ).fetchall()


def crear_usuario_recepcion(
    usuario: str, password_hash: str, rol: str
) -> bool:
    with db_connection() as connection:
        creado = connection.execute(
            """
            INSERT INTO cuentas_recepcion (usuario, password_hash, rol, creado_en)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (usuario) DO NOTHING
            RETURNING usuario
            """,
            (usuario, password_hash, rol),
        ).fetchone()
    return creado is not None


def actualizar_clave_usuario_recepcion(usuario: str, password_hash: str) -> bool:
    with db_connection() as connection:
        actualizado = connection.execute(
            """
            UPDATE cuentas_recepcion
            SET password_hash = %s
            WHERE usuario = %s
            RETURNING usuario
            """,
            (password_hash, usuario),
        ).fetchone()
    return actualizado is not None


def eliminar_usuario_recepcion(usuario: str) -> str | None:
    with db_connection() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(684209135)")
        cuenta = connection.execute(
            "SELECT rol FROM cuentas_recepcion WHERE usuario = %s",
            (usuario,),
        ).fetchone()
        if cuenta is None:
            return None
        cantidad = connection.execute(
            "SELECT COUNT(*) AS cantidad FROM cuentas_recepcion WHERE rol = %s",
            (cuenta["rol"],),
        ).fetchone()["cantidad"]
        if cantidad <= 1:
            return None
        eliminado = connection.execute(
            """
            DELETE FROM cuentas_recepcion
            WHERE usuario = %s
            RETURNING rol
            """,
            (usuario,),
        ).fetchone()
    return eliminado["rol"] if eliminado else None
