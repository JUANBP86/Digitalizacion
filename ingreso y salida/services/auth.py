from werkzeug.security import generate_password_hash

from shared_sso import authenticate, create_account


def validar_credenciales(usuario: str, clave: str) -> dict[str, str] | None:
    cuenta = authenticate(usuario.strip(), clave)
    if cuenta is None or not cuenta["rol_ingresos"]:
        return None
    return {
        "usuario": str(cuenta["usuario"]),
        "rol": str(cuenta["rol_ingresos"]),
    }


def crear_primera_cuenta(usuario: str, clave: str) -> bool:
    return create_account(
        usuario.strip(),
        generate_password_hash(clave),
        None,
        "admin",
        allow_existing_without_visitor_role=True,
    )


def crear_cuenta_consulta(usuario: str, clave: str) -> None:
    creada = create_account(
        usuario.strip(),
        generate_password_hash(clave),
        None,
        "lectura",
    )
    if not creada:
        raise ValueError(f"Ya existe una cuenta con el usuario '{usuario}'.")
