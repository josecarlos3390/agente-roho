#Requires -Version 5.1
<#
.SYNOPSIS
    Instala el proyecto en Windows: entorno virtual, dependencias y .env.local.

.DESCRIPTION
    Detecta un Python compatible (3.10-3.13), crea .venv, instala los requisitos,
    prepara .env.local a partir de la plantilla y ejecuta las comprobaciones.

    Prefiere 'uv' si está instalado (puede descargar un Python compatible y es
    mucho más rápido); si no, usa py/python del sistema.

.EXAMPLE
    .\setup.ps1
#>

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Paso { param([string]$Texto) Write-Host "==> $Texto" -ForegroundColor Cyan }
function Aviso { param([string]$Texto) Write-Host "    $Texto" -ForegroundColor Yellow }
function Bien { param([string]$Texto) Write-Host "    $Texto" -ForegroundColor Green }

Paso "Comprobando herramientas"

$tieneUv = [bool](Get-Command uv -ErrorAction SilentlyContinue)
$tienePy = [bool](Get-Command py -ErrorAction SilentlyContinue)
$tienePython = [bool](Get-Command python -ErrorAction SilentlyContinue)

if ($tieneUv) { Bien "uv encontrado: se usará para crear el entorno" }
elseif ($tienePy -or $tienePython) { Aviso "uv no está instalado: se usará el Python del sistema" }
else {
    Write-Host "No se encontró Python." -ForegroundColor Red
    Write-Host "Instala Python 3.12 desde https://www.python.org/downloads/ (marca 'Add python.exe to PATH')"
    Write-Host "o instala uv desde https://docs.astral.sh/uv/ y vuelve a ejecutar este script."
    exit 1
}

Paso "Creando el entorno virtual (.venv)"
if (Test-Path -LiteralPath ".venv") {
    Aviso ".venv ya existe: se reutiliza"
} elseif ($tieneUv) {
    & uv venv .venv --python 3.12
    if ($LASTEXITCODE -ne 0) { & uv venv .venv }
} else {
    $base = if ($tienePy) { 'py' } else { 'python' }
    $args = if ($tienePy) { @('-3', '-m', 'venv', '.venv') } else { @('-m', 'venv', '.venv') }
    & $base @args
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "No se pudo crear el entorno virtual." -ForegroundColor Red
    exit 1
}

$version = & $python -c "import sys; print('%d.%d' % sys.version_info[:2])"
Bien "Python del entorno: $version"
if ([version]$version -ge [version]'3.14') {
    Aviso "Python $version es muy nuevo: pyodbc puede no tener rueda precompilada."
    Aviso "Si falla la instalación, instala uv (https://docs.astral.sh/uv/) y repite."
}

Paso "Instalando dependencias"
if ($tieneUv) {
    & uv pip install --python $python -r requirements.txt
} else {
    & $python -m pip install --upgrade pip
    & $python -m pip install -r requirements.txt
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "Falló la instalación de dependencias." -ForegroundColor Red
    Write-Host "Recuerda que hace falta el 'ODBC Driver 17 o 18 for SQL Server' instalado en el sistema."
    exit 1
}

Paso "Preparando la configuración"
if (Test-Path -LiteralPath ".env.local") {
    Aviso ".env.local ya existe: no se toca"
} else {
    Copy-Item -LiteralPath ".env.local.example" -Destination ".env.local"
    Bien "Creado .env.local a partir de la plantilla"
    Aviso "EDÍTALO ahora con tu servidor, base, usuario, contraseña y tabla."
}

Paso "Comprobando la instalación"
& $python verificar.py

Write-Host ""
Write-Host "Listo. Siguientes pasos:" -ForegroundColor Green
Write-Host "  1. Edita .env.local (servidor, base, usuario, contraseña y tabla)."
Write-Host "  2. Panel:            .\panel.ps1"
Write-Host "  3. Informe mensual:  .venv\Scripts\python.exe informe_mensual.py --excel"
Write-Host "  4. Servidor MCP:     ya declarado en .mcp.json (Claude Code / VS Code)"
