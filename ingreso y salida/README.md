# Control de salidas del personal

Aplicación web para controlar las salidas del personal de las instalaciones durante su turno, sus motivos y destinos, los regresos y los movimientos que no tendrán regreso durante ese turno.

## Funcionalidades

- Registro de empleados con documento, nombre, área y cargo.
- Enlace público `/salidas` para que el personal registre su salida usando el documento, el motivo y el destino.
- Si regresa durante el turno, el empleado registra el regreso en el mismo enlace.
- Después de registrar una salida o un regreso, la página se limpia y se actualiza automáticamente para la siguiente persona.
- Al salir, el empleado puede indicar que no regresará durante ese turno.
- La firma del empleado se dibuja en pantalla al registrar la salida y queda asociada al movimiento.
- Panel administrativo con la lista de empleados que están fuera y el historial de salidas, motivos, destinos, firmas y regresos.
- El panel permite regularizar un regreso que quedó pendiente, registrando administrador, fecha del ajuste y motivo. Si no se conoce la hora real, se marca como no confirmada; si se ingresa una hora real, se exige describir la evidencia.
- Reporte imprimible por fecha que reproduce las columnas del formato FO-SST-06 / PO-SST-01, con hasta 25 registros por página. Se puede imprimir o guardar como PDF desde el navegador.
- Exportación del historial a CSV compatible con Excel.
- Panel protegido con cuenta administradora y contraseña almacenada mediante hash.
- Los administradores pueden crear cuentas de consulta de solo lectura para revisar el personal fuera, el historial, las firmas, los reportes y la exportación CSV. Esas cuentas no pueden administrar empleados ni modificar registros.
- Inicio de sesión único con el control de visitantes: ambos módulos comparten las cuentas y la sesión revocable cuando se abren usando el mismo host/IP. El rol administrador de visitantes se asigna como administrador de ingreso/salida; recepción obtiene solo lectura.
- Base de datos SQLite creada automáticamente en `instance/ingresos_personal.db`.

## Instalación e inicio en Windows

Desde PowerShell, en la carpeta del proyecto:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\iniciar.ps1
```

También puede ejecutar `iniciar.bat` después de instalar las dependencias. Abra `http://localhost:8501/admin` para el panel administrativo. En el primer inicio, cree la cuenta administradora; luego inicie sesión y registre los empleados. El personal puede usar `http://localhost:8501/salidas`; el enlace también aparece en el panel admin. La ruta anterior `/asistencia` redirige al nuevo enlace.

La aplicación escucha en todas las interfaces para permitir el acceso desde la red local. Para cambiar el puerto, defina `INGRESOS_PORT` en `.env`. Restrinja el acceso mediante el firewall a la red privada de la empresa. Para exponer el sistema fuera de una red confiable, configure HTTPS y una clave persistente en `INGRESOS_SECRET_KEY`.

La interfaz pública sigue el estilo visual de GOTUPLAS e identifica el formato FO-SST-06 y el procedimiento PO-SST-01. Está optimizada para tabletas en posición vertical y horizontal, con controles grandes para uso táctil. La firma se puede dibujar directamente sobre el área de firma con el dedo o un lápiz digital.

El acceso público identifica al empleado únicamente por su documento y firma dibujada; por tanto, no verifica por sí solo que quien registra la salida sea el titular. Comparta ese enlace solo en la red interna y tenga en cuenta esta limitación al interpretar los registros. El destino se conserva como dato adicional en el historial, pero no se imprime porque no forma parte de las columnas del formato.

## Datos y respaldo

Visitantes e ingreso/salida comparten una sesión revocable guardada en `%LOCALAPPDATA%\GOTUPLAS\shared_sso.db`. Ambos servidores deben ejecutarse con el mismo usuario de Windows y los usuarios deben entrar a los dos módulos usando el mismo host, por ejemplo `192.168.0.55`, aunque los puertos sean diferentes.

Al iniciar cada aplicación por primera vez después de esta actualización, se importan sus cuentas existentes. Se conservan los usuarios y sus permisos; para usuarios que existían en ambos módulos, se conserva la contraseña de visitantes y se combinan los roles. En esta instalación los roles duplicados son compatibles. Cerrar sesión en cualquiera de los módulos cierra la sesión en ambos; las sesiones vencen después de 8 horas.

Reinicia los dos servidores para aplicar la migración. El sistema continúa funcionando en la red local por HTTP; usa HTTPS mediante un proxy si se expondrá a redes no confiables.

Los registros se guardan en `instance/ingresos_personal.db`. Para respaldar la información, detenga la aplicación y copie ese archivo a una ubicación segura. No comparta ni publique la base de datos: contiene información personal del personal.
