"""
Script de migración de SQLite a PostgreSQL para GOTUPLAS.
Transfiere datos existentes (visitantes, registros con firmas, cuentas)
preservando integridad referencial, IDs e índices.
"""

import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv
import psycopg
from psycopg import conninfo as pg_conninfo
from psycopg import sql

# Cargar variables de .env
load_dotenv()

DB_SQLITE_FILE = Path(__file__).resolve().parent / "visitantes_gotuplas.db"


def parse_pg_target(conninfo_str: str) -> tuple[str, str]:
    """
    Retorna (conninfo_sin_db_apuntando_a_postgres, nombre_db_objetivo).
    """
    try:
        params = pg_conninfo.conninfo_to_dict(conninfo_str)
    except Exception:
        params = {}

    target_dbname = params.get("dbname") or os.environ.get("PGDATABASE", "visitantes_gotuplas")
    root_params = dict(params)
    root_params["dbname"] = "postgres"
    if "user" not in root_params and "PGUSER" in os.environ:
        root_params["user"] = os.environ["PGUSER"]
    if "password" not in root_params and "PGPASSWORD" in os.environ:
        root_params["password"] = os.environ["PGPASSWORD"]
    if "host" not in root_params and "PGHOST" in os.environ:
        root_params["host"] = os.environ["PGHOST"]
    if "port" not in root_params and "PGPORT" in os.environ:
        root_params["port"] = os.environ["PGPORT"]

    root_conninfo = pg_conninfo.make_conninfo(**root_params)
    return root_conninfo, target_dbname


def asegurar_base_de_datos(conninfo_str: str) -> None:
    """Verifica si la base de datos de destino existe; si no, la crea."""
    root_conninfo, target_dbname = parse_pg_target(conninfo_str)
    try:
        with psycopg.connect(root_conninfo, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s",
                    (target_dbname,),
                )
                if not cur.fetchone():
                    print(f"[+] Creando base de datos '{target_dbname}' en PostgreSQL...")
                    cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_dbname)))
                    print(f"[OK] Base de datos '{target_dbname}' creada con éxito.")
                else:
                    print(f"[*] Base de datos '{target_dbname}' ya existe.")
    except Exception as exc:
        print(f"[!] Aviso al verificar/crear base de datos: {exc}")
        print("    Intentando conectar directamente a la base de datos destino...")


def migrar():
    print("=" * 60)
    print("MIGRACIÓN DE DATOS: SQLite -> PostgreSQL (GOTUPLAS)")
    print("=" * 60)

    if not DB_SQLITE_FILE.is_file():
        print(f"[-] No se encontró archivo SQLite en: {DB_SQLITE_FILE}")
        print("    No hay datos antiguos para migrar. La aplicación usará PostgreSQL limpio.")
        return

    from db import close_pool, db_connection, get_conninfo, init_db

    conninfo_str = get_conninfo()

    if "tu_password_aqui" in conninfo_str or "TU_CONTRASEÑA" in conninfo_str:
        print("\n[!] ATENCIÓN: Aún no has configurado la contraseña en el archivo .env")
        print("    Por favor abre el archivo '.env' y reemplaza la contraseña")
        print("    por tu contraseña real de PostgreSQL.")
        sys.exit(1)

    print(f"[*] Conectando a PostgreSQL...")
    try:
        asegurar_base_de_datos(conninfo_str)
        init_db()
    except psycopg.OperationalError as exc:
        print(f"\n[ERROR] No se pudo conectar a PostgreSQL:")
        print(f"        {exc}")
        print("\nVerifique que:")
        print(" 1. El servicio de PostgreSQL esté iniciado.")
        print(" 2. Las credenciales en el archivo .env sean correctas.")
        sys.exit(1)

    try:
        print("[*] Leyendo datos desde SQLite...")
        sqlite_conn = sqlite3.connect(DB_SQLITE_FILE)
        sqlite_conn.row_factory = sqlite3.Row

        with sqlite_conn:
            visitantes_rows = sqlite_conn.execute("SELECT * FROM visitantes").fetchall()
            registros_rows = sqlite_conn.execute("SELECT * FROM registros ORDER BY id ASC").fetchall()
            cuentas_rows = sqlite_conn.execute("SELECT * FROM cuentas_recepcion").fetchall()

        print(f"    - Visitantes encontrados: {len(visitantes_rows)}")
        print(f"    - Registros encontrados:  {len(registros_rows)}")
        print(f"    - Cuentas encontradas:    {len(cuentas_rows)}")

        # Insertar en PostgreSQL
        with db_connection() as pg_conn:
            # 1. Visitantes
            print("\n[*] Migrando visitantes...")
            for r in visitantes_rows:
                pg_conn.execute(
                    """
                    INSERT INTO visitantes (cedula, nombre, empresa, arl, eps, telefono)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (cedula) DO UPDATE SET
                        nombre = EXCLUDED.nombre,
                        empresa = EXCLUDED.empresa,
                        arl = EXCLUDED.arl,
                        eps = EXCLUDED.eps,
                        telefono = EXCLUDED.telefono
                    """,
                    (
                        r["cedula"],
                        r["nombre"],
                        r["empresa"],
                        r["arl"],
                        r["eps"],
                        r["telefono"],
                    ),
                )
            print(f"[OK] {len(visitantes_rows)} visitantes migrados.")

            # 2. Registros (incluye firma BLOB -> BYTEA)
            print("\n[*] Migrando registros de ingresos e historial...")
            for r in registros_rows:
                firma = bytes(r["firma"]) if r["firma"] is not None else None
                acuerdo_conf = r["acuerdo_confidencialidad"] if "acuerdo_confidencialidad" in r.keys() else 1
                pg_conn.execute(
                    """
                    INSERT INTO registros (
                        id, fecha, hora_ingreso, hora_salida, empresa, nombre,
                        cedula, arl, eps, telefono, persona_visita, equipos,
                        estado, autorizacion_datos, acuerdo_confidencialidad, firma, categoria
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        fecha = EXCLUDED.fecha,
                        hora_ingreso = EXCLUDED.hora_ingreso,
                        hora_salida = EXCLUDED.hora_salida,
                        empresa = EXCLUDED.empresa,
                        nombre = EXCLUDED.nombre,
                        cedula = EXCLUDED.cedula,
                        arl = EXCLUDED.arl,
                        eps = EXCLUDED.eps,
                        telefono = EXCLUDED.telefono,
                        persona_visita = EXCLUDED.persona_visita,
                        equipos = EXCLUDED.equipos,
                        estado = EXCLUDED.estado,
                        autorizacion_datos = EXCLUDED.autorizacion_datos,
                        acuerdo_confidencialidad = EXCLUDED.acuerdo_confidencialidad,
                        firma = EXCLUDED.firma,
                        categoria = EXCLUDED.categoria
                    """,
                    (
                        r["id"],
                        r["fecha"],
                        r["hora_ingreso"],
                        r["hora_salida"],
                        r["empresa"],
                        r["nombre"],
                        r["cedula"],
                        r["arl"],
                        r["eps"],
                        r["telefono"],
                        r["persona_visita"],
                        r["equipos"],
                        r["estado"],
                        r["autorizacion_datos"],
                        acuerdo_conf,
                        firma,
                        r["categoria"],
                    ),
                )

            # Ajustar la secuencia de auto-incremento de id en PostgreSQL
            pg_conn.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('registros', 'id'),
                    COALESCE((SELECT MAX(id) FROM registros), 1)
                )
                """
            )
            print(f"[OK] {len(registros_rows)} registros migrados con secuencia sincronizada.")

            # 3. Cuentas recepción
            print("\n[*] Migrando cuentas de recepción...")
            for r in cuentas_rows:
                pg_conn.execute(
                    """
                    INSERT INTO cuentas_recepcion (usuario, password_hash, creado_en)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (usuario) DO NOTHING
                    """,
                    (r["usuario"], r["password_hash"], r["creado_en"]),
                )
            print(f"[OK] {len(cuentas_rows)} cuentas migradas.")

        # Verificación final
        with db_connection() as pg_conn:
            pg_vis = pg_conn.execute("SELECT count(*) AS total FROM visitantes").fetchone()["total"]
            pg_reg = pg_conn.execute("SELECT count(*) AS total FROM registros").fetchone()["total"]
            pg_cue = pg_conn.execute("SELECT count(*) AS total FROM cuentas_recepcion").fetchone()["total"]

        print("\n" + "=" * 60)
        print("RESUMEN DE MIGRACIÓN")
        print("=" * 60)
        print(f"Tabla 'visitantes':        SQLite={len(visitantes_rows)}  |  PostgreSQL={pg_vis}")
        print(f"Tabla 'registros':         SQLite={len(registros_rows)}  |  PostgreSQL={pg_reg}")
        print(f"Tabla 'cuentas_recepcion':  SQLite={len(cuentas_rows)}  |  PostgreSQL={pg_cue}")
        print("=" * 60)
        print("[EXITO] ¡Migración completada satisfactoriamente!")
        print("=" * 60)
    finally:
        close_pool()


if __name__ == "__main__":
    migrar()
