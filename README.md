# agente-roho

Panel web de informes y **servidor MCP** sobre **SQL Server en modo solo lectura**.

Lee una tabla de hechos de ventas, calcula las agregaciones **en el servidor**
(kilobytes en lugar de millones de filas) y produce:

- **Panel interactivo** (Streamlit + Plotly) con filtros, tablas y gráficos.
- **Informe ejecutivo mensual** con comparativos mes a mes e interanual, alertas de
  margen y conclusiones automáticas.
- **Servidor MCP** para consultar los informes desde Claude Code, Codex CLI,
  VS Code/Copilot, Cursor, Claude Desktop, Gemini CLI o Windsurf.
- Exportación a **Excel** multi-hoja y a CSV.

El proyecto está preparado desde el inicio para crecer a **multiusuario**, con el
acceso a los datos acotado por usuario (ver [Modelo de seguridad](#modelo-de-seguridad)).

---

## Requisitos

| Necesidad | Detalle |
|---|---|
| Python | 3.10 – 3.13 (evita 3.14: `pyodbc` puede no tener rueda precompilada) |
| Controlador ODBC | *ODBC Driver 17 o 18 for SQL Server*, instalado en el sistema |
| Acceso | Un login de SQL Server **de solo lectura** a la base y tabla a informar |
| Opcional | [uv](https://docs.astral.sh/uv/) — simplifica y acelera la instalación |

Instalar el controlador ODBC:
[Windows](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) ·
[macOS/Linux (msodbcsql18)](https://learn.microsoft.com/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server)

## Instalación

### Windows (recomendado)

```powershell
git clone <url-del-repositorio>
cd agente-roho
.\setup.ps1
```

El script detecta Python, crea `.venv`, instala las dependencias, prepara
`.env.local` desde la plantilla y ejecuta las comprobaciones.

### macOS / Linux, o con uv

```bash
git clone <url-del-repositorio>
cd agente-roho
uv sync                                    # crea .venv e instala dependencias
cp .env.local.example .env.local           # y edítalo con tus datos
```

<details>
<summary>Instalación manual (sin uv)</summary>

```bash
python -m venv .venv
# Windows
.venv\Scripts\python.exe -m pip install -r requirements.txt
# macOS / Linux
.venv/bin/python -m pip install -r requirements.txt
```
</details>

## Configuración

Copia `.env.local.example` a `.env.local` y rellena tus datos. **Ese archivo está
en `.gitignore`: nunca se sube al repositorio.**

```ini
MSSQL_CONNSTRING=Server=HOST\INSTANCIA,1433;Database=BASE_DE_DATOS;User Id=USUARIO;Password=CLAVE;TrustServerCertificate=Yes;Encrypt=Yes
MSSQL_TABLE=dbo.MiTabla
REPORT_USER=local
```

Comprueba la conexión antes de nada:

```powershell
.venv\Scripts\python.exe explorar.py            # inventario: bases, tablas, índices
.venv\Scripts\python.exe explorar.py --tabla dbo.MiTabla
```

## Uso

```powershell
# Panel web
.\panel.ps1                                     # http://localhost:8501

# Informe ejecutivo por consola
.venv\Scripts\python.exe informe_mensual.py                     # último mes cerrado
.venv\Scripts\python.exe informe_mensual.py --mes 2026-09 --umbral 18 --excel

# Análisis exploratorio con medición de tiempos
.venv\Scripts\python.exe analisis.py --auto

# Comprobaciones
.venv\Scripts\python.exe verificar.py           # datos, SQL, informe y panel
.venv\Scripts\python.exe verificar_mcp.py       # servidor MCP de extremo a extremo

# Servidor MCP por stdio (normalmente lo lanza el cliente de IA)
.venv\Scripts\python.exe servidor_mcp.py
```

Sin `.env.local` el panel arranca en **modo demo** con datos sintéticos, útil para
probar sin acceso a la base.

## Integración con agentes de IA (MCP)

El servidor MCP expone **7 herramientas de solo lectura**:

| Herramienta | Para qué |
|---|---|
| `estado_conexion` | Comprobar conexión, tabla, última fecha y alcance |
| `meses_disponibles` | Listar los meses con datos (para elegir uno válido) |
| `informe_ejecutivo` | Informe del mes: cifras, comparativos y conclusiones |
| `tabla_dimension` | Tabla comparativa de categoría, tienda, marca, canal, familia, proveedor o tipo de transacción |
| `serie_mensual` | Serie de venta, costo, margen y margen % |
| `buscar_articulos` | Agregado por artículo a partir de un texto |
| `ejecutar_consulta` | SQL de solo lectura, validado y con tope de filas (último recurso) |

El servidor **no recibe credenciales por variables de entorno**: lee `.env.local`
por sí mismo, así que ningún archivo versionado contiene secretos.

### Claude Code

Ya está declarado en [.mcp.json](.mcp.json) (ámbito de proyecto). Alternativa por comando:

```bash
claude mcp add --transport stdio --scope project agente-roho -- uv run servidor_mcp.py
```

### Codex CLI

Ya está en [.codex/config.toml](.codex/config.toml) (proyectos de confianza). Para
tenerlo en todos los proyectos, copia esto a `~/.codex/config.toml`:

```toml
[mcp_servers.agente-roho]
command = "uv"
args = ["run", "servidor_mcp.py"]
cwd = "."
```

### VS Code / GitHub Copilot

`.mcp.json` en la raíz del workspace (formato portable, es el recomendado):

```json
{
  "mcpServers": {
    "agente-roho": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "servidor_mcp.py"]
    }
  }
}
```

Si prefieres el formato propio de VS Code (`.vscode/mcp.json`, hoy en desuso), la
clave se llama `servers` en lugar de `mcpServers`.

### Cursor

`.cursor/mcp.json` en el proyecto, o `~/.cursor/mcp.json` para todos. La clave
`type` es obligatoria en Cursor:

```json
{
  "mcpServers": {
    "agente-roho": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "servidor_mcp.py"]
    }
  }
}
```

### Claude Desktop

- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "agente-roho": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "servidor_mcp.py"]
    }
  }
}
```

### Gemini CLI y Windsurf

```jsonc
// ~/.gemini/settings.json  (o .gemini/settings.json en el proyecto)
{ "mcpServers": { "agente-roho": { "command": "uv", "args": ["run", "servidor_mcp.py"] } } }
```

```jsonc
// Windsurf: ~/.codeium/windsurf/mcp_config.json
{ "mcpServers": { "agente-roho": { "command": "uv", "args": ["run", "servidor_mcp.py"] } } }
```

### Si no tienes `uv`

Sustituye el comando por el intérprete del entorno virtual y deja `args` como
`["servidor_mcp.py"]`:

- Windows: `.venv\\Scripts\\python.exe`
- macOS/Linux: `.venv/bin/python`

### Instrucciones para agentes

[AGENTS.md](AGENTS.md) es la fuente única de instrucciones (lo leen Codex, Cursor,
Copilot, Gemini CLI y otros) y [CLAUDE.md](CLAUDE.md) lo importa con `@AGENTS.md`
para Claude Code. Ahí están las reglas de seguridad, las convenciones y los
criterios de interpretación del negocio.

## Informe ejecutivo mensual

`src/informe.py` calcula, con dos agregaciones (serie mensual y mes × dimensión):

- **Cifras del mes**: venta, costo, margen, margen %, unidades, líneas, importe
  medio por línea, variación frente al mes anterior y al mismo mes del año previo,
  puntos de margen ganados o perdidos, y acumulado del año contra el mismo tramo.
- **Tablas comparativas** por categoría, tienda, marca y tipo de transacción, con
  participación, variación MoM/YoY y salto de margen en puntos.
- **Lectura del mes**: conclusiones generadas con **reglas explícitas**, incluida la
  alerta de las dimensiones por debajo del umbral de margen.

Dos reglas de rigor que conviene conocer:

1. **Variaciones sobre base diminuta se marcan como `base baja`** y se excluyen de
   las conclusiones. Sin esto, una categoría nueva puede aparecer con +7.000%
   interanual y arruinar la lectura.
2. **El umbral de margen es un parámetro** (`--umbral`, `umbral_margen`; 15% por
   defecto), no un adjetivo.

El mes por defecto es el **último mes cerrado**: si el último dato es del mes en
curso, no se toma como mes completo y se avisa.

## Adaptarlo a otra tabla

1. En `.env.local`, apunta `MSSQL_TABLE` a tu tabla.
2. En [src/modelo.py](src/modelo.py), cambia los nombres de columna del mapeo
   (fecha, transacción, artículo, descripción, categoría, familia, marca,
   proveedor, tienda, canal, cantidad, importe, costo, margen).

El resto del proyecto no necesita cambios: las consultas, el panel, el informe y
el servidor MCP trabajan con nombres lógicos.

## Modelo de seguridad

Tres capas, de la más débil a la más fuerte:

1. **Login de base de datos con permisos mínimos** (`db_datareader` sobre lo
   necesario, sin escritura). Además la conexión se abre con `readonly=True`.
2. **Alcance en la aplicación** ([src/scope.py](src/scope.py)): el filtro por filas
   se inyecta **en el SQL**, con parámetros. Nunca se filtra un DataFrame ya
   cargado: eso es lo que produce fugas cuando alguien añade una página nueva y
   olvida filtrar.
3. **RLS en SQL Server** ([sql/rls_plantilla.sql](sql/rls_plantilla.sql)): el motor
   decide qué filas existen para el usuario. Aunque la aplicación tenga un bug, la
   base filtra.

Además, el SQL libre que pueda enviar un agente pasa por
[src/seguridad_sql.py](src/seguridad_sql.py): solo se permiten consultas que
empiecen por `SELECT`, `WITH` o `DECLARE`, y se bloquean escrituras, DDL, `EXEC`,
`xp_cmdshell`, `BACKUP`, `GRANT` y sentencias múltiples peligrosas.

La configuración de alcance vive en una tabla (`seguridad.UsuarioAlcance`), así que
dar de alta a un usuario o cambiar su alcance es un `INSERT`, no un despliegue.

Para **autenticación de usuarios**, dos caminos cuando llegue el momento:

- **Microsoft Entra ID** con el login nativo de Streamlit (`st.login()` / `st.user`).
- **`streamlit-authenticator`** (bcrypt + cookies) si se prefieren usuarios locales.

> `SESSION_CONTEXT` (usado en la plantilla RLS) lo fija la propia aplicación, así
> que protege contra errores de la app, no contra quien controla la conexión. Para
> defensa real de extremo a extremo, la identidad de cada persona debe viajar en la
> conexión (Entra ID o usuarios contenidos por persona).

## Estructura

```
app.py                  Panel Streamlit (4 pestañas). No construye SQL.
panel.ps1               Reinicia el panel liberando el puerto (necesario tras editar src/).
informe_mensual.py      Informe ejecutivo por consola + Excel.
analisis.py             Análisis exploratorio con medición de tiempos.
explorar.py             Inventario del servidor SQL y perfil de una tabla.
diagnostico_conexion.py Diagnóstico de conexión sin exponer credenciales.
servidor_mcp.py         Servidor MCP (stdio) para agentes de IA.
setup.ps1               Instalador para Windows.
verificar.py            Pruebas del proyecto.
verificar_mcp.py        Pruebas del servidor MCP.
src/config.py           Lectura de .env.local y validación de nombres.
src/db.py               Conexión pyodbc solo lectura.
src/modelo.py           Mapeo lógico -> columnas reales.
src/queries.py          Todo el SQL, parametrizado.
src/scope.py            Alcance por usuario (quién ve qué filas).
src/seguridad_sql.py    Guardas de solo lectura para SQL libre.
src/informe.py          Cálculos del informe (funciones puras).
src/demo.py             Datos sintéticos para el modo demo.
sql/rls_plantilla.sql   Plantilla de RLS de SQL Server.
.mcp.json               Servidor MCP para Claude Code / VS Code.
.codex/config.toml      Servidor MCP para Codex CLI.
AGENTS.md / CLAUDE.md   Instrucciones para agentes de IA.
```

## Rendimiento

- El panel pide **agregaciones**; el detalle es opcional y está limitado a 200.000
  filas. Acota el periodo: "todo el histórico" recorre la tabla entera.
- Los resultados se cachean en el panel (5–30 min) y se pueden refrescar desde la
  barra lateral.
- Los tiempos dependen del *buffer pool* del servidor: si el servidor se reinicia o
  libera memoria, el primer escaneo de una tabla grande será mucho más lento.
- Si la tabla no tiene índice por fecha, un `CLUSTERED INDEX` sobre la columna de
  fecha acelera muchísimo los informes por rango. Requiere ventana de cambio.

## Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| `AttributeError: module 'src.x' has no attribute ...` en el panel | Streamlit no recarga los módulos de `src/` ya importados | Reinicia con `.\panel.ps1` |
| `Invalid connection string attribute` al conectar | El controlador ODBC rechaza la forma de cadena | Ya resuelto: `src/db.py` descompone la cadena en parámetros |
| `Neither DSN nor SERVER keyword supplied` | Falta `Server=` o `DRIVER` | Revisa `MSSQL_CONNSTRING`; el controlador se añade solo si falta |
| `Can't open lib 'ODBC Driver 17 for SQL Server'` | Falta el controlador ODBC | Instálalo (ver Requisitos) |
| `ModuleNotFoundError: pyodbc` al instalar | Python 3.14 sin rueda precompilada | Usa Python 3.10–3.13 o instala con `uv` |
| `Login failed for user ''` | La cadena perdió el usuario | Comprueba `User Id=` en `.env.local` |
| El servidor MCP no arranca en el cliente | El cliente no arranca el proceso en la raíz del proyecto | Usa `uv run --directory <ruta> servidor_mcp.py` o una ruta absoluta al intérprete |

## Privacidad

Este repositorio **no debe contener** direcciones de servidores, nombres de bases,
logins ni cifras de negocio reales. Las credenciales viven en `.env.local` y los
informes y extracciones en `out/`; ambos están en `.gitignore`.
