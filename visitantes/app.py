import base64
import binascii
import csv
import hmac
import io
import json
import logging
import os
import secrets
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

import pypdfium2 as pdfium
from flask import (
    Flask,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared_sso import (
    SSO_COOKIE_NAME,
    create_session as crear_sesion_sso,
    get_session as obtener_sesion_sso,
    has_role as tiene_rol_sso,
    init_sso_db,
    list_accounts as listar_cuentas_sso,
    migrate_legacy_accounts,
    revoke_session as revocar_sesion_sso,
    delete_visitor_role as eliminar_rol_visitantes_sso,
)

from db import (
    DatabaseError,
    db_connection,
    init_db,
    obtener_firma,
    obtener_historial,
    obtener_registro,
    obtener_visitante,
    obtener_visitantes_activos,
)
from services.acuerdo_pdf import generar_acuerdo_pdf
from services.auth import (
    autenticar_usuario,
    cambiar_clave_usuario,
    crear_primera_cuenta,
    crear_usuario,
    hay_cuenta_recepcion,
)
from services.visitantes import registrar_ingreso, registrar_salida


app = Flask(__name__)
app.secret_key = os.environ.get("GOTUPLAS_SECRET_KEY") or secrets.token_hex(32)
app.json.ensure_ascii = False
MAX_POLITICA_BYTES = 10 * 1024 * 1024
MAX_FIRMA_BYTES = 512 * 1024
_PDFIUM_LOCK = Lock()
CATEGORIAS_VISITANTE = {
    "Visitantes",
    "Proveedores y contratistas",
    "Clientes",
    "Candidatos o aspirantes",
}
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_NAME="gotuplas_visitantes_session",
    MAX_CONTENT_LENGTH=MAX_POLITICA_BYTES + 64 * 1024,
)
logging.basicConfig(level=logging.INFO)
init_sso_db()

POLITICA_FILE = (
    Path(app.instance_path) / "documentos" / "politica_tratamiento_datos.pdf"
)

PRIVATE_ENDPOINTS = {
    "recepcion",
    "cerrar_sesion",
    "listar_activos",
    "registrar_hora_salida",
    "listar_historial",
    "exportar_historial",
    "subir_politica_datos",
    "consultar_firma",
    "descargar_acuerdo_pdf",
}
ADMIN_ENDPOINTS = {"administrar_usuarios"}


def contar_paginas_pdf(origen: Path | bytes) -> int:
    with _PDFIUM_LOCK:
        documento = pdfium.PdfDocument(origen)
        try:
            return len(documento)
        finally:
            documento.close()


def renderizar_pagina_pdf(ruta: Path, numero_pagina: int) -> bytes:
    with _PDFIUM_LOCK:
        documento = None
        pagina = None
        bitmap = None
        imagen = None
        try:
            documento = pdfium.PdfDocument(ruta)
            if numero_pagina < 1 or numero_pagina > len(documento):
                raise IndexError("La página solicitada no existe.")

            pagina = documento[numero_pagina - 1]
            ancho, alto = pagina.get_size()
            if ancho <= 0 or alto <= 0:
                raise ValueError("La página del documento no tiene un tamaño válido.")
            escala = min(1.5, 1600 / max(ancho, alto))
            bitmap = pagina.render(scale=escala)
            imagen = bitmap.to_pil()
            with io.BytesIO() as salida:
                imagen.save(salida, format="PNG")
                return salida.getvalue()
        finally:
            if imagen is not None:
                imagen.close()
            if bitmap is not None:
                bitmap.close()
            if pagina is not None:
                pagina.close()
            if documento is not None:
                documento.close()


@app.before_request
def proteger_rutas_de_recepcion():
    token_sso = request.cookies.get(SSO_COOKIE_NAME)
    try:
        g.sso_account = obtener_sesion_sso(token_sso)
    except sqlite3.Error:
        app.logger.exception("Error validando la sesión compartida")
        return "No fue posible validar la sesión compartida.", 503

    if request.method == "POST" and request.endpoint != "static":
        token = session.get("csrf_token", "")
        enviado = request.headers.get("X-CSRF-Token") or request.form.get(
            "csrf_token", ""
        )
        if not token or not hmac.compare_digest(token, enviado):
            return jsonify({"error": "La solicitud expiró. Recargue la página."}), 400

    if request.endpoint in PRIVATE_ENDPOINTS:
        cuenta = getattr(g, "sso_account", None)
        if not cuenta or not cuenta.get("rol_visitantes"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Se requiere iniciar sesión en recepción."}), 401
            return redirect(url_for("iniciar_sesion"))

    if request.endpoint in ADMIN_ENDPOINTS and (
        not getattr(g, "sso_account", None)
        or g.sso_account.get("rol_visitantes") != "administrador"
    ):
        return redirect(url_for("iniciar_sesion"))


@app.context_processor
def inyectar_token_csrf():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrf_token": session["csrf_token"]}


@app.errorhandler(RequestEntityTooLarge)
def solicitud_demasiado_grande(_error: RequestEntityTooLarge):
    app.logger.warning("Solicitud rechazada por exceder el límite de tamaño: %s", _error)
    return jsonify({"error": "La solicitud supera el límite de 10 MB."}), 413


def equipos_para_respuesta(raw: str | None) -> Any:
    if not raw:
        return []
    try:
        equipos = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return equipos if isinstance(equipos, list) else raw


@app.get("/")
def inicio():
    return render_template(
        "index.html",
        politica_disponible=POLITICA_FILE.is_file(),
    )


@app.get("/politica-tratamiento-datos")
def politica_tratamiento_datos():
    if not POLITICA_FILE.is_file():
        return render_template("politica_no_disponible.html"), 200
    return send_file(
        POLITICA_FILE,
        mimetype="application/pdf",
        as_attachment=False,
        download_name="politica_tratamiento_datos.pdf",
    )


@app.get("/politica-tratamiento-datos/paginas/<int:numero_pagina>")
def pagina_politica_tratamiento_datos(numero_pagina: int):
    if not POLITICA_FILE.is_file():
        return (
            jsonify({"error": "La política de tratamiento de datos no está disponible."}),
            404,
        )

    try:
        contenido = renderizar_pagina_pdf(POLITICA_FILE, numero_pagina)
    except IndexError:
        return jsonify({"error": "La página solicitada no existe."}), 404
    except (OSError, RuntimeError):
        app.logger.exception("Error renderizando una página de la política de datos")
        return (
            jsonify(
                {"error": "No fue posible mostrar la política de tratamiento de datos."}
            ),
            500,
        )
    except ValueError:
        app.logger.exception("La página de la política de datos no se puede renderizar")
        return (
            jsonify(
                {"error": "No fue posible mostrar la política de tratamiento de datos."}
            ),
            500,
        )

    return app.response_class(
        contenido,
        mimetype="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/politica-tratamiento-datos/leer")
def leer_politica_tratamiento_datos():
    if not POLITICA_FILE.is_file():
        return render_template(
            "politica_pdf.html",
            politica_disponible=False,
            politica_paginas=0,
        )

    try:
        numero_paginas = contar_paginas_pdf(POLITICA_FILE)
    except (OSError, RuntimeError):
        app.logger.exception("Error abriendo la política de tratamiento de datos")
        return "No fue posible abrir la política de tratamiento de datos.", 500

    if numero_paginas < 1:
        return "La política de tratamiento de datos no contiene páginas.", 500

    return render_template(
        "politica_pdf.html",
        politica_disponible=True,
        politica_paginas=numero_paginas,
    )


@app.get("/acuerdo-confidencialidad")
def acuerdo_confidencialidad():
    return render_template("acuerdo_confidencialidad.html")


@app.route("/recepcion/login", methods=["GET", "POST"])
def iniciar_sesion():
    cuenta_actual = getattr(g, "sso_account", None)
    if cuenta_actual and cuenta_actual.get("rol_visitantes"):
        if cuenta_actual["rol_visitantes"] == "administrador":
            return redirect(url_for("administrar_usuarios"))
        return redirect(url_for("recepcion"))

    error = ""
    status = 200

    if request.method == "POST":
        usuario = request.form.get("usuario", "")
        clave = request.form.get("clave", "")
        try:
            cuenta = autenticar_usuario(usuario, clave)
        except sqlite3.Error:
            app.logger.exception("Error validando la cuenta compartida")
            error = "No fue posible validar el acceso. Intente de nuevo."
            status = 500
        except DatabaseError:
            app.logger.exception("Error consultando la cuenta de recepción")
            error = "No fue posible validar el acceso. Intente de nuevo."
            status = 500
        else:
            if cuenta is not None:
                session.clear()
                session["csrf_token"] = secrets.token_urlsafe(32)
                try:
                    token = crear_sesion_sso(cuenta["usuario"])
                except sqlite3.Error:
                    app.logger.exception("Error creando la sesión compartida")
                    error = "No fue posible iniciar la sesión. Intente de nuevo."
                    status = 500
                else:
                    response = (
                        redirect(url_for("administrar_usuarios"))
                        if cuenta["rol"] == "administrador"
                        else redirect(url_for("recepcion"))
                    )
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
                error = "Usuario o contraseña incorrectos."
                status = 401

    try:
        account_configured = hay_cuenta_recepcion()
    except sqlite3.Error:
        app.logger.exception("Error verificando la cuenta de recepción")
        return "No fue posible consultar la cuenta de recepción.", 500
    return render_template(
        "login.html",
        error=error,
        account_configured=account_configured,
        administrador_creado=request.args.get("administrador_creado") == "1",
    ), status


@app.route("/recepcion/configurar", methods=["GET", "POST"])
def configurar_cuenta_recepcion():
    try:
        if hay_cuenta_recepcion():
            return redirect(url_for("iniciar_sesion"))
    except sqlite3.Error:
        app.logger.exception("Error verificando la configuración de recepción")
        return "No fue posible verificar la configuración de la cuenta.", 500

    error = ""
    status = 200
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        clave = request.form.get("clave", "")
        confirmar = request.form.get("confirmar_clave", "")
        if len(usuario) < 3:
            error = "El usuario debe tener al menos 3 caracteres."
        elif len(clave) < 6:
            error = "La contraseña debe tener al menos 6 caracteres."
        elif clave != confirmar:
            error = "Las contraseñas no coinciden."
        else:
            try:
                creada = crear_primera_cuenta(usuario, clave)
            except sqlite3.Error:
                app.logger.exception("Error creando la cuenta de recepción")
                error = "No fue posible crear la cuenta. Intente de nuevo."
                status = 500
            else:
                if creada:
                    return redirect(url_for("iniciar_sesion"))
                error = "No fue posible crear la cuenta. Es posible que el usuario ya exista."
                status = 409

    return (
        render_template("setup.html", error=error),
        status,
    )


@app.route("/administracion/usuarios", methods=["GET", "POST"])
def administrar_usuarios():
    cuenta_actual = getattr(g, "sso_account", None)
    es_administrador = bool(
        cuenta_actual and cuenta_actual.get("rol_visitantes") == "administrador"
    )
    try:
        administrador_configurado = tiene_rol_sso("visitantes", "administrador")
    except sqlite3.Error:
        app.logger.exception("Error verificando las cuentas de administración")
        return "No fue posible verificar las cuentas de administración.", 500

    if not es_administrador and administrador_configurado:
        return redirect(url_for("recepcion"))

    error = ""
    mensaje = ""
    status = 200
    if request.method == "POST":
        accion = request.form.get("accion", "crear")
        if accion == "eliminar" and es_administrador:
            usuario = request.form.get("usuario", "").strip()
            if usuario.casefold() == str(cuenta_actual["usuario"]).casefold():
                error = "No puede eliminar la cuenta con la que inició sesión."
                status = 400
            else:
                try:
                    rol_eliminado = eliminar_rol_visitantes_sso(usuario)
                except sqlite3.Error:
                    app.logger.exception("Error eliminando una cuenta de usuario")
                    error = "No fue posible eliminar la cuenta. Intente de nuevo."
                    status = 500
                else:
                    if rol_eliminado is None:
                        error = (
                            "No se puede eliminar la última cuenta de un rol "
                            "o la cuenta ya no existe."
                        )
                        status = 400
                    else:
                        return redirect(
                            url_for("administrar_usuarios", eliminado="1")
                        )
        elif accion == "cambiar_clave" and es_administrador:
            usuario = request.form.get("usuario", "").strip()
            clave = request.form.get("clave", "")
            confirmar = request.form.get("confirmar_clave", "")
            if len(clave) < 6:
                error = "La contraseña debe tener al menos 6 caracteres."
                status = 400
            elif clave != confirmar:
                error = "Las contraseñas no coinciden."
                status = 400
            else:
                try:
                    actualizada = cambiar_clave_usuario(usuario, clave)
                except sqlite3.Error:
                    app.logger.exception("Error cambiando la contraseña de un usuario")
                    error = "No fue posible cambiar la contraseña. Intente de nuevo."
                    status = 500
                else:
                    if not actualizada:
                        error = "La cuenta ya no existe."
                        status = 404
                    else:
                        return redirect(
                            url_for("administrar_usuarios", clave_cambiada="1")
                        )
        elif accion == "crear":
            usuario = request.form.get("usuario", "").strip()
            clave = request.form.get("clave", "")
            confirmar = request.form.get("confirmar_clave", "")
            rol = (
                request.form.get("rol", "")
                if es_administrador
                else "administrador"
            )
            if len(usuario) < 3 or len(usuario) > 100:
                error = "El usuario debe tener entre 3 y 100 caracteres."
            elif rol not in {"recepcion", "administrador"}:
                error = "Seleccione un tipo de cuenta válido."
            elif len(clave) < 6:
                error = "La contraseña debe tener al menos 6 caracteres."
            elif clave != confirmar:
                error = "Las contraseñas no coinciden."
            else:
                try:
                    creada = crear_usuario(usuario, clave, rol)
                except sqlite3.Error:
                    app.logger.exception("Error creando una cuenta de usuario")
                    error = "No fue posible crear la cuenta. Intente de nuevo."
                    status = 500
                else:
                    if not creada:
                        error = "Ya existe una cuenta con ese nombre de usuario."
                        status = 400
                    elif not es_administrador:
                        return redirect(
                            url_for("administrar_usuarios", creado="1")
                        )
                    else:
                        return redirect(
                            url_for("administrar_usuarios", creado="1")
                        )
        else:
            error = "La acción solicitada no es válida."
            status = 400

    try:
        cuentas = listar_cuentas_sso("visitantes")
    except sqlite3.Error:
        app.logger.exception("Error consultando las cuentas de usuario")
        return "No fue posible consultar las cuentas de usuario.", 500

    if request.args.get("creado") == "1":
        mensaje = "La cuenta se creó correctamente."
    elif request.args.get("eliminado") == "1":
        mensaje = "La cuenta se eliminó correctamente."
    elif request.args.get("clave_cambiada") == "1":
        mensaje = "La contraseña se cambió correctamente."

    return (
        render_template(
            "administracion_usuarios.html",
            cuentas=cuentas,
            es_administrador=es_administrador,
            error=error,
            mensaje=mensaje,
            usuario_actual=(cuenta_actual or {}).get("usuario"),
        ),
        status,
    )


@app.get("/recepcion")
def recepcion():
    try:
        administrador_configurado = tiene_rol_sso("visitantes", "administrador")
    except sqlite3.Error:
        app.logger.exception("Error verificando las cuentas de administración")
        return "No fue posible verificar las cuentas de administración.", 500
    return render_template(
        "recepcion.html",
        politica_disponible=POLITICA_FILE.is_file(),
        puede_configurar_administrador=not administrador_configurado,
    )


@app.post("/api/recepcion/politica-tratamiento-datos")
def subir_politica_datos():
    archivo = request.files.get("archivo")
    if archivo is None or not archivo.filename:
        return jsonify({"error": "Seleccione el archivo PDF de la política."}), 400
    if Path(archivo.filename).suffix.lower() != ".pdf":
        return jsonify({"error": "El archivo seleccionado debe tener formato PDF."}), 400

    contenido = archivo.read(MAX_POLITICA_BYTES + 1)
    if len(contenido) > MAX_POLITICA_BYTES:
        return jsonify({"error": "El PDF no puede superar los 10 MB."}), 413
    if not contenido.startswith(b"%PDF-"):
        return jsonify({"error": "El archivo seleccionado no parece ser un PDF válido."}), 400

    try:
        numero_paginas = contar_paginas_pdf(contenido)
    except (OSError, RuntimeError):
        return (
            jsonify({"error": "El archivo seleccionado no se puede leer como PDF."}),
            400,
        )
    if numero_paginas < 1:
        return jsonify({"error": "El archivo PDF no contiene páginas para mostrar."}), 400

    temporal: str | None = None
    try:
        POLITICA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=POLITICA_FILE.parent,
            prefix=".politica-",
            suffix=".tmp",
            delete=False,
        ) as archivo_temporal:
            temporal = archivo_temporal.name
            archivo_temporal.write(contenido)
        os.replace(temporal, POLITICA_FILE)
    except OSError:
        app.logger.exception("Error guardando la política de tratamiento de datos")
        return jsonify({"error": "No fue posible guardar el PDF de la política."}), 500
    finally:
        if temporal and os.path.exists(temporal):
            try:
                os.unlink(temporal)
            except OSError:
                app.logger.exception("Error limpiando el archivo temporal de la política")

    return jsonify({"message": "La política de tratamiento de datos quedó cargada."})


@app.post("/recepcion/logout")
def cerrar_sesion():
    token = request.cookies.get(SSO_COOKIE_NAME)
    try:
        revocar_sesion_sso(token)
    except sqlite3.Error:
        app.logger.exception("Error cerrando la sesión compartida")
        return "No fue posible cerrar la sesión.", 500
    session.clear()
    response = redirect(url_for("inicio"))
    response.delete_cookie(SSO_COOKIE_NAME, path="/", httponly=True, samesite="Lax")
    return response


@app.get("/api/visitantes/<cedula>")
def consultar_visitante(cedula: str):
    visitante = obtener_visitante(cedula.strip())
    if visitante is None:
        return jsonify({"found": False})
    return jsonify({"found": True, "visitante": dict(visitante)})


@app.post("/api/ingresos")
def crear_ingreso():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({"error": "El cuerpo de la solicitud debe ser JSON."}), 400

    cedula = str(datos.get("cedula") or "").strip()
    valores = {
        "Nombre": str(datos.get("nombre") or "").strip(),
        "Empresa": str(datos.get("empresa") or "").strip(),
        "ARL": str(datos.get("arl") or "").strip(),
        "EPS": str(datos.get("eps") or "").strip(),
        "Teléfono": str(datos.get("telefono") or "").strip(),
        "Persona a quien visita": str(datos.get("persona_visita") or "").strip(),
    }
    categoria = str(datos.get("categoria") or "").strip()
    errores = [
        f"{campo} es obligatorio"
        for campo, valor in {
            "Cédula": cedula,
            **valores,
        }.items()
        if not valor
    ]
    if categoria not in CATEGORIAS_VISITANTE:
        errores.append("Seleccione una categoría de visitante válida")

    equipos_recibidos = datos.get("equipos", [])
    if not isinstance(equipos_recibidos, list):
        errores.append("La lista de equipos no tiene un formato válido")
        equipos_recibidos = []

    equipos = []
    for equipo in equipos_recibidos:
        if not isinstance(equipo, dict):
            errores.append("Cada equipo debe incluir marca, referencia y serie")
            continue
        normalizado = {
            "marca": str(equipo.get("marca") or "").strip(),
            "referencia": str(equipo.get("referencia") or "").strip(),
            "serie": str(equipo.get("serie") or "").strip(),
        }
        if any(normalizado.values()):
            if not all(normalizado.values()):
                errores.append(
                    "Complete marca, referencia y serie de cada equipo ingresado"
                )
            else:
                equipos.append(normalizado)

    autorizacion_datos = datos.get("autorizacion_datos") is True
    if not autorizacion_datos:
        errores.append("Debe autorizar el tratamiento de sus datos personales")

    acuerdo_confidencialidad = datos.get("acuerdo_confidencialidad") is True
    if not acuerdo_confidencialidad:
        errores.append("Debe aceptar el Acuerdo de Confidencialidad para visitantes")

    firma_data_url = datos.get("firma")
    firma = b""
    if isinstance(firma_data_url, str) and firma_data_url.startswith(
        "data:image/png;base64,"
    ):
        encoded_firma = firma_data_url.removeprefix("data:image/png;base64,")
        if len(encoded_firma) <= ((MAX_FIRMA_BYTES + 2) // 3) * 4:
            try:
                firma = base64.b64decode(encoded_firma, validate=True)
            except (binascii.Error, ValueError):
                firma = b""
    if (
        not firma.startswith(b"\x89PNG\r\n\x1a\n")
        or len(firma) > MAX_FIRMA_BYTES
    ):
        errores.append("La firma es obligatoria y debe tener un formato válido")

    if errores:
        return jsonify({"error": "; ".join(errores) + "."}), 400

    try:
        registrado = registrar_ingreso(
            cedula,
            valores,
            equipos,
            categoria,
            autorizacion_datos,
            firma,
            acuerdo_confidencialidad,
        )
    except DatabaseError:
        app.logger.exception("Error guardando el ingreso de un visitante")
        return jsonify({"error": "No fue posible guardar el ingreso."}), 500
    if not registrado:
        return (
            jsonify(
                {
                    "error": (
                        "Esta persona ya tiene un ingreso activo. "
                        "Registre su salida antes de crear otro ingreso."
                    )
                }
            ),
            409,
        )
    return jsonify({"message": f"Ingreso registrado para {valores['Nombre']}."}), 201


@app.get("/api/activos")
def listar_activos():
    try:
        visitantes = obtener_visitantes_activos()
    except DatabaseError:
        app.logger.exception("Error consultando visitantes activos")
        return jsonify({"error": "No fue posible consultar los visitantes activos."}), 500
    respuesta = []
    for visitante in visitantes:
        registro = dict(visitante)
        registro["equipos"] = equipos_para_respuesta(registro["equipos"])
        respuesta.append(registro)
    return jsonify({"visitantes": respuesta})


@app.post("/api/ingresos/<int:registro_id>/salida")
def registrar_hora_salida(registro_id: int):
    try:
        registrado = registrar_salida(registro_id)
    except DatabaseError:
        app.logger.exception("Error registrando la salida del visitante")
        return jsonify({"error": "No fue posible registrar la salida."}), 500
    if not registrado:
        return (
            jsonify({"error": "El ingreso ya no está activo o no existe."}),
            409,
        )
    return jsonify({"message": "Salida registrada correctamente."})


@app.get("/api/historial")
def listar_historial():
    try:
        registros = obtener_historial()
    except DatabaseError:
        app.logger.exception("Error consultando el historial de ingresos")
        return jsonify({"error": "No fue posible consultar el historial."}), 500
    respuesta = []
    for registro in registros:
        item = dict(registro)
        item["equipos"] = equipos_para_respuesta(item["equipos"])
        respuesta.append(item)
    return jsonify({"registros": respuesta})


@app.get("/recepcion/historial/exportar")
def exportar_historial():
    fecha = request.args.get("fecha")
    if "fecha" in request.args:
        try:
            fecha_validada = datetime.strptime(fecha or "", "%Y-%m-%d").strftime(
                "%Y-%m-%d"
            )
        except ValueError:
            return jsonify({"error": "La fecha debe tener formato AAAA-MM-DD."}), 400
        if fecha_validada != fecha:
            return jsonify({"error": "La fecha debe tener formato AAAA-MM-DD."}), 400
    else:
        fecha = None

    try:
        registros = obtener_historial(fecha)
    except DatabaseError:
        app.logger.exception("Error consultando el historial para exportación")
        return jsonify({"error": "No fue posible exportar el historial."}), 500

    salida = io.StringIO(newline="")
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(
        [
            "ID",
            "Fecha",
            "Hora de ingreso",
            "Hora de salida",
            "Estado",
            "Categoría",
            "Cédula",
            "Nombre",
            "Empresa",
            "ARL",
            "EPS",
            "Teléfono",
            "Persona visitada",
            "Equipos o herramientas",
            "Autorizó tratamiento de datos",
            "Acuerdo de confidencialidad",
            "Firma guardada",
        ]
    )

    def celda_segura(valor: object) -> str:
        texto = str(valor if valor is not None else "")
        if texto.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
            return "'" + texto
        return texto

    for registro in registros:
        equipos = equipos_para_respuesta(registro["equipos"])
        if isinstance(equipos, list):
            equipos_texto = " | ".join(
                "Marca: {marca}, Referencia: {referencia}, Serie: {serie}".format(
                    marca=equipo.get("marca", ""),
                    referencia=equipo.get("referencia", ""),
                    serie=equipo.get("serie", ""),
                )
                for equipo in equipos
                if isinstance(equipo, dict)
            ) or "Ninguno"
        else:
            equipos_texto = str(equipos)

        escritor.writerow(
            celda_segura(valor)
            for valor in (
                registro["id"],
                registro["fecha"],
                registro["hora_ingreso"],
                registro["hora_salida"] or "",
                registro["estado"],
                registro["categoria"],
                registro["cedula"],
                registro["nombre"],
                registro["empresa"],
                registro["arl"],
                registro["eps"],
                registro["telefono"],
                registro["persona_visita"],
                equipos_texto,
                "Sí" if registro["autorizacion_datos"] else "No",
                "Sí" if registro.get("acuerdo_confidencialidad") else "No",
                "Sí" if registro["tiene_firma"] else "No",
            )
        )

    sufijo_fecha = f"_{fecha}" if fecha else ""
    nombre_archivo = (
        f"historial_gotuplas{sufijo_fecha}_{datetime.now():%Y%m%d_%H%M%S}.csv"
    )
    return app.response_class(
        salida.getvalue().encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )


@app.get("/api/ingresos/<int:registro_id>/firma")
def consultar_firma(registro_id: int):
    try:
        firma = obtener_firma(registro_id)
    except DatabaseError:
        app.logger.exception("Error consultando la firma del ingreso")
        return jsonify({"error": "No fue posible consultar la firma."}), 500
    if firma is None:
        return jsonify({"error": "Este ingreso no tiene una firma disponible."}), 404
    return app.response_class(
        firma,
        mimetype="image/png",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/ingresos/<int:registro_id>/acuerdo-pdf")
def descargar_acuerdo_pdf(registro_id: int):
    try:
        registro = obtener_registro(registro_id)
    except DatabaseError:
        app.logger.exception("Error consultando registro para acuerdo PDF")
        return jsonify({"error": "No fue posible consultar el registro."}), 500
    if registro is None:
        return jsonify({"error": "El registro especificado no existe."}), 404

    firma = registro.get("firma")
    if isinstance(firma, memoryview):
        firma = firma.tobytes()

    try:
        pdf_bytes = generar_acuerdo_pdf(dict(registro), firma)
    except Exception:
        app.logger.exception("Error generando el PDF del acuerdo")
        return jsonify({"error": "No fue posible generar el acuerdo de confidencialidad."}), 500

    nombre_archivo = f"acuerdo_confidencialidad_{registro['cedula']}_{registro['id']}.pdf"
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=nombre_archivo,
    )


if __name__ == "__main__":
    from waitress import serve

    init_db()
    with db_connection() as connection:
        visitor_accounts = connection.execute(
            "SELECT usuario, password_hash, rol FROM cuentas_recepcion"
        ).fetchall()
    migrate_legacy_accounts(
        "visitantes",
        [dict(account) for account in visitor_accounts],
    )
    port = int(os.environ.get("GOTUPLAS_PORT", "8501"))
    serve(app, host="0.0.0.0", port=port)
