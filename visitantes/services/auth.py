from werkzeug.security import generate_password_hash

from shared_sso import (
    authenticate,
    create_account,
    has_role,
    update_password,
)


def autenticar_usuario(usuario: str, clave: str) -> dict[str, str] | None:
    cuenta = authenticate(usuario.strip(), clave)
    if cuenta is None or cuenta["rol_visitantes"] not in {
        "recepcion",
        "administrador",
    }:
        return None
    return {"usuario": cuenta["usuario"], "rol": cuenta["rol_visitantes"]}


def crear_primera_cuenta(usuario: str, clave: str) -> bool:
    return create_account(
        usuario.strip(),
        generate_password_hash(clave),
        "administrador",
        "admin",
        allow_existing_without_visitor_role=True,
    )


def crear_usuario(usuario: str, clave: str, rol: str) -> bool:
    return create_account(
        usuario.strip(),
        generate_password_hash(clave),
        rol,
        "admin" if rol == "administrador" else "lectura",
        allow_existing_without_visitor_role=True,
    )


def cambiar_clave_usuario(usuario: str, clave: str) -> bool:
    return update_password(usuario.strip(), generate_password_hash(clave))


def hay_cuenta_recepcion() -> bool:
    return has_role("visitantes")
