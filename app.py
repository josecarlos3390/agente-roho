"""Panel de informes de ventas sobre SQL Server (Streamlit).

Ejecutar:  .venv\\Scripts\\python.exe -m streamlit run app.py

Pestañas:
  1. Informe ejecutivo mensual (mes seleccionable, comparativos MoM/YoY, lectura automática)
  2. Panorama (periodo libre de la barra lateral)
  3. Detalle (opcional, hasta 200.000 filas)
  4. Calidad de datos

Principios:
- KPIs y gráficos se calculan con AGREGACIONES en el servidor: se transfieren
  kilobytes, no millones de filas.
- Los filtros y el alcance por usuario viajan al SQL como parámetros; nunca se
  filtra un DataFrame ya cargado.
"""

from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import config, db, demo, informe
from src import modelo as modelo_mod
from src import queries
from src.scope import resolver_alcance

st.set_page_config(page_title="Informes de ventas", page_icon="📈", layout="wide")

ajustes = config.cargar()
modelo = modelo_mod.por_defecto()
alcance = resolver_alcance(ajustes.usuario_local)
dimensiones = modelo_mod.dimensiones(modelo)
modo_demo = (not ajustes.hay_conexion) or st.session_state.get("forzar_demo", False)

PERIODOS = {
    "Últimos 3 meses": 3,
    "Últimos 12 meses": 12,
    "Últimos 24 meses": 24,
    "Año en curso": None,
    "Todo el histórico": 0,
    "Personalizado": -1,
}
MESES_EJECUTIVO = 36
DIMENSIONES_INFORME = ("Categoría", "Tienda", "Marca", "Tipo de transacción")


# --------------------------------------------------------------------------
# Acceso a datos
# --------------------------------------------------------------------------


@st.cache_data(ttl=600, show_spinner=False)
def _demo() -> pd.DataFrame:
    return demo.generar()


@st.cache_data(ttl=300, show_spinner=False)
def _sql(sql: str, params: tuple) -> pd.DataFrame:
    return db.consultar(sql, list(params))


def _demo_filtrado(filtros, busqueda, desde: date | None, hasta: date | None) -> pd.DataFrame:
    df = _demo()
    if desde is not None and hasta is not None:
        df = df[(df[modelo.fecha].dt.date >= desde) & (df[modelo.fecha].dt.date <= hasta)]
    df = df.copy()
    for columna, valores in filtros.items():
        df = df[df[columna].isin(valores)]
    if busqueda:
        mascara = df[modelo.descripcion].astype(str).str.contains(
            busqueda, case=False, na=False
        ) | df[modelo.transaccion].astype(str).str.contains(busqueda, case=False, na=False)
        df = df[mascara]
    return df


def _agregar_mes(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(pd.Grouper(key=modelo.fecha, freq="MS"))
        .agg(
            Importe=(modelo.importe, "sum"),
            Costo=(modelo.costo, "sum"),
            Margen=(modelo.margen, "sum"),
            Cantidad=(modelo.cantidad, "sum"),
            Filas=(modelo.transaccion, "count"),
        )
        .reset_index()
        .rename(columns={modelo.fecha: "Mes"})
    )


def _agregar_mes_dim(df: pd.DataFrame, columna: str) -> pd.DataFrame:
    temporal = df.copy()
    temporal["Mes"] = pd.to_datetime(temporal[modelo.fecha]).dt.to_period("M").dt.to_timestamp()
    temporal["Dimension"] = temporal[columna].astype(str).str.strip()
    return (
        temporal.groupby(["Mes", "Dimension"], dropna=False)
        .agg(
            Importe=(modelo.importe, "sum"),
            Costo=(modelo.costo, "sum"),
            Margen=(modelo.margen, "sum"),
            Cantidad=(modelo.cantidad, "sum"),
            Filas=(modelo.transaccion, "count"),
        )
        .reset_index()
    )


def _filtros_efectivos(seleccion: dict[str, list[str]]) -> dict[str, list[str]]:
    return {dimensiones[e]: v for e, v in seleccion.items() if v}


@st.cache_data(ttl=1800, show_spinner=False)
def ultima_fecha() -> date | None:
    if modo_demo:
        return _demo()[modelo.fecha].max().date()
    sql, params = queries.sql_fecha_maxima(alcance, modelo)
    df = _sql(sql, tuple(params))
    return None if df.empty else pd.to_datetime(df["Ultima"].iloc[0]).date()


@st.cache_data(ttl=300, show_spinner=False)
def cargar_ejecutivo(filtros_clave: tuple, busqueda: str) -> tuple[pd.DataFrame, dict]:
    """Serie mensual y desgloses mes × dimensión para el informe ejecutivo."""
    filtros = {clave: list(valores) for clave, valores in filtros_clave}
    inicio = (pd.Timestamp(date.today()) - pd.DateOffset(months=MESES_EJECUTIVO)).date()
    fin = date.today()

    if modo_demo:
        df = _demo_filtrado(filtros, busqueda, inicio, fin)
        return _agregar_mes(df), {
            etiqueta: _agregar_mes_dim(df, dimensiones[etiqueta]) for etiqueta in DIMENSIONES_INFORME
        }

    sql, params = queries.sql_mensual(alcance, modelo, inicio, fin, filtros, busqueda or None)
    mensual = _sql(sql, tuple(params))
    tablas = {}
    for etiqueta in DIMENSIONES_INFORME:
        sql_dim, p_dim = queries.sql_mensual_dimension(
            alcance, modelo, dimensiones[etiqueta], inicio, fin, filtros, busqueda or None
        )
        tablas[etiqueta] = _sql(sql_dim, tuple(p_dim))
    return mensual, tablas


@st.cache_data(ttl=300, show_spinner=False)
def cargar_panorama(filtros_clave: tuple, busqueda: str, desde: date, hasta: date):
    filtros = {clave: list(valores) for clave, valores in filtros_clave}
    if modo_demo:
        df = _demo_filtrado(filtros, busqueda, desde, hasta)
        agregados = {
            etiqueta: df.groupby(columna, dropna=False)
            .agg(
                Importe=(modelo.importe, "sum"),
                Costo=(modelo.costo, "sum"),
                Margen=(modelo.margen, "sum"),
                Cantidad=(modelo.cantidad, "sum"),
                Filas=(modelo.transaccion, "count"),
            )
            .reset_index()
            .rename(columns={columna: "Dimension"})
            .assign(Dimension=lambda d: d["Dimension"].astype(str).str.strip())
            .sort_values("Importe", ascending=False)
            for etiqueta, columna in dimensiones.items()
        }
        return _agregar_mes(df), agregados

    sql, params = queries.sql_mensual(alcance, modelo, desde, hasta, filtros, busqueda or None)
    mensual = _sql(sql, tuple(params))
    agregados = {}
    for etiqueta, columna in dimensiones.items():
        sql_dim, p_dim = queries.sql_agregado(
            alcance, modelo, columna, desde, hasta, filtros, busqueda or None
        )
        agregados[etiqueta] = _sql(sql_dim, tuple(p_dim))
    return mensual, agregados


@st.cache_data(ttl=300, show_spinner=False)
def cargar_detalle(filtros_clave: tuple, busqueda: str, desde: date, hasta: date) -> pd.DataFrame:
    filtros = {clave: list(valores) for clave, valores in filtros_clave}
    if modo_demo:
        return _demo_filtrado(filtros, busqueda, desde, hasta)
    sql, params = queries.sql_detalle(alcance, modelo, desde, hasta, filtros, busqueda or None)
    return _sql(sql, tuple(params))


@st.cache_data(ttl=1800, show_spinner=False)
def opciones_filtro() -> dict[str, list[str]]:
    if modo_demo:
        base = _demo()
        return {
            etiqueta: sorted(base[columna].dropna().astype(str).str.strip().unique().tolist())
            for etiqueta, columna in dimensiones.items()
        }
    opciones = {}
    for etiqueta, columna in dimensiones.items():
        sql, params = queries.sql_agregado(alcance, modelo, columna)
        df = _sql(sql, tuple(params))
        opciones[etiqueta] = sorted(str(v).strip() for v in df["Dimension"].dropna().tolist())
    return opciones


def a_excel(hojas: dict[str, pd.DataFrame]) -> bytes | None:
    try:
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as escritor:
            for nombre, tabla in hojas.items():
                tabla.to_excel(escritor, index=False, sheet_name=nombre[:31])
        return buffer.getvalue()
    except Exception:
        return None


# --------------------------------------------------------------------------
# Barra lateral
# --------------------------------------------------------------------------

with st.sidebar:
    st.title("📈 Informes de ventas")

    if ajustes.hay_conexion:
        st.success("Modo: **SQL Server**")
        if st.button("Probar conexión", width="stretch"):
            with st.spinner("Conectando…"):
                diagnostico = db.probar_conexion()
            (st.success if diagnostico.ok else st.error)(diagnostico.detalle)
    else:
        st.warning("Modo: **datos de ejemplo**\n\nNo hay `.env.local` con `MSSQL_CONNSTRING`.")

    st.caption(f"Alcance: {alcance.descripcion()}")

    st.divider()
    st.subheader("Filtros")
    st.caption("Aplican al informe ejecutivo y al panorama.")
    busqueda = st.text_input("Buscar descripción o transacción", value="").strip()

    try:
        disponibles = opciones_filtro()
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudieron leer las dimensiones: {exc}")
        disponibles = {etiqueta: [] for etiqueta in dimensiones}

    seleccion: dict[str, list[str]] = {}
    for etiqueta in dimensiones:
        seleccion[etiqueta] = st.multiselect(etiqueta, options=disponibles.get(etiqueta, []))

    st.divider()
    st.subheader("Periodo del panorama")
    periodo = st.selectbox("Rango", list(PERIODOS), index=1)

    hoy = date.today()
    if periodo == "Personalizado":
        rango = st.date_input("Fechas", value=(hoy - timedelta(days=365), hoy), format="DD/MM/YYYY")
        if isinstance(rango, (tuple, list)):
            desde, hasta = rango[0], (rango[1] if len(rango) > 1 else rango[0])
        else:
            desde = hasta = rango
    elif periodo == "Año en curso":
        desde, hasta = date(hoy.year, 1, 1), hoy
    elif periodo == "Todo el histórico":
        desde, hasta = date(2018, 1, 1), hoy
        st.caption("⚠️ Todo el histórico recorre los 9,8 GB de la tabla.")
    else:
        meses = PERIODOS[periodo]
        desde, hasta = hoy - timedelta(days=30 * meses), hoy

    st.caption(f"Panorama: {desde:%d/%m/%Y} → {hasta:%d/%m/%Y}")

    con_detalle = st.checkbox(
        "Cargar tabla de detalle",
        value=modo_demo,
        help="En la tabla real son hasta 200.000 filas: es la consulta más pesada del panel.",
    )
    if st.button("Refrescar datos", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    st.caption(f"Tabla: `{modelo.tabla}`")

filtros = _filtros_efectivos(seleccion)
filtros_clave = tuple((clave, tuple(valores)) for clave, valores in filtros.items())

# --------------------------------------------------------------------------
# Cuerpo
# --------------------------------------------------------------------------

st.title("Informe de ventas")

tab_informe, tab_panorama, tab_detalle, tab_calidad = st.tabs(
    ["Informe ejecutivo", "Panorama", "Detalle", "Calidad de datos"]
)

# ----- 1. Informe ejecutivo -------------------------------------------------
with tab_informe:
    try:
        with st.spinner("Calculando el informe…"):
            mensual_ej, tablas_ej = cargar_ejecutivo(filtros_clave, busqueda or "")
            fecha_max = ultima_fecha()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Error consultando la base: {type(exc).__name__}: {exc}")
        st.stop()

    meses = informe.meses_disponibles(mensual_ej)
    if not meses:
        st.warning("No hay datos con los filtros seleccionados.")
    else:
        por_defecto = informe.mes_completo_por_defecto(mensual_ej, fecha_max)
        etiquetas = [f"{m:%m/%Y}" for m in meses]
        elegido = st.selectbox(
            "Mes del informe", etiquetas, index=etiquetas.index(f"{por_defecto:%m/%Y}")
        )
        mes_sel = meses[etiquetas.index(elegido)]

        if fecha_max and informe.inicio_mes(fecha_max) == mes_sel and fecha_max < (
            mes_sel + pd.offsets.MonthEnd(0)
        ).date():
            st.info(f"Mes en curso: datos hasta el {fecha_max:%d/%m/%Y}.")

        datos = informe.kpis(mensual_ej, mes_sel)
        if not datos:
            st.warning("Sin datos para ese mes.")
        else:
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric(
                "Venta",
                f"{datos['venta']:,.0f}",
                delta=None
                if datos["var_mom"] is None
                else f"{datos['var_mom']:+,.1f}% vs mes ant.",
            )
            c2.metric(
                "Interanual",
                f"{datos['var_yoy']:+,.1f}%" if datos["var_yoy"] is not None else "s/d",
                delta=f"vs {mes_sel - pd.DateOffset(years=1):%m/%Y}",
                delta_color="off",
            )
            c3.metric("Margen", f"{datos['margen']:,.0f}")
            c4.metric(
                "Margen %",
                f"{datos['margen_pct']:.1f}%" if datos["margen_pct"] is not None else "s/d",
                delta=None
                if datos["margen_pp_yoy"] is None
                else f"{datos['margen_pp_yoy']:+.1f} pp vs año ant.",
            )
            c5.metric(
                "Importe medio/línea",
                f"{datos['ticket_medio']:,.0f}" if datos["ticket_medio"] else "s/d",
            )

            tablas_mes = {
                etiqueta: informe.tabla_dimension(tabla, mes_sel)
                for etiqueta, tabla in tablas_ej.items()
            }

            st.subheader("Lectura del mes")
            for frase in informe.lectura(datos, tablas_mes):
                st.markdown(f"- {frase}")

            serie = mensual_ej.copy()
            serie["Mes"] = pd.to_datetime(serie["Mes"])
            serie["Margen %"] = (serie["Margen"] / serie["Importe"].replace(0, pd.NA) * 100).round(2)
            figura = go.Figure()
            figura.add_bar(x=serie["Mes"], y=serie["Importe"], name="Venta")
            figura.add_scatter(
                x=serie["Mes"],
                y=serie["Margen %"],
                name="Margen %",
                mode="lines+markers",
                yaxis="y2",
            )
            figura.update_layout(
                title=f"Venta y margen, últimos {MESES_EJECUTIVO} meses",
                yaxis=dict(title="Venta"),
                yaxis2=dict(title="Margen %", overlaying="y", side="right", ticksuffix="%"),
                margin=dict(l=10, r=10, t=50, b=10),
                legend=dict(orientation="h"),
            )
            st.plotly_chart(figura)

            categorias = tablas_mes.get("Categoría")
            if categorias is not None and not categorias.empty:
                comparativo = categorias.head(10)[["Dimensión", "Venta", "Venta año ant."]].melt(
                    "Dimensión", var_name="Serie", value_name="Importe"
                )
                figura = px.bar(
                    comparativo,
                    x="Dimensión",
                    y="Importe",
                    color="Serie",
                    barmode="group",
                    title="Top categorías: mes actual vs mismo mes del año anterior",
                )
                figura.update_layout(margin=dict(l=10, r=10, t=50, b=10), xaxis_title="")
                st.plotly_chart(figura)

            config_columnas = {
                "Venta": st.column_config.NumberColumn(format="%.0f"),
                "Venta mes ant.": st.column_config.NumberColumn(format="%.0f"),
                "Venta año ant.": st.column_config.NumberColumn(format="%.0f"),
                "Var MoM %": st.column_config.NumberColumn(format="%+.1f%%"),
                "Var YoY %": st.column_config.NumberColumn(format="%+.1f%%"),
                "Margen": st.column_config.NumberColumn(format="%.0f"),
                "Margen %": st.column_config.NumberColumn(format="%.1f%%"),
                "Margen pp YoY": st.column_config.NumberColumn(format="%+.1f"),
                "Part. %": st.column_config.NumberColumn(format="%.1f%%"),
                "Unidades": st.column_config.NumberColumn(format="%.0f"),
                "Líneas": st.column_config.NumberColumn(format="%d"),
            }

            for etiqueta, tabla in tablas_mes.items():
                with st.expander(f"{etiqueta} — {elegido}", expanded=(etiqueta == "Categoría")):
                    if tabla.empty:
                        st.caption("Sin datos.")
                    else:
                        st.dataframe(
                            tabla, width="stretch", column_config=config_columnas, hide_index=True
                        )

            hojas = {"Resumen": pd.DataFrame(datos.items(), columns=["Métrica", "Valor"])}
            for etiqueta, tabla in tablas_mes.items():
                hojas[etiqueta] = tabla
            hojas["Serie mensual"] = serie
            contenido = a_excel(hojas)
            if contenido:
                st.download_button(
                    f"Descargar informe {elegido} (Excel)",
                    data=contenido,
                    file_name=f"informe_ejecutivo_{mes_sel:%Y_%m}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                )

# ----- 2. Panorama ---------------------------------------------------------
with tab_panorama:
    try:
        with st.spinner("Agregando en el servidor…"):
            mensual, agregados = cargar_panorama(filtros_clave, busqueda or "", desde, hasta)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Error consultando la base: {type(exc).__name__}: {exc}")
        st.stop()

    if mensual.empty:
        st.warning("No hay datos con los filtros seleccionados.")
    else:
        venta = float(mensual["Importe"].sum())
        margen = float(mensual["Margen"].sum())
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Venta", f"{venta:,.0f}")
        c2.metric("Margen", f"{margen:,.0f}")
        c3.metric("Margen %", f"{(margen / venta * 100):.1f}%" if venta else "—")
        c4.metric("Unidades", f"{float(mensual['Cantidad'].sum()):,.0f}")

        serie = mensual.copy()
        serie["Mes"] = pd.to_datetime(serie["Mes"])
        figura = px.line(serie, x="Mes", y=["Importe", "Margen"], markers=True,
                         title="Evolución mensual: venta y margen")
        figura.update_layout(margin=dict(l=10, r=10, t=50, b=10), legend_title_text="")
        st.plotly_chart(figura)

        izquierda, derecha = st.columns(2)
        with izquierda:
            df_cat = agregados.get("Categoría")
            if df_cat is not None and not df_cat.empty:
                figura = px.bar(df_cat.head(20), x="Dimension", y="Importe",
                                title="Venta por categoría", text_auto=".2s")
                figura.update_layout(margin=dict(l=10, r=10, t=50, b=10), xaxis_title="")
                st.plotly_chart(figura)
        with derecha:
            df_tienda = agregados.get("Tienda")
            if df_tienda is not None and not df_tienda.empty:
                figura = px.pie(df_tienda, names="Dimension", values="Importe",
                                title="Reparto por tienda", hole=0.45)
                figura.update_layout(margin=dict(l=10, r=10, t=50, b=10))
                st.plotly_chart(figura)

        izquierda, derecha = st.columns(2)
        with izquierda:
            df_marca = agregados.get("Marca")
            if df_marca is not None and not df_marca.empty:
                figura = px.bar(df_marca.head(15).sort_values("Importe"), x="Importe",
                                y="Dimension", orientation="h", title="Venta por marca")
                figura.update_layout(margin=dict(l=10, r=10, t=50, b=10), yaxis_title="")
                st.plotly_chart(figura)
        with derecha:
            df_canal = agregados.get("Canal")
            if df_canal is not None and not df_canal.empty:
                figura = px.bar(df_canal.head(15), x="Dimension", y=["Importe", "Margen"],
                                barmode="group", title="Venta y margen por canal")
                figura.update_layout(margin=dict(l=10, r=10, t=50, b=10), xaxis_title="")
                st.plotly_chart(figura)

        with st.expander("Agregados completos por dimensión"):
            for etiqueta, tabla in agregados.items():
                st.caption(etiqueta)
                st.dataframe(tabla, width="stretch")

# ----- 3. Detalle ----------------------------------------------------------
with tab_detalle:
    if not con_detalle:
        st.info(
            "Activa **Cargar tabla de detalle** en la barra lateral para ver las filas. "
            "En esta tabla son hasta 200.000 filas y es la consulta más pesada."
        )
    else:
        with st.spinner("Trayendo el detalle…"):
            try:
                detalle = cargar_detalle(filtros_clave, busqueda or "", desde, hasta)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Error trayendo el detalle: {type(exc).__name__}: {exc}")
                detalle = pd.DataFrame()
        if detalle.empty:
            st.warning("Sin filas de detalle con los filtros actuales.")
        else:
            st.caption(f"{len(detalle):,} filas (máximo 200.000) · ordenado por fecha descendente")
            st.dataframe(detalle, height=520)
            izquierda, derecha = st.columns(2)
            with izquierda:
                st.download_button(
                    "Descargar CSV",
                    data=detalle.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"detalle_{desde:%Y%m%d}_{hasta:%Y%m%d}.csv",
                    mime="text/csv",
                    width="stretch",
                )
            with derecha:
                contenido = a_excel({"Detalle": detalle})
                if contenido:
                    st.download_button(
                        "Descargar Excel",
                        data=contenido,
                        file_name=f"detalle_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        width="stretch",
                    )

# ----- 4. Calidad de datos -------------------------------------------------
with tab_calidad:
    try:
        mensual_q, agregados_q = cargar_panorama(filtros_clave, busqueda or "", desde, hasta)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Error consultando la base: {type(exc).__name__}: {exc}")
        st.stop()

    if not mensual_q.empty:
        venta_q = float(mensual_q["Importe"].sum())
        margen_q = float(mensual_q["Margen"].sum())
        resumen = {
            "Líneas": f"{int(mensual_q['Filas'].sum()):,}",
            "Meses con datos": f"{len(mensual_q):,}",
            "Venta": f"{venta_q:,.2f}",
            "Margen": f"{margen_q:,.2f}",
            "Margen %": f"{(margen_q / venta_q * 100):.2f}%" if venta_q else "—",
        }
        st.dataframe(pd.DataFrame(resumen.items(), columns=["Métrica", "Valor"]), width="stretch")

        canal = agregados_q.get("Canal")
        if canal is not None and not canal.empty:
            st.subheader("Reparto por canal")
            st.dataframe(canal, width="stretch")

        tipo = agregados_q.get("Tipo de transacción")
        if tipo is not None and not tipo.empty:
            st.subheader("Tipos de transacción (devoluciones)")
            st.dataframe(tipo, width="stretch")

    if con_detalle:
        st.subheader("Valores nulos en el detalle")
        with st.spinner("Analizando el detalle…"):
            detalle_q = cargar_detalle(filtros_clave, busqueda or "", desde, hasta)
        if not detalle_q.empty:
            nulos = detalle_q.isna().sum().rename("Nulos").to_frame()
            nulos["% del total"] = (nulos["Nulos"] / len(detalle_q) * 100).round(2)
            st.dataframe(
                nulos[nulos["Nulos"] > 0] if (nulos["Nulos"] > 0).any() else nulos, width="stretch"
            )
            st.caption(f"Transacciones distintas: {detalle_q[modelo.transaccion].nunique():,}")

st.divider()
st.caption(
    f"Alcance: {alcance.descripcion()} · Fuente: {modelo.tabla} · "
    "KPIs y gráficos calculados con agregaciones en el servidor."
)
