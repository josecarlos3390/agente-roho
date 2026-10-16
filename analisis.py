"""Analisis exploratorio de la tabla de ventas configurada en .env.local.

Cada agregacion es un escaneo completo de la tabla, por eso el script mide el
tiempo de la primera consulta y, en modo --auto, solo continua si el servidor
responde rapido. Si no, recomienda extraer una instantanea local.

Uso:
    .venv\\Scripts\\python.exe analisis.py --auto
    .venv\\Scripts\\python.exe analisis.py --todo --limite-segundos 300
    .venv\\Scripts\\python.exe analisis.py --indices
"""

from __future__ import annotations

import argparse
import sys
import time

import pandas as pd

from src import config, db

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)

# Tabla a analizar: se toma de MSSQL_TABLE (.env.local), nunca incrustada.
TABLA = config.cargar().validar_tabla()


def titulo(texto: str) -> None:
    print("\n" + "=" * 90)
    print(texto)
    print("=" * 90)


def ejecutar(texto: str, sql: str) -> tuple[pd.DataFrame, float]:
    inicio = time.perf_counter()
    df = db.consultar(sql)
    segundos = time.perf_counter() - inicio
    print(f"\n--- {texto}  [{segundos:.1f}s, {len(df):,} filas] ---")
    print(df.to_string(index=False))
    return df, segundos


def indices() -> None:
    titulo("INDICES DE " + TABLA)
    df = db.consultar(
        """
        SELECT i.name AS Indice, i.type_desc AS Tipo,
               CASE WHEN i.is_primary_key = 1 THEN 'SI' ELSE '' END AS PK,
               CASE WHEN i.is_unique = 1 THEN 'SI' ELSE '' END AS Unico,
               STUFF((
                   SELECT ', ' + c.name + CASE WHEN ic.is_descending_key = 1 THEN ' DESC' ELSE '' END
                   FROM sys.index_columns AS ic
                   JOIN sys.columns AS c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                   WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id AND ic.is_included_column = 0
                   ORDER BY ic.key_ordinal
                   FOR XML PATH('')
               ), 1, 2, '') AS ColumnasClave
        FROM sys.indexes AS i
        WHERE i.object_id = OBJECT_ID(?) AND i.type > 0
        ORDER BY i.index_id
        """,
        (TABLA,),
    )
    print(df.to_string(index=False))


def totales() -> tuple[pd.DataFrame, float]:
    return ejecutar(
        "TOTALES GLOBALES (una pasada)",
        f"""
        SELECT COUNT_BIG(*) AS Lineas,
               SUM(VTA_CANTIDAD) AS Unidades,
               SUM(VTA_TOTAL) AS Venta,
               SUM(VTA_COSTOTOTAL) AS Costo,
               SUM(VTA_MARGEN) AS Margen,
               SUM(CASE WHEN VTA_TOTAL < 0 THEN 1 ELSE 0 END) AS LineasNegativas,
               MIN(VTA_FECHA) AS Desde,
               MAX(VTA_FECHA) AS Hasta
        FROM {TABLA}
        """,
    )


def por_anio() -> None:
    ejecutar(
        "VENTA Y MARGEN POR ANIO",
        f"""
        SELECT VTA_ANIO AS Anio, COUNT_BIG(*) AS Lineas,
               SUM(VTA_CANTIDAD) AS Unidades,
               CAST(SUM(VTA_TOTAL) AS DECIMAL(18,2)) AS Venta,
               CAST(SUM(VTA_MARGEN) AS DECIMAL(18,2)) AS Margen,
               CAST(100.0 * SUM(VTA_MARGEN) / NULLIF(SUM(VTA_TOTAL), 0) AS DECIMAL(6,2)) AS MargenPct
        FROM {TABLA}
        GROUP BY VTA_ANIO
        ORDER BY VTA_ANIO
        """,
    )


def por_mes() -> None:
    ejecutar(
        "VENTA POR MES (ultimos 36 meses)",
        f"""
        SELECT DATEFROMPARTS(YEAR(VTA_FECHA), MONTH(VTA_FECHA), 1) AS Mes,
               COUNT_BIG(*) AS Lineas,
               CAST(SUM(VTA_TOTAL) AS DECIMAL(18,2)) AS Venta,
               CAST(SUM(VTA_MARGEN) AS DECIMAL(18,2)) AS Margen
        FROM {TABLA}
        WHERE VTA_FECHA >= DATEADD(MONTH, -36, CAST(GETDATE() AS date))
        GROUP BY DATEFROMPARTS(YEAR(VTA_FECHA), MONTH(VTA_FECHA), 1)
        ORDER BY Mes
        """,
    )


def por_tipo_transaccion() -> None:
    ejecutar(
        "TIPOS DE TRANSACCION",
        f"""
        SELECT TOP 20 VTA_TPTRANSACTION AS Tipo, COUNT_BIG(*) AS Lineas,
               CAST(SUM(VTA_TOTAL) AS DECIMAL(18,2)) AS Venta
        FROM {TABLA}
        GROUP BY VTA_TPTRANSACTION
        ORDER BY Lineas DESC
        """,
    )


def por_categoria() -> None:
    ejecutar(
        "TOP 20 CATEGORIAS (ultimos 12 meses)",
        f"""
        SELECT TOP 20 VTA_CATEGORIA AS Categoria, COUNT_BIG(*) AS Lineas,
               CAST(SUM(VTA_TOTAL) AS DECIMAL(18,2)) AS Venta,
               CAST(SUM(VTA_MARGEN) AS DECIMAL(18,2)) AS Margen,
               CAST(100.0 * SUM(VTA_MARGEN) / NULLIF(SUM(VTA_TOTAL), 0) AS DECIMAL(6,2)) AS MargenPct
        FROM {TABLA}
        WHERE VTA_FECHA >= DATEADD(MONTH, -12, CAST(GETDATE() AS date))
        GROUP BY VTA_CATEGORIA
        ORDER BY Venta DESC
        """,
    )


def por_tienda_canal() -> None:
    ejecutar(
        "TIENDA Y CANAL (ultimos 12 meses)",
        f"""
        SELECT TOP 30 VTA_TIENDA AS Tienda, VTA_CANAL AS Canal, COUNT_BIG(*) AS Lineas,
               CAST(SUM(VTA_TOTAL) AS DECIMAL(18,2)) AS Venta,
               CAST(SUM(VTA_MARGEN) AS DECIMAL(18,2)) AS Margen
        FROM {TABLA}
        WHERE VTA_FECHA >= DATEADD(MONTH, -12, CAST(GETDATE() AS date))
        GROUP BY VTA_TIENDA, VTA_CANAL
        ORDER BY Venta DESC
        """,
    )


def top_articulos() -> None:
    ejecutar(
        "TOP 20 ARTICULOS (ultimos 12 meses)",
        f"""
        SELECT TOP 20 VTA_ARTICULO AS Articulo, MAX(VTA_DESCRIPCION) AS Descripcion,
               SUM(VTA_CANTIDAD) AS Unidades,
               CAST(SUM(VTA_TOTAL) AS DECIMAL(18,2)) AS Venta,
               CAST(SUM(VTA_MARGEN) AS DECIMAL(18,2)) AS Margen
        FROM {TABLA}
        WHERE VTA_FECHA >= DATEADD(MONTH, -12, CAST(GETDATE() AS date))
        GROUP BY VTA_ARTICULO
        ORDER BY Venta DESC
        """,
    )


def por_proveedor() -> None:
    ejecutar(
        "TOP 15 PROVEEDORES (ultimos 12 meses)",
        f"""
        SELECT TOP 15 VTA_CODPROV AS Codigo, MAX(VTA_NMBPROV) AS Proveedor,
               CAST(SUM(VTA_TOTAL) AS DECIMAL(18,2)) AS Venta,
               CAST(SUM(VTA_MARGEN) AS DECIMAL(18,2)) AS Margen
        FROM {TABLA}
        WHERE VTA_FECHA >= DATEADD(MONTH, -12, CAST(GETDATE() AS date))
        GROUP BY VTA_CODPROV
        ORDER BY Venta DESC
        """,
    )


def por_marca_familia() -> None:
    ejecutar(
        "TOP 15 MARCAS (ultimos 12 meses)",
        f"""
        SELECT TOP 15 ISNULL(VTA_MARCA, '(sin marca)') AS Marca, COUNT_BIG(*) AS Lineas,
               CAST(SUM(VTA_TOTAL) AS DECIMAL(18,2)) AS Venta,
               CAST(100.0 * SUM(VTA_MARGEN) / NULLIF(SUM(VTA_TOTAL), 0) AS DECIMAL(6,2)) AS MargenPct
        FROM {TABLA}
        WHERE VTA_FECHA >= DATEADD(MONTH, -12, CAST(GETDATE() AS date))
        GROUP BY VTA_MARCA
        ORDER BY Venta DESC
        """,
    )


def calendario() -> None:
    ejecutar(
        "COBERTURA: dias con venta vs anio/mes (ultimos 14 meses)",
        f"""
        SELECT DATEFROMPARTS(YEAR(VTA_FECHA), MONTH(VTA_FECHA), 1) AS Mes,
               COUNT(DISTINCT CAST(VTA_FECHA AS date)) AS DiasConVenta,
               COUNT(DISTINCT VTA_IDTRANSACTION) AS Transacciones,
               CAST(SUM(VTA_TOTAL) AS DECIMAL(18,2)) AS Venta
        FROM {TABLA}
        WHERE VTA_FECHA >= DATEADD(MONTH, -14, CAST(GETDATE() AS date))
        GROUP BY DATEFROMPARTS(YEAR(VTA_FECHA), MONTH(VTA_FECHA), 1)
        ORDER BY Mes
        """,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Analisis de la tabla de ventas")
    parser.add_argument("--auto", action="store_true", help="mide la primera consulta y decide")
    parser.add_argument("--todo", action="store_true", help="ejecuta todo sin medir")
    parser.add_argument("--indices", action="store_true", help="solo lista indices")
    parser.add_argument("--limite-segundos", type=float, default=90.0)
    args = parser.parse_args()

    indices()
    if args.indices:
        return 0

    titulo("FASE 1: MEDICION")
    _, segundos = totales()
    print(f"\n  Una pasada completa tarda {segundos:.1f}s.")

    if args.auto and segundos > args.limite_segundos:
        print(
            f"  El servidor tarda mas de {args.limite_segundos:.0f}s por escaneo. "
            "Conviene extraer una instantanea local (Parquet) antes de seguir analizando."
        )
        return 0

    titulo("FASE 2: ANALISIS")
    for funcion in (
        por_anio,
        por_mes,
        por_tipo_transaccion,
        por_categoria,
        por_tienda_canal,
        por_marca_familia,
        top_articulos,
        por_proveedor,
        calendario,
    ):
        try:
            funcion()
        except Exception as exc:  # noqa: BLE001
            print(f"\n  ERROR en {funcion.__name__}: {type(exc).__name__}: {str(exc)[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
