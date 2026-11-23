$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "No se encontró el Python del entorno en $python. Instale las dependencias primero."
}

$env:GOTUPLAS_SECRET_KEY = & $python -c "import secrets; print(secrets.token_hex(32))"

try {
    & $python (Join-Path $PSScriptRoot "app.py")
    if ($LASTEXITCODE -ne 0) {
        throw "El servidor terminó con código de error $LASTEXITCODE."
    }
}
finally {
    Remove-Item Env:GOTUPLAS_SECRET_KEY -ErrorAction SilentlyContinue
}
