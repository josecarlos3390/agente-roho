"""Cálculos del informe ejecutivo mensual.

Sin Streamlit y sin SQL: funciones puras sobre los DataFrames agregados, para
poder probarlas y reutilizarlas (panel, Excel, Word, PowerPoint).

Convención de columnas de entrada (salida de queries.sql_mensual y
queries.sql_mensual_dimension):
    Mes, [Dimension,] Importe, Costo, Margen, Cantidad, Filas
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

MES = "Mes"
DIM = "Dimension"


def inicio_mes(valor) -> pd.Timestamp:
    return pd.Timestamp(valor).to_period("M").to_timestamp()


def _normalizar(df: pd.DataFrame) -> pd.DataFrame:
    copia = df.copy()
    copia[MES] = pd.to_datetime(copia[MES]).dt.to_period("M").dt.to_timestamp()
    return copia


def meses_disponibles(mensual: pd.DataFrame) -> list[pd.Timestamp]:
    if mensual is None or mensual.empty:
        return []
    serie = _normalizar(mensual)[MES]
    return sorted(serie.unique())


def mes_completo_por_defecto(mensual: pd.DataFrame, ultima_fecha) -> pd.Timestamp | None:
    """Último mes cerrado: si el último dato es de un mes en curso, devuelve el anterior."""
    meses = meses_disponibles(mensual)
    if not meses:
        return None
    ultimo = meses[-1]
    if ultima_fecha is None:
        return ultimo
    fecha = pd.Timestamp(ultima_fecha)
    fin_de_mes = ultimo + pd.offsets.MonthEnd(0)
    return meses[-2] if fecha.normalize() < fin_de_mes.normalize() else ultimo


def _pct_variacion(actual: float, base: float | None) -> float | None:
    if base in (None, 0) or pd.isna(base):
        return None
    return (actual / base - 1.0) * 100.0


def kpis(mensual: pd.DataFrame, mes) -> dict:
    """KPIs del mes con comparativos (mes anterior, mismo mes del año anterior, acumulado)."""
    if mensual is None or mensual.empty:
        return {}
    serie = _normalizar(mensual).set_index(MES).sort_index()
    serie = serie.groupby(level=0).sum(numeric_only=True)
    mes = inicio_mes(mes)
    if mes not in serie.index:
        return {}

    actual = serie.loc[mes]
    anterior_mes = mes - pd.DateOffset(months=1)
    mismo_mes_ano_anterior = mes - pd.DateOffset(years=1)

    anterior = serie.loc[anterior_mes] if anterior_mes in serie.index else None
    year_ago = serie.loc[mismo_mes_ano_anterior] if mismo_mes_ano_anterior in serie.index else None

    def margen_pct(fila) -> float | None:
        if fila is None or not fila.get("Importe"):
            return None
        return float(fila["Margen"]) / float(fila["Importe"]) * 100.0

    # Acumulado del año (YTD) contra el mismo tramo del año anterior.
    ytd = serie.loc[f"{mes.year}-01-01":mes]
    ytd_prev = serie.loc[
        f"{mes.year - 1}-01-01": (mes - pd.DateOffset(years=1))
    ]

    return {
        "mes": mes,
        "venta": float(actual["Importe"]),
        "costo": float(actual["Costo"]),
        "margen": float(actual["Margen"]),
        "margen_pct": margen_pct(actual),
        "unidades": float(actual["Cantidad"]),
        "lineas": int(actual["Filas"]),
        "venta_mes_anterior": float(anterior["Importe"]) if anterior is not None else None,
        "var_mom": _pct_variacion(float(actual["Importe"]), float(anterior["Importe"])) if anterior is not None else None,
        "venta_ano_anterior": float(year_ago["Importe"]) if year_ago is not None else None,
        "var_yoy": _pct_variacion(float(actual["Importe"]), float(year_ago["Importe"])) if year_ago is not None else None,
        "margen_pct_ano_anterior": margen_pct(year_ago),
        "margen_pp_yoy": (margen_pct(actual) - margen_pct(year_ago))
        if (margen_pct(actual) is not None and margen_pct(year_ago) is not None)
        else None,
        "ytd_venta": float(ytd["Importe"].sum()),
        "ytd_var": _pct_variacion(float(ytd["Importe"].sum()), float(ytd_prev["Importe"].sum()))
        if not ytd_prev.empty
        else None,
        "ticket_medio": float(actual["Importe"]) / float(actual["Filas"]) if actual["Filas"] else None,
    }


def tabla_dimension(
    por_mes_dim: pd.DataFrame,
    mes,
    umbral_margen: float = 15.0,
) -> pd.DataFrame:
    """Tabla comparativa por dimensión para el mes elegido.

    Columnas: Venta, Venta mes ant., Var MoM %, Venta año ant., Var YoY %, Margen,
    Margen %, Margen pp YoY, Part. %, Unidades, Líneas, Alerta.
    """
    if por_mes_dim is None or por_mes_dim.empty:
        return pd.DataFrame()
    datos = _normalizar(por_mes_dim)
    mes = inicio_mes(mes)

    def agrupar(clave) -> pd.DataFrame:
        bloque = datos[datos[MES] == clave]
        if bloque.empty:
            return pd.DataFrame()
        return bloque.groupby(DIM, dropna=False).sum(numeric_only=True)

    actual = agrupar(mes)
    if actual.empty:
        return pd.DataFrame()

    anterior = agrupar(mes - pd.DateOffset(months=1))
    year_ago = agrupar(mes - pd.DateOffset(years=1))

    salida = pd.DataFrame(index=actual.index)
    salida["Venta"] = actual["Importe"]
    salida["Venta mes ant."] = anterior["Importe"].reindex(salida.index) if not anterior.empty else pd.NA
    salida["Var MoM %"] = [
        _pct_variacion(v, b) for v, b in zip(salida["Venta"], salida["Venta mes ant."], strict=False)
    ]
    salida["Venta año ant."] = year_ago["Importe"].reindex(salida.index) if not year_ago.empty else pd.NA
    salida["Var YoY %"] = [
        _pct_variacion(v, b) for v, b in zip(salida["Venta"], salida["Venta año ant."], strict=False)
    ]
    salida["Margen"] = actual["Margen"]
    salida["Margen %"] = (actual["Margen"] / actual["Importe"].replace(0, pd.NA) * 100).round(2)
    if not year_ago.empty:
        margen_previo = (year_ago["Margen"] / year_ago["Importe"].replace(0, pd.NA) * 100).reindex(
            salida.index
        )
        salida["Margen pp YoY"] = (salida["Margen %"] - margen_previo).round(2)
    else:
        salida["Margen pp YoY"] = pd.NA
    salida["Part. %"] = (salida["Venta"] / salida["Venta"].sum() * 100).round(2)
    salida["Unidades"] = actual["Cantidad"]
    salida["Líneas"] = actual["Filas"]
    salida["Alerta"] = [
        "margen bajo" if (m is not None and not pd.isna(m) and m < umbral_margen) else ""
        for m in salida["Margen %"]
    ]
    # Una variación interanual sobre una base diminuta no es información: se marca
    # para que ni la lectura automática ni el lector la interpreten como crecimiento.
    base_previa = pd.to_numeric(salida["Venta año ant."], errors="coerce")
    salida["Nota"] = [
        "base baja" if (pd.isna(b) or b < 0.05 * abs(v)) else ""
        for v, b in zip(salida["Venta"], base_previa, strict=False)
    ]
    return salida.sort_values("Venta", ascending=False).reset_index().rename(columns={DIM: "Dimensión"})


def lectura(
    datos_kpis: dict,
    tablas: dict[str, pd.DataFrame],
    umbral_margen: float = 15.0,
) -> list[str]:
    """Conclusiones automáticas del mes, con reglas explícitas (no interpretación libre)."""
    if not datos_kpis:
        return ["Sin datos para el mes seleccionado."]

    mes = datos_kpis["mes"]
    nombre_mes = f"{mes:%m/%Y}"
    frases: list[str] = []

    def miles(valor: float | None) -> str:
        return f"{valor:,.0f}" if valor is not None and not pd.isna(valor) else "s/d"

    def signo(valor: float | None, sufijo: str = "%") -> str:
        if valor is None or pd.isna(valor):
            return "s/d"
        return f"{valor:+,.1f}{sufijo}"

    frases.append(
        f"**Venta de {nombre_mes}: {miles(datos_kpis['venta'])}** "
        f"({signo(datos_kpis['var_mom'])} vs mes anterior, {signo(datos_kpis['var_yoy'])} interanual)."
    )

    margen_pct = datos_kpis.get("margen_pct")
    pp = datos_kpis.get("margen_pp_yoy")
    frases.append(
        f"Margen de **{miles(datos_kpis['margen'])}** "
        f"({margen_pct:.1f}% sobre venta)" if margen_pct is not None else
        f"Margen de **{miles(datos_kpis['margen'])}**"
    )
    if pp is not None and not pd.isna(pp):
        direccion = "mejoró" if pp >= 0 else "empeoró"
        frases[-1] += f", que {direccion} **{abs(pp):.1f} puntos** frente al mismo mes del año anterior."

    if datos_kpis.get("ytd_var") is not None and not pd.isna(datos_kpis["ytd_var"]):
        frases.append(
            f"Acumulado del año: **{miles(datos_kpis['ytd_venta'])}** "
            f"({signo(datos_kpis['ytd_var'])} vs el mismo tramo de {mes.year - 1})."
        )

    categorias = tablas.get("Categoría")
    if categorias is not None and not categorias.empty:
        primera = categorias.iloc[0]
        frases.append(
            f"La categoría líder es **{primera['Dimensión']}** con {miles(primera['Venta'])} "
            f"({primera['Part. %']:.1f}% de la venta del mes) y margen {primera['Margen %']:.1f}%."
        )

    tiendas = tablas.get("Tienda")
    if tiendas is not None and not tiendas.empty:
        primera = tiendas.iloc[0]
        frases.append(
            f"**{primera['Dimensión']}** concentra {primera['Part. %']:.1f}% de la venta; "
            f"su margen es {primera['Margen %']:.1f}%."
        )

    for etiqueta, tabla in tablas.items():
        if tabla is None or tabla.empty or "Var YoY %" not in tabla.columns:
            continue
        con_base = tabla.dropna(subset=["Var YoY %"])
        if "Nota" in con_base.columns:
            con_base = con_base[con_base["Nota"] != "base baja"]
        if len(con_base) < 2:
            continue
        mejor = con_base.loc[con_base["Var YoY %"].idxmax()]
        peor = con_base.loc[con_base["Var YoY %"].idxmin()]
        frases.append(
            f"En {etiqueta.lower()}, el mayor crecimiento interanual es **{mejor['Dimensión']}** "
            f"({signo(mejor['Var YoY %'])}) y la mayor caída **{peor['Dimensión']}** "
            f"({signo(peor['Var YoY %'])})."
        )
        break

    if categorias is not None and not categorias.empty:
        bajo = categorias[categorias["Margen %"] < umbral_margen]
        if not bajo.empty:
            detalle = ", ".join(
                f"{fila['Dimensión']} ({fila['Margen %']:.1f}%)" for _, fila in bajo.head(5).iterrows()
            )
            frases.append(
                f"⚠️ **{len(bajo)} categorías por debajo del {umbral_margen:.0f}% de margen**: {detalle}."
            )

    return frases
