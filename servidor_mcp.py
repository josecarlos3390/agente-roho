"""Servidor MCP (stdio) con las herramientas de informes de ventas.

Permite que Claude Code, Codex CLI, VS Code/Copilot, Cursor, Claude Desktop o
cualquier cliente compatible con Model Context Protocol consulten los informes sin
ver SQL ni tener acceso directo a la base.

Ejecutar:  .venv\\Scripts\\python.exe servidor_mcp.py

Requiere el SDK de MCP v2 o superior (``MCPServer``, antes llamado ``FastMCP``).

Guardas de seguridad (en capas, no en el prompt):
1. El login de base de datos configurado en .env.local debe tener permisos mínimos.
2. La conexión se abre en modo solo lectura (src/db.py, ``readonly=True``).
3. ``ejecutar_consulta`` valida el SQL con src/seguridad_sql.py antes de enviarlo
   y aplica tope de filas (SET ROWCOUNT) y de tiempo.
4. Todo pasa por src/scope.py: el alcance por usuario se inyecta en el SQL.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Permite arrancar el servidor desde cualquier directorio de trabajo: algunos
# clientes MCP no lanzan el proceso con la raíz del proyecto como cwd.
RAIZ_PROYECTO = Path(__file__).resolve().parent
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

import pandas as pd  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402

from src import config, db, informe  # noqa: E402
from src import modelo as modelo_mod  # noqa: E402
from src import queries  # noqa: E402
from src.seguridad_sql import ConsultaNoPermitida, validar_consulta  # noqa: E402
from src.scope import resolver_alcance  # noqa: E402

INSTRUCCIONES = """
Herramientas de informes de ventas sobre una base SQL Server (solo lectura).

Cómo usarlas:
- Empieza por `estado_conexion` si no sabes qué datos hay, y por
  `meses_disponibles` para elegir un mes válido.
- Para una visión ejecutiva de un mes, usa `informe_ejecutivo`.
- Para profundizar en una dimensión concreta (categoría, tienda, marca, canal,
  familia, proveedor o tipo de transacción), usa `tabla_dimension`.
- `ejecutar_consulta` es el último recurso: úsala solo cuando ninguna otra
  herramienta responda a la pregunta.

Interpretación de los números (importante, no inventes criterios propios):
- El margen de una línea es venta menos costo. "Margen %" = margen / venta * 100.
- Umbral de margen bajo: 15% por defecto (parámetro `umbral_margen`). No lo
  cambies sin que el usuario lo pida.
- Una variación interanual sobre una base diminuta NO es crecimiento: las tablas
  marcan esas filas con "base baja" en la columna Nota. No las cites como logro.
- Las devoluciones vienen como tipo de transacción "Refund" con importes
  negativos: reducen venta y margen.
- El mes en curso puede estar incompleto: comprueba la fecha máxima antes de
  compararlo con meses cerrados.
"""

mcp = MCPServer(
    "agente-roho",
    title="Informes de ventas (solo lectura)",
    version="0.1.0",
    instructions=INSTRUCCIONES,
)


# --------------------------------------------------------------------------
# Utilidades internas
# --------------------------------------------------------------------------


def _contexto():
    ajustes = config.cargar()
    modelo = modelo_mod.por_defecto()
    alcance = resolver_alcance(ajustes.usuario_local)
    return ajustes, modelo, alcance


def _normalizar(texto: str) -> str:
    tabla = str.maketrans("áéíóúüÁÉÍÓÚÜñÑ", "aeiouuAEIOUUnN")
    return texto.translate(tabla).strip().lower()


def _markdown(df: pd.DataFrame, vacio: str = "_(sin datos)_") -> str:
    if df is None or df.empty:
        return vacio
    columnas = [str(c) for c in df.columns]
    lineas = [
        "| " + " | ".join(columnas) + " |",
        "| " + " | ".join("---" for _ in columnas) + " |",
    ]
    for _, fila in df.iterrows():
        celdas = []
        for columna in df.columns:
            valor = fila[columna]
            if valor is None or (isinstance(valor, float) and pd.isna(valor)):
                celdas.append("s/d")
            elif isinstance(valor, float):
                celdas.append(f"{valor:,.2f}")
            else:
                celdas.append(str(valor))
        lineas.append("| " + " | ".join(celdas) + " |")
    return "\n".join(lineas)


def _ventana(meses: int) -> tuple[date, date]:
    fin = date.today()
    inicio = (pd.Timestamp(fin) - pd.DateOffset(months=int(meses))).date()
    return inicio, fin


def _serie(alcance, modelo, meses: int = 36) -> pd.DataFrame:
    inicio, fin = _ventana(meses)
    sql, params = queries.sql_mensual(alcance, modelo, inicio, fin)
    return db.consultar(sql, params)


def _ultima_fecha(alcance, modelo) -> date | None:
    sql, params = queries.sql_fecha_maxima(alcance, modelo)
    df = db.consultar(sql, params)
    return None if df.empty else pd.to_datetime(df["Ultima"].iloc[0]).date()


def _resolver_mes(mensual: pd.DataFrame, alcance, modelo, mes: str | None) -> pd.Timestamp:
    meses = informe.meses_disponibles(mensual)
    if not meses:
        raise ValueError("No hay datos en la ventana analizada.")
    if not mes:
        return informe.mes_completo_por_defecto(mensual, _ultima_fecha(alcance, modelo))
    texto = mes.strip()
    if len(texto) == 7:
        texto += "-01"
    objetivo = informe.inicio_mes(texto)
    if objetivo not in meses:
        raise ValueError(
            f"El mes {mes} no tiene datos. Disponibles: {meses[0]:%Y-%m} a {meses[-1]:%Y-%m}."
        )
    return objetivo


def _tabla_dimension(alcance, modelo, etiqueta: str, mes, umbral: float) -> pd.DataFrame:
    inicio, fin = _ventana(36)
    sql, params = queries.sql_mensual_dimension(
        alcance, modelo, modelo_mod.dimensiones(modelo)[etiqueta], inicio, fin
    )
    por_mes_dim = db.consultar(sql, params)
    return informe.tabla_dimension(por_mes_dim, mes, umbral)


# --------------------------------------------------------------------------
# Herramientas
# --------------------------------------------------------------------------


@mcp.tool()
def estado_conexion() -> str:
    """Comprueba la conexión e indica servidor, base, tabla, alcance del usuario y
    la fecha del último dato disponible. Úsala primero si no sabes qué hay."""
    ajustes, modelo, alcance = _contexto()
    diagnostico = db.probar_conexion()
    if not diagnostico.ok:
        return f"Sin conexión: {diagnostico.detalle}"
    try:
        ultima = _ultima_fecha(alcance, modelo)
    except Exception as exc:  # noqa: BLE001
        ultima = f"no disponible ({type(exc).__name__})"
    return "\n".join(
        [
            f"- Conexión: OK ({diagnostico.detalle})",
            f"- Tabla: {modelo.tabla}",
            f"- Fecha del último dato: {ultima}",
            f"- Alcance aplicado: {alcance.descripcion()}",
            "- Modo: solo lectura",
        ]
    )


@mcp.tool()
def meses_disponibles(meses_atras: int = 36) -> str:
    """Lista los meses con datos (formato AAAA-MM), del más antiguo al más reciente.

    Úsala para elegir un mes válido antes de llamar a informe_ejecutivo o
    tabla_dimension.
    """
    _, modelo, alcance = _contexto()
    mensual = _serie(alcance, modelo, meses_atras)
    meses = informe.meses_disponibles(mensual)
    if not meses:
        return "No hay datos en la ventana analizada."
    return ", ".join(f"{m:%Y-%m}" for m in meses)


@mcp.tool()
def informe_ejecutivo(mes: str | None = None, umbral_margen: float = 15.0) -> str:
    """Informe ejecutivo de un mes: cifras, lectura automática y comparativos.

    Devuelve venta, costo, margen, márgenes porcentuales, variación frente al mes
    anterior y al mismo mes del año anterior, el acumulado del año, conclusiones
    automáticas y tablas por categoría, tienda, marca y tipo de transacción.

    Args:
        mes: mes a informar en formato AAAA-MM. Si se omite, usa el último mes
            cerrado (no el mes en curso, que puede estar incompleto).
        umbral_margen: porcentaje de margen por debajo del cual se marca alerta.
    """
    _, modelo, alcance = _contexto()
    mensual = _serie(alcance, modelo, 36)
    mes_sel = _resolver_mes(mensual, alcance, modelo, mes)

    datos = informe.kpis(mensual, mes_sel)
    if not datos:
        return f"Sin datos para {mes_sel:%Y-%m}."

    tablas = {
        etiqueta: _tabla_dimension(alcance, modelo, etiqueta, mes_sel, umbral_margen)
        for etiqueta in ("Categoría", "Tienda", "Marca", "Tipo de transacción")
    }

    def n(valor, decimales: int = 0) -> str:
        return "s/d" if valor is None or pd.isna(valor) else f"{valor:,.{decimales}f}"

    def v(valor) -> str:
        return "s/d" if valor is None or pd.isna(valor) else f"{valor:+,.1f}%"

    partes = [
        f"# Informe ejecutivo — {mes_sel:%m/%Y}",
        "",
        "## Cifras",
        f"- Venta: {n(datos['venta'])} ({v(datos['var_mom'])} vs mes anterior, {v(datos['var_yoy'])} interanual)",
        f"- Costo: {n(datos['costo'])}",
        f"- Margen: {n(datos['margen'])} ({n(datos['margen_pct'], 1)}% sobre venta)",
        f"- Variación de margen vs año anterior: "
        + ("s/d" if datos["margen_pp_yoy"] is None else f"{datos['margen_pp_yoy']:+.1f} puntos"),
        f"- Unidades: {n(datos['unidades'])} · Líneas: {n(datos['lineas'])} · Importe medio por línea: {n(datos['ticket_medio'])}",
        f"- Acumulado del año: {n(datos['ytd_venta'])} ({v(datos['ytd_var'])} vs el mismo tramo de {mes_sel.year - 1})",
        "",
        "## Lectura del mes",
    ]
    partes += [f"- {frase}" for frase in informe.lectura(datos, tablas, umbral_margen)]

    for etiqueta, tabla in tablas.items():
        partes += ["", f"## {etiqueta}"]
        if tabla is None or tabla.empty:
            partes.append("_(sin datos)_")
            continue
        columnas = [
            "Dimensión", "Venta", "Var MoM %", "Var YoY %", "Margen", "Margen %",
            "Margen pp YoY", "Part. %", "Alerta", "Nota",
        ]
        partes.append(_markdown(tabla[columnas].head(15)))

    return "\n".join(partes)


@mcp.tool()
def tabla_dimension(dimension: str, mes: str | None = None, umbral_margen: float = 15.0) -> str:
    """Tabla comparativa de una dimensión en un mes concreto.

    Args:
        dimension: Categoría, Tienda, Marca, Canal, Familia, Proveedor o
            Tipo de transacción (no distingue mayúsculas ni acentos).
        mes: mes en formato AAAA-MM. Si se omite, el último mes cerrado.
        umbral_margen: umbral de alerta de margen en porcentaje.
    """
    _, modelo, alcance = _contexto()
    disponibles = modelo_mod.dimensiones(modelo)
    mapa = {_normalizar(etiqueta): etiqueta for etiqueta in disponibles}
    clave = _normalizar(dimension)
    if clave not in mapa:
        return f"Dimensión desconocida: {dimension}. Válidas: {', '.join(disponibles)}."
    etiqueta = mapa[clave]

    mensual = _serie(alcance, modelo, 36)
    mes_sel = _resolver_mes(mensual, alcance, modelo, mes)
    tabla = _tabla_dimension(alcance, modelo, etiqueta, mes_sel, umbral_margen)
    if tabla.empty:
        return f"Sin datos de {etiqueta} para {mes_sel:%Y-%m}."
    return f"# {etiqueta} — {mes_sel:%m/%Y}\n\n" + _markdown(tabla)


@mcp.tool()
def serie_mensual(meses: int = 24) -> str:
    """Serie mensual de venta, costo, margen y margen porcentual.

    Úsala para tendencias, estacionalidad o comparaciones entre periodos.

    Args:
        meses: cuántos meses hacia atrás incluir (por defecto 24).
    """
    _, modelo, alcance = _contexto()
    mensual = _serie(alcance, modelo, meses).copy()
    if mensual.empty:
        return "No hay datos en la ventana analizada."
    mensual["Mes"] = pd.to_datetime(mensual["Mes"]).dt.strftime("%Y-%m")
    mensual["Margen %"] = (
        mensual["Margen"] / mensual["Importe"].replace(0, pd.NA) * 100
    ).round(2)
    columnas = ["Mes", "Importe", "Costo", "Margen", "Margen %", "Cantidad", "Filas"]
    return _markdown(mensual[columnas])


@mcp.tool()
def buscar_articulos(texto: str, meses: int = 12, limite: int = 20) -> str:
    """Busca artículos por texto en la descripción y los agrega por artículo.

    Devuelve venta, unidades y margen de cada artículo que coincida, ordenado por
    venta descendente. Útil para saber cómo va un producto concreto.

    Args:
        texto: fragmento a buscar en la descripción del artículo.
        meses: ventana temporal hacia atrás (por defecto 12).
        limite: número máximo de artículos a devolver.
    """
    _, modelo, alcance = _contexto()
    inicio, fin = _ventana(meses)
    condiciones, params = queries._where(alcance, modelo, inicio, fin, None, texto)
    sql = (
        f"SELECT TOP ({int(limite)}) "
        f"RTRIM(t.[{modelo.articulo}]) AS Articulo, "
        f"MAX(t.[{modelo.descripcion}]) AS Descripcion, "
        f"SUM(t.[{modelo.cantidad}]) AS Unidades, "
        f"SUM(t.[{modelo.importe}]) AS Venta, "
        f"SUM(t.[{modelo.margen}]) AS Margen "
        f"FROM {modelo.tabla} AS t "
        f"WHERE {' AND '.join(condiciones)} "
        f"GROUP BY RTRIM(t.[{modelo.articulo}]) "
        f"ORDER BY Venta DESC"
    )
    datos = db.consultar(sql, params)
    if datos.empty:
        return f"Sin artículos que coincidan con {texto!r} en los últimos {meses} meses."
    return f"# Artículos que coinciden con {texto!r}\n\n" + _markdown(datos)


@mcp.tool()
def ejecutar_consulta(sql: str, max_filas: int = 200) -> str:
    """Ejecuta una consulta SQL de solo lectura y devuelve el resultado en markdown.

    Último recurso: solo cuando ninguna otra herramienta responde a la pregunta.
    La consulta debe empezar por SELECT, WITH o DECLARE. Se bloquean escrituras,
    DDL, procedimientos del sistema sensibles y ejecución dinámica.

    Args:
        sql: consulta T-SQL de solo lectura.
        max_filas: tope de filas devueltas (SET ROWCOUNT).
    """
    _, _, alcance = _contexto()
    try:
        consulta = validar_consulta(sql)
    except ConsultaNoPermitida as exc:
        return f"Consulta rechazada: {exc}"

    # El alcance del usuario también aplica al SQL libre: si está restringido, no
    # se permite evadir el filtro con una consulta propia.
    if not alcance.es_total:
        return (
            "Consulta rechazada: tu alcance sobre los datos está restringido, así que "
            "no se permite SQL libre. Usa las herramientas de informes."
        )

    try:
        datos = db.consultar_limitado(consulta, limite_filas=max_filas)
    except Exception as exc:  # noqa: BLE001
        return f"Error ejecutando la consulta: {type(exc).__name__}: {exc}"

    aviso = ""
    if len(datos) >= max_filas:
        aviso = f"\n\n_Aviso: se alcanzó el tope de {max_filas} filas; el resultado puede estar truncado._"
    return _markdown(datos) + aviso


if __name__ == "__main__":
    mcp.run()
