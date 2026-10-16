"""Consultas SQL de la aplicación.

Todo el SQL vive aquí, parametrizado, con el predicado de alcance inyectado
desde src/scope.py. Los nombres de tabla/columna se validan antes de
interpolarse; los valores nunca se concatenan.

Nota sobre RTRIM: VTA_TIENDA y VTA_CANAL son nchar(40) y vienen rellenas con
espacios a la derecha. Se recortan tanto al agrupar como al filtrar, para que los
valores mostrados y los filtros coincidan exactamente.
"""

from __future__ import annotations

import re
from datetime import date

from .modelo import Modelo
from .scope import Alcance

_COLUMNA = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


def _col(nombre: str) -> str:
    if not _COLUMNA.match(nombre):
        raise ValueError(f"Nombre de columna inválido: {nombre!r}")
    return f"[{nombre}]"


def _columnas_texto(modelo: Modelo) -> set[str]:
    return {
        modelo.transaccion,
        modelo.tipo,
        modelo.articulo,
        modelo.descripcion,
        modelo.categoria,
        modelo.familia,
        modelo.marca,
        modelo.proveedor,
        modelo.tienda,
        modelo.canal,
    }


def _where(
    alcance: Alcance,
    modelo: Modelo,
    desde: date | None,
    hasta: date | None,
    filtros: dict[str, list[str]] | None = None,
    busqueda: str | None = None,
) -> tuple[list[str], list]:
    condiciones: list[str] = []
    params: list = []

    if desde is not None:
        condiciones.append(f"t.{_col(modelo.fecha)} >= ?")
        params.append(desde)
    if hasta is not None:
        condiciones.append(f"t.{_col(modelo.fecha)} < DATEADD(DAY, 1, ?)")
        params.append(hasta)

    for columna, valores in (filtros or {}).items():
        limpios = [v for v in valores if v not in (None, "")]
        if not limpios:
            continue
        marcadores = ",".join("?" for _ in limpios)
        condiciones.append(f"RTRIM(t.{_col(columna)}) IN ({marcadores})")
        params.extend(limpios)

    if busqueda:
        condiciones.append(
            f"(t.{_col(modelo.descripcion)} LIKE ? OR t.{_col(modelo.transaccion)} LIKE ?)"
        )
        patron = f"%{busqueda.strip()}%"
        params.extend([patron, patron])

    # El alcance del usuario se añade SIEMPRE, con AND, al final.
    fragmento, params_alcance = alcance.predicado("t")
    condiciones.append(f"({fragmento})")
    params.extend(params_alcance)

    return condiciones, params


def sql_detalle(
    alcance: Alcance,
    modelo: Modelo,
    desde: date | None = None,
    hasta: date | None = None,
    filtros: dict[str, list[str]] | None = None,
    busqueda: str | None = None,
    tope: int = 200_000,
) -> tuple[str, list]:
    texto = _columnas_texto(modelo)
    columnas = ", ".join(
        f"RTRIM(t.{_col(c)}) AS {_col(c)}" if c in texto else f"t.{_col(c)} AS {_col(c)}"
        for c in (
            modelo.fecha,
            modelo.transaccion,
            modelo.tienda,
            modelo.canal,
            modelo.categoria,
            modelo.marca,
            modelo.descripcion,
            modelo.cantidad,
            modelo.importe,
            modelo.costo,
            modelo.margen,
        )
    )
    condiciones, params = _where(alcance, modelo, desde, hasta, filtros, busqueda)
    sql = (
        f"SELECT TOP ({int(tope)}) {columnas} "
        f"FROM {modelo.tabla} AS t "
        f"WHERE {' AND '.join(condiciones)} "
        f"ORDER BY t.{_col(modelo.fecha)} DESC"
    )
    return sql, params


def sql_agregado(
    alcance: Alcance,
    modelo: Modelo,
    columna_dim: str,
    desde: date | None = None,
    hasta: date | None = None,
    filtros: dict[str, list[str]] | None = None,
    busqueda: str | None = None,
) -> tuple[str, list]:
    condiciones, params = _where(alcance, modelo, desde, hasta, filtros, busqueda)
    dim = f"RTRIM(t.{_col(columna_dim)})"
    sql = (
        f"SELECT {dim} AS Dimension, "
        f"SUM(t.{_col(modelo.importe)}) AS Importe, "
        f"SUM(t.{_col(modelo.costo)}) AS Costo, "
        f"SUM(t.{_col(modelo.margen)}) AS Margen, "
        f"SUM(t.{_col(modelo.cantidad)}) AS Cantidad, "
        f"COUNT_BIG(*) AS Filas "
        f"FROM {modelo.tabla} AS t "
        f"WHERE {' AND '.join(condiciones)} "
        f"GROUP BY {dim} "
        f"ORDER BY Importe DESC"
    )
    return sql, params


def sql_mensual_dimension(
    alcance: Alcance,
    modelo: Modelo,
    columna_dim: str,
    desde: date | None = None,
    hasta: date | None = None,
    filtros: dict[str, list[str]] | None = None,
    busqueda: str | None = None,
) -> tuple[str, list]:
    """Serie mensual desglosada por una dimensión.

    Una sola pasada al servidor devuelve mes × dimensión, lo que permite calcular
    mes actual, mes anterior y mismo mes del año anterior sin volver a consultar.
    Es la consulta base del informe ejecutivo.
    """
    condiciones, params = _where(alcance, modelo, desde, hasta, filtros, busqueda)
    fecha = f"t.{_col(modelo.fecha)}"
    mes = f"DATEFROMPARTS(YEAR({fecha}), MONTH({fecha}), 1)"
    dim = f"RTRIM(t.{_col(columna_dim)})"
    sql = (
        f"SELECT {mes} AS Mes, {dim} AS Dimension, "
        f"SUM(t.{_col(modelo.importe)}) AS Importe, "
        f"SUM(t.{_col(modelo.costo)}) AS Costo, "
        f"SUM(t.{_col(modelo.margen)}) AS Margen, "
        f"SUM(t.{_col(modelo.cantidad)}) AS Cantidad, "
        f"COUNT_BIG(*) AS Filas "
        f"FROM {modelo.tabla} AS t "
        f"WHERE {' AND '.join(condiciones)} "
        f"GROUP BY {mes}, {dim} "
        f"ORDER BY Mes"
    )
    return sql, params


def sql_fecha_maxima(alcance: Alcance, modelo: Modelo) -> tuple[str, list]:
    condicion, params = alcance.predicado("t")
    sql = f"SELECT MAX(t.{_col(modelo.fecha)}) AS Ultima FROM {modelo.tabla} AS t WHERE {condicion}"
    return sql, params


def sql_mensual(
    alcance: Alcance,
    modelo: Modelo,
    desde: date | None = None,
    hasta: date | None = None,
    filtros: dict[str, list[str]] | None = None,
    busqueda: str | None = None,
) -> tuple[str, list]:
    condiciones, params = _where(alcance, modelo, desde, hasta, filtros, busqueda)
    fecha = f"t.{_col(modelo.fecha)}"
    mes = f"DATEFROMPARTS(YEAR({fecha}), MONTH({fecha}), 1)"
    sql = (
        f"SELECT {mes} AS Mes, "
        f"SUM(t.{_col(modelo.importe)}) AS Importe, "
        f"SUM(t.{_col(modelo.costo)}) AS Costo, "
        f"SUM(t.{_col(modelo.margen)}) AS Margen, "
        f"SUM(t.{_col(modelo.cantidad)}) AS Cantidad, "
        f"COUNT_BIG(*) AS Filas "
        f"FROM {modelo.tabla} AS t "
        f"WHERE {' AND '.join(condiciones)} "
        f"GROUP BY {mes} "
        f"ORDER BY Mes"
    )
    return sql, params
