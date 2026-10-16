# AGENTS.md — Instrucciones para agentes de IA

Este archivo es la **fuente única** de instrucciones del proyecto. `CLAUDE.md` lo
importa con `@AGENTS.md`, y Codex, Cursor, Copilot y otros lo leen directamente.

## Qué es este proyecto

Panel web de informes (Streamlit + Plotly + pandas) y **servidor MCP** sobre una
base **SQL Server en solo lectura**. Lee una tabla de hechos de ventas, calcula
agregaciones en el servidor y produce informes ejecutivos mensuales.

Todo el código, los nombres de variables y los informes están **en español**.

## Instalación

```powershell
# Windows (recomendado)
.\setup.ps1
```

```bash
# macOS / Linux, o si prefieres uv
uv sync                                  # crea .venv e instala dependencias
cp .env.local.example .env.local         # y rellena tus datos de conexión
```

Requisitos: Python 3.10–3.13, y el **controlador ODBC de SQL Server**
(*ODBC Driver 17 o 18 for SQL Server*). `pyodbc` viene en los `requirements`.

## Ejecución

```powershell
.venv\Scripts\python.exe -m streamlit run app.py     # panel: http://localhost:8501
.\panel.ps1                                          # reinicia el panel (ver aviso abajo)
.venv\Scripts\python.exe informe_mensual.py --excel  # informe ejecutivo + Excel
.venv\Scripts\python.exe verificar.py                # pruebas del proyecto
.venv\Scripts\python.exe verificar_mcp.py            # pruebas del servidor MCP
.venv\Scripts\python.exe explorar.py                 # inventario del servidor SQL
.venv\Scripts\python.exe servidor_mcp.py             # servidor MCP por stdio
```

> **Aviso importante:** Streamlit recarga `app.py` al guardarlo, pero **no** los
> módulos de `src/` ya importados. Tras editar cualquier archivo de `src/`, hay que
> reiniciar con `.\panel.ps1`, o el servidor seguirá usando el código antiguo y
> aparecerán errores del tipo `AttributeError: module 'src.queries' has no
> attribute ...`.

## Reglas de seguridad (no negociables)

1. **Solo lectura.** La conexión se abre con `readonly=True` y el SQL libre pasa
   por `src/seguridad_sql.py`, que bloquea escrituras, DDL, `EXEC`, `xp_cmdshell`,
   `BACKUP`, `GRANT` y sentencias múltiples peligrosas.
2. **Nunca escribas credenciales en el repositorio.** La cadena de conexión vive
   solo en `.env.local`, que está en `.gitignore`. No la imprimas en logs,
   mensajes ni informes, ni la pases por línea de comandos.
3. **Nunca concatenes valores en SQL.** Los valores van parametrizados (`?`). Lo
   único que se interpola son nombres de tabla/columna, validados antes con
   `src/config.py` y `src/queries.py`.
4. **El alcance por usuario se aplica en el SQL**, siempre con `AND`, y solo desde
   `src/scope.py`. Jamás filtres un DataFrame ya cargado para decidir qué ve un
   usuario: eso produce fugas de datos.
5. No añadas dependencias sin justificarlo ni cambies el modo de la conexión.

## Arquitectura (dónde tocar cada cosa)

| Ruta | Responsabilidad |
|---|---|
| `app.py` | Panel Streamlit (4 pestañas). **No construye SQL.** |
| `informe_mensual.py` | Informe ejecutivo por consola + Excel (apto para tarea programada). |
| `servidor_mcp.py` | Servidor MCP por stdio con las herramientas de informes. |
| `src/config.py` | Lectura de `.env.local` y validación de nombres de objeto. |
| `src/db.py` | Conexión pyodbc solo lectura; `consultar` y `consultar_limitado`. |
| `src/modelo.py` | **Único archivo a tocar si cambia la tabla** (mapeo lógico → columnas). |
| `src/queries.py` | Todo el SQL, parametrizado, con alcance inyectado. |
| `src/scope.py` | Quién ve qué filas. Único lugar que decide el alcance. |
| `src/seguridad_sql.py` | Guardas de solo lectura para SQL libre. |
| `src/informe.py` | Cálculos del informe (funciones puras, sin Streamlit ni SQL). |
| `src/demo.py` | Datos sintéticos para desarrollar sin base de datos. |
| `sql/rls_plantilla.sql` | Plantilla de seguridad a nivel de fila (RLS) para multiusuario. |
| `verificar.py`, `verificar_mcp.py` | Pruebas. **Ejecútalas antes de dar algo por terminado.** |

## Rendimiento (tabla grande)

La tabla tiene millones de filas y varios GB. Reglas:

- El panel pide **agregaciones** (`SUM`, `GROUP BY`, `COUNT_BIG`): kilobytes, no
  millones de filas. El detalle es opcional y está limitado a 200.000 filas.
- Acota siempre por fecha (`VTA_FECHA`). "Todo el histórico" recorre toda la tabla.
- `SET ROWCOUNT` limita filas en SQL libre; no reescribas la consulta del usuario.
- Columnas `nchar` (`VTA_TIENDA`, `VTA_CANAL`) vienen **rellenas con espacios**:
  se comparan y agrupan con `RTRIM(...)`. Si añades una dimensión de este tipo,
  hazlo igual o los filtros no coincidirán.

## Reglas de interpretación del negocio

Aplícalas tal cual; no inventes criterios propios:

- **Margen** = venta − costo. `Margen %` = margen / venta × 100.
- **Umbral de margen bajo**: 15% por defecto, parametrizable (`--umbral`,
  `umbral_margen`). No lo cambies sin que el usuario lo pida.
- **Base baja**: una variación interanual calculada sobre una base mínima (menos
  del 5% del valor actual) **no es crecimiento**. `src/informe.py` marca esas filas
  con `Nota = "base baja"` y las excluye de las conclusiones automáticas. No las
  cites como logro.
- **Devoluciones**: tipo de transacción `Refund`, importes negativos. Reducen venta
  y margen; no son ventas fallidas que se puedan ignorar.
- **Mes en curso**: puede estar incompleto. Comprueba la fecha máxima antes de
  compararlo con meses cerrados. El informe por defecto usa el último mes cerrado.
- Los importes están en la moneda de la base; no asumas USD ni conviertas.

## Cómo añadir un informe nuevo

1. Si necesita SQL nuevo, añádelo a `src/queries.py` (parametrizado, con `_where`).
2. Si necesita cálculos, añádelos a `src/informe.py` como función pura sobre
   DataFrames (así se puede probar sin base de datos).
3. Añade la vista en `app.py` (pestaña) y, si aporta, una herramienta en
   `servidor_mcp.py`.
4. Añade la comprobación correspondiente a `verificar.py`.
5. Ejecuta `verificar.py` y `verificar_mcp.py`.

## Servidor MCP

Herramientas expuestas (todas de solo lectura): `estado_conexion`,
`meses_disponibles`, `informe_ejecutivo`, `tabla_dimension`, `serie_mensual`,
`buscar_articulos` y `ejecutar_consulta` (último recurso, validado).

Los clientes se configuran así:

| Cliente | Archivo | Clave |
|---|---|---|
| Claude Code (proyecto) | `.mcp.json` | `mcpServers` |
| VS Code / Copilot | `.mcp.json` (recomendado) o `.vscode/mcp.json` | `mcpServers` / `servers` |
| Codex CLI | `.codex/config.toml` o `~/.codex/config.toml` | `[mcp_servers.<nombre>]` |
| Cursor | `.cursor/mcp.json` o `~/.cursor/mcp.json` | `mcpServers` |
| Claude Desktop | `claude_desktop_config.json` | `mcpServers` |
| Gemini CLI | `.gemini/settings.json` | `mcpServers` |

El servidor **no recibe credenciales por variables de entorno**: lee `.env.local`
por sí mismo. Si tu cliente no arranca el proceso en la raíz del proyecto, usa
`uv run --directory <ruta-del-proyecto> servidor_mcp.py`.

## Qué NO hacer

- No ejecutes nada que escriba en la base, ni siquiera para "probar".
- No publiques en el repositorio: direcciones de servidores, nombres de bases,
  logins, ni cifras de negocio reales (ventas, márgenes, proveedores, tiendas).
  Los informes y extracciones van a `out/`, que está ignorado por git.
- No subas `.venv/`, `out/`, `data/` ni `.env.local`.
- No cambies el umbral de margen, el periodo por defecto ni el modo de conexión
  como "mejora" sin pedirlo.
