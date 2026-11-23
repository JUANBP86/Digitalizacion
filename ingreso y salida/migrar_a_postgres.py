import sqlite3
import sys

from db import SQLITE_SOURCE_PATH, db_connection, init_db
from psycopg import Error as PostgresError


TABLES = {
    "empleados": "documento, nombre, area, cargo, activo, creado_en",
    "cuentas_admin": "usuario, password_hash, creado_en",
    "salidas_personal": (
        "id, documento_empleado, salida, regreso, motivo, destino, firma, no_regresa"
    ),
}


def migrar() -> None:
    if not SQLITE_SOURCE_PATH.is_file():
        raise FileNotFoundError(
            f"No se encontró la base SQLite de origen: {SQLITE_SOURCE_PATH}"
        )

    init_db()
    with sqlite3.connect(SQLITE_SOURCE_PATH) as origen:
        origen.row_factory = sqlite3.Row
        with db_connection() as destino:
            cantidades_destino = {
                tabla: destino.execute(
                    f"SELECT COUNT(*) AS cantidad FROM {tabla}"
                ).fetchone()["cantidad"]
                for tabla in TABLES
            }
            if any(cantidades_destino.values()):
                raise RuntimeError(
                    "La migración se detuvo porque la base PostgreSQL ya contiene "
                    "datos. No se modificó ningún registro."
                )

            cantidades_origen: dict[str, int] = {}
            for tabla, columnas in TABLES.items():
                cursor_origen = origen.execute(
                    f"SELECT {columnas} FROM {tabla}"
                )
                cantidad = 0
                columnas_lista = columnas.split(", ")
                placeholders = ", ".join(["%s"] * len(columnas_lista))
                insert = (
                    f"INSERT INTO {tabla} ({columnas}) VALUES ({placeholders})"
                )
                with destino.cursor() as cursor_destino:
                    while filas := cursor_origen.fetchmany(500):
                        valores = [tuple(fila) for fila in filas]
                        cursor_destino.executemany(insert, valores)
                        cantidad += len(valores)
                cantidades_origen[tabla] = cantidad

            destino.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('salidas_personal', 'id'),
                    COALESCE(MAX(id), 1),
                    MAX(id) IS NOT NULL
                )
                FROM salidas_personal
                """
            )

    print(f"Migración completada desde: {SQLITE_SOURCE_PATH}")
    for tabla, cantidad in cantidades_origen.items():
        print(f"{tabla}: {cantidad} registros")


if __name__ == "__main__":
    try:
        migrar()
    except (OSError, sqlite3.Error, PostgresError, RuntimeError) as error:
        print(f"Error de migración: {error}", file=sys.stderr)
        sys.exit(1)
