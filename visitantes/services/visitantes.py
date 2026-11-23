import json
from datetime import datetime
from typing import Any

from db import db_connection


def registrar_ingreso(
    cedula: str,
    valores: dict[str, str],
    equipos: list[dict[str, str]],
    categoria: str,
    autorizacion_datos: bool,
    firma: bytes,
    acuerdo_confidencialidad: bool = True,
) -> bool:
    ahora = datetime.now()
    with db_connection() as connection:
        activo = connection.execute(
            """
            SELECT 1
            FROM registros
            WHERE cedula = %s AND estado = 'ACTIVO'
            LIMIT 1
            """,
            (cedula,),
        ).fetchone()
        if activo:
            return False

        connection.execute(
            """
            INSERT INTO visitantes
                (cedula, nombre, empresa, arl, eps, telefono)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT(cedula) DO UPDATE SET
                nombre = excluded.nombre,
                empresa = excluded.empresa,
                arl = excluded.arl,
                eps = excluded.eps,
                telefono = excluded.telefono
            """,
            (
                cedula,
                valores["Nombre"],
                valores["Empresa"],
                valores["ARL"],
                valores["EPS"],
                valores["Teléfono"],
            ),
        )
        connection.execute(
            """
            INSERT INTO registros (
                fecha, hora_ingreso, hora_salida, empresa, nombre, cedula,
                arl, eps, telefono, persona_visita, equipos, estado,
                autorizacion_datos, acuerdo_confidencialidad, firma, categoria
            )
            VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, 'ACTIVO', %s, %s, %s, %s)
            """,
            (
                ahora.strftime("%Y-%m-%d"),
                ahora.strftime("%H:%M:%S"),
                valores["Empresa"],
                valores["Nombre"],
                cedula,
                valores["ARL"],
                valores["EPS"],
                valores["Teléfono"],
                valores["Persona a quien visita"],
                json.dumps(equipos, ensure_ascii=False),
                int(autorizacion_datos),
                int(acuerdo_confidencialidad),
                firma,
                categoria,
            ),
        )
    return True


def registrar_salida(registro_id: int) -> bool:
    hora_salida = datetime.now().strftime("%H:%M:%S")
    with db_connection() as connection:
        resultado = connection.execute(
            """
            UPDATE registros
            SET hora_salida = %s, estado = 'SALIÓ'
            WHERE id = %s AND estado = 'ACTIVO'
            """,
            (hora_salida, registro_id),
        )
    return resultado.rowcount == 1


def formatear_equipos(raw: str | None) -> str:
    if not raw:
        return "Ninguno"

    try:
        equipos: Any = json.loads(raw)
    except json.JSONDecodeError:
        return raw

    if not isinstance(equipos, list):
        return raw

    lineas = []
    for equipo in equipos:
        if isinstance(equipo, dict):
            lineas.append(
                "Marca: {marca} | Referencia: {referencia} | Serie: {serie}".format(
                    marca=equipo.get("marca", ""),
                    referencia=equipo.get("referencia", ""),
                    serie=equipo.get("serie", ""),
                )
            )
    return "\n".join(lineas) if lineas else "Ninguno"
