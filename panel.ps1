# Reinicia el panel Streamlit recargando TODO el codigo.
#
# Por que hace falta: Streamlit detecta cambios en app.py y vuelve a ejecutarlo,
# pero NO recarga los modulos ya importados de src/. Si se edita cualquier archivo
# de src/ (queries.py, informe.py, modelo.py...), el servidor sigue usando la
# version antigua y aparecen errores del tipo:
#     AttributeError: module 'src.queries' has no attribute '...'
# Este script libera el puerto y arranca un proceso nuevo.
#
# Uso:  .\panel.ps1

$ErrorActionPreference = 'SilentlyContinue'
Set-Location $PSScriptRoot

$puerto = 8501

$ocupado = Get-NetTCPConnection -LocalPort $puerto -State Listen -ErrorAction SilentlyContinue
foreach ($conexion in $ocupado) {
    Write-Host "Deteniendo el proceso $($conexion.OwningProcess) que ocupa el puerto $puerto..." -ForegroundColor Yellow
    Stop-Process -Id $conexion.OwningProcess -Force
}
if ($ocupado) { Start-Sleep -Seconds 3 }

Write-Host "Arrancando el panel en http://localhost:$puerto" -ForegroundColor Green
& "$PSScriptRoot\.venv\Scripts\python.exe" -m streamlit run app.py `
    --server.port $puerto `
    --server.headless true `
    --server.address 127.0.0.1 `
    --browser.gatherUsageStats false
