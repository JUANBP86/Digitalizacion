# GOTUPLAS — Control de ingreso de visitantes

## Pantallas y privacidad

- La ruta `/` es la pantalla pública del visitante. Solo muestra el campo de documento al abrir; después de consultar, presenta el formulario con los datos frecuentes autocompletados o vacío para una primera visita.
- La ruta `/recepcion/login` pide las credenciales de recepción.
- La ruta `/recepcion` muestra visitantes activos e historial solo después de iniciar sesión.
- Inicio de sesión único con ingreso y salida cuando ambos módulos se abren usando el mismo host/IP. Las cuentas administradoras de visitantes administran ambos módulos; recepción tiene solo lectura en ingreso/salida.
- Los administradores pueden crear, eliminar y cambiar la contraseña de las cuentas desde **Administrar usuarios**. Las nuevas contraseñas deben tener al menos 6 caracteres y se guardan como hash.
- Las API de activos, historial y registro de salida también exigen una sesión de recepción; ocultar enlaces no es la protección.
- El formulario de visitante solicita autorización para el tratamiento de datos personales y la aceptación del **Acuerdo de Confidencialidad para Visitantes**. El visitante puede consultar las cláusulas del acuerdo en `/acuerdo-confidencialidad` antes de aceptar.
- La política de tratamiento de datos se muestra como páginas de imagen dentro del navegador para que también pueda leerse en tablets cuyo visor web no abre PDF directamente.
- Al registrar el ingreso con la firma dibujada en pantalla, el sistema genera automáticamente el documento legal en PDF de 2 páginas con las 10 cláusulas completas, rellenando el nombre del visitante, su documento de identidad, empresa, fecha actual y estampando su firma digital en la sección "EL VISITANTE".
- Desde el panel de recepción (`/recepcion`), tanto en la lista de visitantes activos como en el historial, el personal puede abrir y descargar el PDF oficial generado (`/api/ingresos/<id>/acuerdo-pdf`) para imprimirlo o archivarlo digitalmente.
- La exportación en CSV del historial incluye una columna indicando si el acuerdo de confidencialidad fue aceptado.

## Inicio de sesión compartido

Visitantes e ingreso/salida comparten una sesión revocable guardada en `%LOCALAPPDATA%\GOTUPLAS\shared_sso.db`. Ambos servidores deben ejecutarse con el mismo usuario de Windows y los usuarios deben entrar a los dos módulos usando el mismo host, por ejemplo `192.168.0.55`, aunque los puertos sean diferentes.

Al iniciar cada aplicación por primera vez después de esta actualización, se importan sus cuentas existentes. Se conservan los usuarios y sus permisos; para usuarios que existían en ambos módulos, se conserva la contraseña de visitantes y se combinan los roles. En esta instalación los roles duplicados son compatibles. Cerrar sesión en cualquiera de los módulos cierra la sesión en ambos; las sesiones vencen después de 8 horas.

Reinicia los dos servidores para aplicar la migración. El sistema continúa funcionando en la red local por HTTP; usa HTTPS mediante un proxy si se expondrá a redes no confiables.

## Configuración de PostgreSQL

1. Abre el archivo `.env` en la raíz del proyecto y configura tu contraseña de PostgreSQL:
   ```env
   DATABASE_URL=postgresql://postgres:tu_password_aqui@localhost:5432/visitantes_gotuplas
   ```
2. Si deseas migrar los datos existentes de SQLite (`visitantes_gotuplas.db`) hacia PostgreSQL, ejecuta el script de migración:
   ```powershell
   .\.venv\Scripts\python.exe migrar_a_postgres.py
   ```
   Este script se encargará automáticamente de crear la base de datos `visitantes_gotuplas` (si aún no existe), crear las tablas e índices, y transferir todos los visitantes, registros históricos, firmas dibujadas y cuentas de recepción existentes.

## Iniciar en Windows

Haz doble clic en `iniciar.bat` para arrancar el servidor. También puedes iniciarlo desde PowerShell, en esta carpeta:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\iniciar.ps1
```

El archivo `iniciar.bat` utiliza el Python del entorno virtual `.venv` y mantiene abierta la ventana para mostrar errores. La aplicación genera una clave de sesión al arrancar. Si todavía no has instalado las dependencias, ejecuta primero el comando `pip install` anterior.

Si la versión anterior sigue abierta en una terminal, deténgala con `Ctrl+C` antes de iniciar esta. Si el puerto 8501 está ocupado por otro proceso, puede usar otro puerto:

```powershell
$env:GOTUPLAS_PORT = "8502"
.\iniciar.bat
```

En la primera ejecución (si no realizas migración), abre `/recepcion/login` y pulsa **Crear cuenta de recepción**. Define un usuario de al menos 3 caracteres y una contraseña de al menos 6 caracteres. Después utiliza esa cuenta en el formulario normal de inicio de sesión. La contraseña se guarda como hash seguro en la base de datos PostgreSQL, nunca en texto plano.

En el servidor, abre `http://localhost:8501`. Desde las tablets de la intranet, visita `http://<IP-del-servidor>:8501`. Para recepción, abre `http://<IP-del-servidor>:8501/recepcion/login`. Si el puerto 8501 ya está ocupado, configure `GOTUPLAS_PORT` antes de iniciar.

Permite el puerto TCP 8501 en el firewall de Windows únicamente para la red privada de la empresa. Para redes no confiables, configura HTTPS con un proxy corporativo antes de enviar credenciales o datos personales.

## Base de Datos

La aplicación ahora utiliza PostgreSQL como base de datos de producción con pool de conexiones (`psycopg_pool`), lo que garantiza alta concurrencia y soporte multi-hilo en Waitress. La base SQLite original permanece como respaldo en `visitantes_gotuplas.db` sin ser eliminada.
