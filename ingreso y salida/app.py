import base64
import binascii
import csv
import hmac
import io
import logging
import os
import secrets
import sqlite3
import sys
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Callable, TypeVar

import psycopg
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge
from waitress import serve

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared_sso import (
    SSO_COOKIE_NAME,
    create_session as crear_sesion_sso,
    get_session as obtener_sesion_sso,
    has_role as tiene_rol_sso,
    init_sso_db,
    migrate_legacy_accounts,
    revoke_session as revocar_sesion_sso,
)

from db import (
    crear_empleado,
    consultar_salida_personal,
    obtener_firma_salida,
    init_db,
    db_connection,
    obtener_empleados,
    obtener_historial_salidas,
    obtener_reporte_dia,
    obtener_salidas_activas,
    obtener_salida_pendiente,
    registrar_regreso_personal,
    regularizar_regreso_personal,
    registrar_salida_personal,
)
from services.auth import (
    crear_cuenta_consulta,
    crear_primera_cuenta,
    validar_credenciales,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("INGRESOS_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_NAME="gotuplas_ingresos_session",
    MAX_CONTENT_LENGTH=1024 * 1024,
)
MAX_FIRMA_BYTES = 512 * 1024
logging.basicConfig(level=logging.INFO)
init_db()
init_sso_db()
with db_connection() as connection:
    attendance_accounts = connection.execute(
        "SELECT usuario, password_hash, rol FROM cuentas_admin"
    ).fetchall()
migrate_legacy_accounts(
    "ingresos",
    [dict(account) for account in attendance_accounts],
)

F = TypeVar("F", bound=Callable[..., object])


def requiere_lectura(function: F) -> F:
    @wraps(function)
    def wrapped(*args: object, **kwargs: object) -> object:
        account = getattr(g, "sso_account", None)
        if not account or not account.get("rol_ingresos"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Inicie sesión para continuar."}), 401
            return redirect(url_for("iniciar_sesion"))
        return function(*args, **kwargs)

    return wrapped  # type: ignore[return-value]


def requiere_admin(function: F) -> F:
    @wraps(function)
    @requiere_lectura
    def wrapped(*args: object, **kwargs: object) -> object:
        if not getattr(g, "sso_account", None) or g.sso_account.get(
            "rol_ingresos"
        ) != "admin":
            if request.path.startswith("/api/"):
                return jsonify({"error": "Se requieren permisos de administrador."}), 403
            abort(403)
        return function(*args, **kwargs)

    return wrapped  # type: ignore[return-value]


@app.before_request
def validar_csrf() -> tuple[dict[str, str], int] | None:
    try:
        g.sso_account = obtener_sesion_sso(request.cookies.get(SSO_COOKIE_NAME))
    except sqlite3.Error:
        app.logger.exception("Error validando la sesión compartida")
        return jsonify({"error": "No fue posible validar la sesión compartida."}), 503

    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    if request.method == "POST":
        token = request.headers.get("X-CSRF-Token") or request.form.get(
            "csrf_token", ""
        )
        if not token or not hmac.compare_digest(session["csrf_token"], token):
            return jsonify({"error": "La solicitud expiró. Recargue la página."}), 400
    return None


@app.context_processor
def csrf_context() -> dict[str, str]:
    return {"csrf_token": session["csrf_token"]}


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(_error: RequestEntityTooLarge) -> tuple[dict[str, str], int]:
    return jsonify({"error": "La firma supera el tamaño máximo permitido."}), 413


@app.get("/")
def inicio() -> object:
    try:
        if not tiene_rol_sso("ingresos"):
            return redirect(url_for("configurar_cuenta"))
    except sqlite3.Error:
        app.logger.exception("Error consultando las cuentas compartidas")
        return "No fue posible consultar la sesión compartida.", 503
    account = getattr(g, "sso_account", None)
    if account and account.get("rol_ingresos"):
        return redirect(url_for("panel"))
    return redirect(url_for("iniciar_sesion"))


@app.get("/salidas")
def salida_instalaciones() -> object:
    return render_template("asistencia.html")


@app.get("/asistencia")
def acceso_asistencia_anterior() -> object:
    return redirect(url_for("salida_instalaciones"))


@app.post("/api/salidas/consultar")
def consultar_estado_salida() -> object:
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({"error": "El cuerpo de la solicitud debe ser JSON."}), 400

    documento = str(datos.get("documento") or "").strip()
    if not documento or len(documento) > 50:
        return jsonify({"error": "Ingrese un documento válido."}), 400

    try:
        empleado = consultar_salida_personal(
            documento, datetime.now().astimezone().date().isoformat()
        )
    except psycopg.Error:
        app.logger.exception("Error consultando el estado de salida")
        return jsonify({"error": "No fue posible consultar el estado de salida."}), 500
    if empleado is None:
        return jsonify({"error": "Documento no registrado o empleado inactivo."}), 404

    return jsonify({
        "empleado": empleado,
        "estado": (
            "no_regresa"
            if empleado["no_regresa"]
            else "fuera" if empleado["movimiento_id"] else "en_instalaciones"
        ),
    })


@app.post("/api/salidas/registrar")
def crear_salida_personal() -> object:
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({"error": "El cuerpo de la solicitud debe ser JSON."}), 400

    documento = str(datos.get("documento") or "").strip()
    motivo = str(datos.get("motivo") or "").strip()
    destino = str(datos.get("destino") or "").strip()
    firma_data = datos.get("firma")
    no_regresa = datos.get("no_regresa")
    if not documento or len(documento) > 50:
        return jsonify({"error": "Ingrese un documento válido."}), 400
    if not motivo or len(motivo) > 300:
        return jsonify({"error": "Indique un motivo de salida (máximo 300 caracteres)."}), 400
    if not destino or len(destino) > 200:
        return jsonify({"error": "Indique un destino (máximo 200 caracteres)."}), 400
    if not isinstance(firma_data, str) or not firma_data.startswith(
        "data:image/png;base64,"
    ):
        return jsonify({"error": "Dibuje su firma antes de registrar la salida."}), 400
    encoded_signature = firma_data.removeprefix("data:image/png;base64,")
    if len(encoded_signature) > ((MAX_FIRMA_BYTES + 2) // 3) * 4:
        return jsonify({"error": "La firma supera el tamaño máximo de 512 KB."}), 413
    try:
        firma = base64.b64decode(encoded_signature, validate=True)
    except (binascii.Error, ValueError):
        return jsonify({"error": "La firma no tiene un formato válido."}), 400
    if len(firma) > MAX_FIRMA_BYTES or not firma.startswith(b"\x89PNG\r\n\x1a\n"):
        return jsonify({"error": "La imagen de la firma no es válida."}), 400
    if not isinstance(no_regresa, bool):
        return jsonify({"error": "Indique si regresará a las instalaciones durante el turno."}), 400

    momento = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        resultado = registrar_salida_personal(
            documento,
            momento,
            motivo,
            destino,
            firma,
            no_regresa,
        )
    except psycopg.Error:
        app.logger.exception("Error registrando una salida de las instalaciones")
        return jsonify({"error": "No fue posible registrar la salida."}), 500

    mensajes = {
        "no_disponible": ("Documento no registrado o empleado inactivo.", 404),
        "salida_abierta": ("El empleado ya tiene una salida sin regreso registrada.", 409),
        "ya_indico_no_regreso": (
            "Ya indicó que no regresará durante este turno.",
            409,
        ),
    }
    if resultado in mensajes:
        error, status = mensajes[resultado]
        return jsonify({"error": error}), status

    return jsonify({
        "message": "Salida registrada. Se marcará el regreso cuando vuelva."
        if resultado == "salida"
        else "Salida registrada. Indicó que no regresará durante este turno.",
        "estado": (
            "fuera" if resultado == "salida" else "no_regresa"
        ),
        "momento": momento,
    })


@app.post("/api/salidas/regreso")
def registrar_regreso_publico() -> object:
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({"error": "El cuerpo de la solicitud debe ser JSON."}), 400
    documento = str(datos.get("documento") or "").strip()
    if not documento or len(documento) > 50:
        return jsonify({"error": "Ingrese un documento válido."}), 400

    try:
        registrado = registrar_regreso_personal(
            documento,
            datetime.now().astimezone().isoformat(timespec="seconds"),
        )
    except psycopg.Error:
        app.logger.exception("Error registrando regreso a las instalaciones")
        return jsonify({"error": "No fue posible registrar el regreso."}), 500
    if not registrado:
        return jsonify({"error": "No hay una salida pendiente de regreso."}), 409
    return jsonify({"message": "Regreso a las instalaciones registrado correctamente."})


@app.route("/admin/login", methods=["GET", "POST"])
def iniciar_sesion() -> object:
    current_account = getattr(g, "sso_account", None)
    if current_account and current_account.get("rol_ingresos"):
        return redirect(url_for("panel"))

    error = ""
    status = 200
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        clave = request.form.get("clave", "")
        try:
            cuenta = validar_credenciales(usuario, clave)
        except sqlite3.Error:
            app.logger.exception("Error validando la cuenta compartida")
            error, status = "No fue posible validar el acceso. Intente de nuevo.", 500
        except psycopg.Error:
            app.logger.exception("Error validando la cuenta administrativa")
            error, status = "No fue posible validar el acceso. Intente de nuevo.", 500
        else:
            if cuenta is not None:
                session.clear()
                session["csrf_token"] = secrets.token_urlsafe(32)
                try:
                    token = crear_sesion_sso(cuenta["usuario"])
                except sqlite3.Error:
                    app.logger.exception("Error creando la sesión compartida")
                    error, status = "No fue posible iniciar la sesión. Intente de nuevo.", 500
                else:
                    response = redirect(url_for("panel"))
                    response.set_cookie(
                        SSO_COOKIE_NAME,
                        token,
                        max_age=8 * 60 * 60,
                        httponly=True,
                        secure=request.is_secure,
                        samesite="Lax",
                        path="/",
                    )
                    return response
            else:
                error, status = "Usuario o contraseña incorrectos.", 401
    return render_template("login.html", error=error), status


@app.route("/admin/configurar", methods=["GET", "POST"])
def configurar_cuenta() -> object:
    try:
        if tiene_rol_sso("ingresos"):
            return redirect(url_for("iniciar_sesion"))
    except sqlite3.Error:
        app.logger.exception("Error verificando la configuración administrativa")
        return "No fue posible verificar la sesión compartida.", 500

    error = ""
    status = 200
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        clave = request.form.get("clave", "")
        confirmar = request.form.get("confirmar_clave", "")
        if len(usuario) < 3:
            error = "El usuario debe tener al menos 3 caracteres."
        elif len(clave) < 8:
            error = "La contraseña debe tener al menos 8 caracteres."
        elif clave != confirmar:
            error = "Las contraseñas no coinciden."
        else:
            try:
                creada = crear_primera_cuenta(usuario, clave)
            except sqlite3.Error:
                app.logger.exception("Error creando la cuenta administrativa")
                error = "No fue posible crear la cuenta. Intente de nuevo."
            else:
                if creada:
                    return redirect(url_for("iniciar_sesion"))
                error = "No fue posible crear la cuenta. Es posible que el usuario ya exista."
                status = 409
    return render_template("setup.html", error=error), status


@app.get("/admin")
@requiere_lectura
def panel() -> object:
    account = g.sso_account
    return render_template(
        "admin.html",
        usuario=account["usuario"],
        rol=account["rol_ingresos"],
    )


@app.post("/admin/logout")
def cerrar_sesion() -> object:
    try:
        revocar_sesion_sso(request.cookies.get(SSO_COOKIE_NAME))
    except sqlite3.Error:
        app.logger.exception("Error cerrando la sesión compartida")
        return "No fue posible cerrar la sesión.", 500
    session.clear()
    response = redirect(url_for("iniciar_sesion"))
    response.delete_cookie(SSO_COOKIE_NAME, path="/", httponly=True, samesite="Lax")
    return response


@app.get("/api/empleados")
@requiere_admin
def listar_empleados() -> object:
    try:
        return jsonify({"empleados": obtener_empleados()})
    except psycopg.Error:
        app.logger.exception("Error consultando empleados")
        return jsonify({"error": "No fue posible cargar los empleados."}), 500


@app.post("/api/empleados")
@requiere_admin
def agregar_empleado() -> object:
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({"error": "El cuerpo de la solicitud debe ser JSON."}), 400

    campos = {
        "documento": str(datos.get("documento") or "").strip(),
        "nombre": str(datos.get("nombre") or "").strip(),
        "area": str(datos.get("area") or "").strip(),
        "cargo": str(datos.get("cargo") or "").strip(),
    }
    if any(not valor for valor in campos.values()):
        return jsonify({"error": "Complete todos los campos del empleado."}), 400
    if len(campos["documento"]) > 50 or len(campos["nombre"]) > 150:
        return jsonify({"error": "Revise la longitud del documento o del nombre."}), 400

    try:
        crear_empleado(
            **campos,
            creado_en=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
    except psycopg.IntegrityError:
        return jsonify({"error": "Ya existe un empleado con ese documento."}), 409
    except psycopg.Error:
        app.logger.exception("Error creando empleado")
        return jsonify({"error": "No fue posible guardar el empleado."}), 500
    return jsonify({"message": "Empleado registrado correctamente."}), 201


@app.post("/api/usuarios/lectura")
@requiere_admin
def crear_usuario_lectura() -> object:
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({"error": "El cuerpo de la solicitud debe ser JSON."}), 400
    usuario = str(datos.get("usuario") or "").strip()
    clave = str(datos.get("clave") or "")
    if len(usuario) < 3 or len(usuario) > 50:
        return jsonify({"error": "El usuario debe tener entre 3 y 50 caracteres."}), 400
    if any(character.isspace() for character in usuario):
        return jsonify({"error": "El usuario no puede contener espacios."}), 400
    if len(clave) < 12:
        return jsonify({"error": "La contraseña debe tener al menos 12 caracteres."}), 400
    try:
        crear_cuenta_consulta(usuario, clave)
    except ValueError as error:
        return jsonify({"error": str(error)}), 409
    except psycopg.IntegrityError:
        return jsonify({"error": "Ya existe una cuenta con ese usuario."}), 409
    except sqlite3.Error:
        app.logger.exception("Error creando una cuenta de solo lectura")
        return jsonify({"error": "No fue posible crear la cuenta de consulta."}), 500
    except psycopg.Error:
        app.logger.exception("Error creando una cuenta de solo lectura")
        return jsonify({"error": "No fue posible crear la cuenta de consulta."}), 500
    return jsonify({"message": f"Cuenta de solo lectura '{usuario}' creada."}), 201


@app.get("/api/activos")
@requiere_lectura
def listar_activos() -> object:
    try:
        return jsonify({"activos": obtener_salidas_activas()})
    except psycopg.Error:
        app.logger.exception("Error consultando salidas activas")
        return jsonify({"error": "No fue posible cargar las salidas activas."}), 500


@app.post("/api/salidas/<int:movimiento_id>/regularizar")
@requiere_admin
def regularizar_regreso(movimiento_id: int) -> object:
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({"error": "El cuerpo de la solicitud debe ser JSON."}), 400

    motivo = str(datos.get("motivo") or "").strip()
    hora_real = str(datos.get("hora_real") or "").strip()
    evidencia = str(datos.get("evidencia") or "").strip()
    if not motivo or len(motivo) > 500:
        return jsonify({"error": "Indique el motivo del ajuste (máximo 500 caracteres)."}), 400
    if len(evidencia) > 500:
        return jsonify({"error": "La evidencia no puede superar 500 caracteres."}), 400
    if hora_real and not evidencia:
        return jsonify({
            "error": "Describa la evidencia que confirma la hora real del regreso."
        }), 400

    try:
        pendiente = obtener_salida_pendiente(movimiento_id)
        if pendiente is None:
            return jsonify({"error": "La salida ya no está pendiente o no existe."}), 409

        ahora = datetime.now().astimezone()
        regreso_confirmado = bool(hora_real)
        if hora_real:
            try:
                regreso = datetime.fromisoformat(hora_real.replace("Z", "+00:00"))
            except ValueError:
                return jsonify({"error": "La hora real del regreso no es válida."}), 400
            if regreso.tzinfo is None:
                return jsonify({"error": "La hora real debe incluir zona horaria."}), 400
            salida = datetime.fromisoformat(str(pendiente["salida"]))
            if salida.tzinfo is None:
                salida = salida.astimezone()
            if regreso < salida:
                return jsonify({"error": "El regreso no puede ser anterior a la salida."}), 400
            if regreso > ahora:
                return jsonify({"error": "La hora real del regreso no puede ser futura."}), 400
            regreso_texto = regreso.astimezone().isoformat(timespec="seconds")
        else:
            regreso_texto = ahora.isoformat(timespec="seconds")

        actualizado = regularizar_regreso_personal(
            movimiento_id=movimiento_id,
            regreso=regreso_texto,
            regreso_confirmado=regreso_confirmado,
            admin=str(g.sso_account["usuario"]),
            regularizado_en=ahora.isoformat(timespec="seconds"),
            motivo=motivo,
            evidencia=evidencia,
        )
    except psycopg.Error:
        app.logger.exception("Error regularizando el regreso de una salida")
        return jsonify({"error": "No fue posible regularizar el regreso."}), 500
    if not actualizado:
        return jsonify({"error": "La salida ya fue cerrada por otro usuario."}), 409
    return jsonify({
        "message": (
            "Regreso regularizado con hora confirmada y evidencia."
            if regreso_confirmado
            else "Salida cerrada con la hora actual, marcada como no confirmada."
        )
    })


@app.get("/api/historial")
@requiere_lectura
def listar_historial() -> object:
    try:
        return jsonify({"registros": obtener_historial_salidas()})
    except psycopg.Error:
        app.logger.exception("Error consultando historial")
        return jsonify({"error": "No fue posible cargar el historial."}), 500


@app.get("/admin/exportar")
@requiere_lectura
def exportar_historial() -> object:
    try:
        registros = obtener_historial_salidas()
    except psycopg.Error:
        app.logger.exception("Error preparando exportación del historial")
        return jsonify({"error": "No fue posible exportar el historial."}), 500

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "Documento",
            "Nombre",
            "Área",
            "Cargo",
            "Salida de instalaciones",
            "Regreso",
            "Hora de regreso confirmada",
            "Regularizado por",
            "Fecha de regularización",
            "Motivo de regularización",
            "Evidencia",
            "Motivo",
            "Destino",
            "Firma",
            "Estado",
        ]
    )
    for registro in registros:
        writer.writerow(
            [
                registro["documento"],
                registro["nombre"],
                registro["area"],
                registro["cargo"],
                registro["salida"],
                registro["regreso"] or "",
                (
                    "Sí"
                    if registro["regreso_regularizado"]
                    and registro["regreso_confirmado"]
                    else "No"
                    if registro["regreso_regularizado"]
                    else ""
                ),
                registro["regreso_regularizado_por"] or "",
                registro["regreso_regularizado_en"] or "",
                registro["regreso_regularizado_motivo"] or "",
                registro["regreso_regularizado_evidencia"] or "",
                registro["motivo"],
                registro["destino"],
                "Registrada" if registro["tiene_firma"] else "Sin firma",
                registro["estado"],
            ]
        )
    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = (
        "attachment; filename=historial_salidas_personal.csv"
    )
    return response


@app.get("/admin/reporte")
@requiere_lectura
def imprimir_reporte() -> object:
    fecha = request.args.get("fecha", datetime.now().astimezone().date().isoformat())
    try:
        fecha_objeto = datetime.strptime(fecha, "%Y-%m-%d").date()
    except ValueError:
        return "La fecha del reporte debe tener formato AAAA-MM-DD.", 400
    if fecha_objeto.isoformat() != fecha:
        return "La fecha del reporte no es válida.", 400

    try:
        registros = obtener_reporte_dia(fecha)
    except psycopg.Error:
        app.logger.exception("Error preparando el reporte imprimible de salidas")
        return "No fue posible cargar el reporte del día.", 500

    filas = []
    for numero, registro in enumerate(registros, start=1):
        salida = datetime.fromisoformat(str(registro["salida"]))
        regreso = (
            datetime.fromisoformat(str(registro["regreso"]))
            if registro["regreso"]
            else None
        )
        firma = registro["firma"]
        if isinstance(firma, memoryview):
            firma = firma.tobytes()
        filas.append(
            {
                "numero": numero,
                "fecha": salida.strftime("%d/%m/%Y"),
                "nombre": registro["nombre"],
                "documento": registro["documento"],
                "cargo": registro["cargo"],
                "hora_salida": salida.strftime("%H:%M:%S"),
                "fecha_regreso": regreso.strftime("%d/%m/%Y") if regreso else "",
                "hora_regreso": regreso.strftime("%H:%M:%S") if regreso else "",
                "regreso_regularizado": registro["regreso_regularizado"],
                "regreso_confirmado": registro["regreso_confirmado"],
                "regreso_regularizado_por": registro["regreso_regularizado_por"],
                "firma": (
                    base64.b64encode(bytes(firma)).decode("ascii")
                    if firma
                    else ""
                ),
                "motivo": registro["motivo"],
            }
        )

    filas_paginadas = [filas[i:i + 25] for i in range(0, len(filas), 25)] or [[]]
    return render_template(
        "reporte_salidas.html",
        fecha=fecha_objeto.strftime("%d/%m/%Y"),
        paginas=filas_paginadas,
    )


@app.get("/api/salidas/<int:movimiento_id>/firma")
@requiere_lectura
def consultar_firma(movimiento_id: int) -> object:
    try:
        firma = obtener_firma_salida(movimiento_id)
    except psycopg.Error:
        app.logger.exception("Error consultando firma de la salida")
        return jsonify({"error": "No fue posible consultar la firma."}), 500
    if firma is None:
        abort(404)
    response = make_response(firma)
    response.headers["Content-Type"] = "image/png"
    response.headers["Cache-Control"] = "private, no-store"
    return response


if __name__ == "__main__":
    port = int(os.environ.get("INGRESOS_PORT", "8503"))
    serve(app, host="0.0.0.0", port=port)
