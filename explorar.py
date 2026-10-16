"""Explora el servidor SQL Server: conectividad, inventario y perfil de una tabla.

Uso:
    .venv\\Scripts\\python.exe explorar.py
    .venv\\Scripts\\python.exe explorar.py --tabla dbo.NombreTabla
    .venv\\Scripts\\python.exe explorar.py --tabla dbo.X --muestra 5
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from src import config, db

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)
pd.set_option("display.max_colwidth", 40)


def seccion(titulo: str) -> None:
    print("\n" + "=" * 78)
    print(titulo)
    print("=" * 78)


def conectividad() -> bool:
    seccion("1. CONECTIVIDAD")
    ajustes = config.cargar()
    print(f"  Controlador ODBC : {db.driver_en_uso()}")
    print(f"  Servidor / base  : {ajustes.connstring.split('Password')[0].split(';')[0]}")
    diagnostico = db.probar_conexion()
    if not diagnostico.ok:
        print(f"  FALLO: {diagnostico.detalle}")
        return False
    print(f"  OK: {diagnostico.detalle}")
    return True


def inventario() -> None:
    seccion("2. BASES DE DATOS VISIBLES")
    bases = db.consultar(
        "SELECT name AS Base, state_desc AS Estado, recovery_model_desc AS Recuperacion, "
        "compatibility_level AS Compat FROM sys.databases ORDER BY database_id"
    )
    print(bases.to_string(index=False))

    seccion("3. TABLAS DE USUARIO (por filas)")
    tablas = db.consultar(
        """
        SELECT s.name AS Esquema, t.name AS Tabla,
               SUM(p.rows) AS Filas,
               CAST(SUM(a.total_pages) * 8.0 / 1024 AS DECIMAL(12,2)) AS MB
        FROM sys.tables AS t
        JOIN sys.schemas AS s ON s.schema_id = t.schema_id
        JOIN sys.indexes AS i ON i.object_id = t.object_id
        JOIN sys.partitions AS p ON p.object_id = i.object_id AND p.index_id = i.index_id
        JOIN sys.allocation_units AS a ON a.container_id = p.partition_id
        WHERE t.is_ms_shipped = 0 AND i.index_id IN (0, 1)
        GROUP BY s.name, t.name
        ORDER BY SUM(p.rows) DESC
        """
    )
    print(f"  Total: {len(tablas)} tablas\n")
    print(tablas.to_string(index=False))

    seccion("4. VISTAS DE USUARIO")
    vistas = db.consultar(
        "SELECT TABLE_SCHEMA AS Esquema, TABLE_NAME AS Vista FROM INFORMATION_SCHEMA.VIEWS "
        "ORDER BY TABLE_SCHEMA, TABLE_NAME"
    )
    print(f"  Total: {len(vistas)} vistas")
    if len(vistas):
        print(vistas.to_string(index=False))

    seccion("5. PROCEDIMIENTOS ALMACENADOS (primeros 30)")
    procs = db.consultar(
        "SELECT TOP 30 ROUTINE_SCHEMA AS Esquema, ROUTINE_NAME AS Procedimiento "
        "FROM INFORMATION_SCHEMA.ROUTINES WHERE ROUTINE_TYPE='PROCEDURE' "
        "ORDER BY ROUTINE_SCHEMA, ROUTINE_NAME"
    )
    print(f"  Total mostrado: {len(procs)}")
    if len(procs):
        print(procs.to_string(index=False))


def perfil(objeto: str, estadisticas: bool = False) -> None:
    if "." not in objeto:
        print("El nombre debe ser esquema.tabla (ej. dbo.Ventas)")
        return

    esquema, tabla = objeto.split(".", 1)
    seccion(f"6. PERFIL DE {esquema}.{tabla}")

    columnas = db.consultar(
        """
        SELECT c.column_id AS Ord, c.name AS Columna, ty.name AS Tipo,
               c.max_length AS Largo, c.precision AS Precision, c.scale AS Escala,
               CASE WHEN c.is_nullable = 1 THEN 'SI' ELSE 'NO' END AS Nulos,
               CASE WHEN pk.column_id IS NOT NULL THEN 'PK' ELSE '' END AS Clave
        FROM sys.columns AS c
        JOIN sys.types AS ty ON ty.user_type_id = c.user_type_id
        LEFT JOIN (
            SELECT ic.object_id, ic.column_id
            FROM sys.index_columns AS ic
            JOIN sys.indexes AS ix ON ix.object_id = ic.object_id AND ix.index_id = ic.index_id
            WHERE ix.is_primary_key = 1
        ) AS pk ON pk.object_id = c.object_id AND pk.column_id = c.column_id
        WHERE c.object_id = OBJECT_ID(?)
        ORDER BY c.column_id
        """,
        (objeto,),
    )
    if columnas.empty:
        print(f"  No se encontro el objeto {objeto} o no tienes permisos para verlo.")
        return
    print(columnas.to_string(index=False))

    total = db.consultar(f"SELECT COUNT_BIG(*) AS Filas FROM {objeto}")
    print(f"\n  Filas: {int(total['Filas'].iloc[0]):,}")

    columnas_fecha = columnas[columnas["Tipo"].isin(["date", "datetime", "datetime2", "smalldatetime"])]
    for nombre in columnas_fecha["Columna"].tolist()[:3]:
        rango = db.consultar(
            f"SELECT MIN([{nombre}]) AS Minimo, MAX([{nombre}]) AS Maximo FROM {objeto}"
        )
        print(f"  {nombre}: {rango['Minimo'].iloc[0]} -> {rango['Maximo'].iloc[0]}")

    columnas_num = columnas[columnas["Tipo"].isin(["int", "bigint", "smallint", "decimal", "numeric", "float", "money"])]
    if not estadisticas:
        print(
            f"\n  (estadisticas de {len(columnas_num)} columnas numericas omitidas; "
            "usa --estadisticas para calcularlas)"
        )
        return
    for nombre in columnas_num["Columna"].tolist()[:4]:
        estad = db.consultar(
            f"SELECT COUNT(*) AS Filas, COUNT([{nombre}]) AS NoNulos, "
            f"COUNT(DISTINCT [{nombre}]) AS Distintos, "
            f"MIN([{nombre}]) AS Minimo, MAX([{nombre}]) AS Maximo, "
            f"AVG(CAST([{nombre}] AS FLOAT)) AS Media FROM {objeto}"
        )
        print(f"\n  {nombre}:")
        print("   " + estad.to_string(index=False).replace("\n", "\n   "))


def main() -> int:
    parser = argparse.ArgumentParser(description="Explora el SQL Server configurado en .env.local")
    parser.add_argument("--tabla", help="esquema.tabla a perfilar (ej. dbo.Ventas)")
    parser.add_argument(
        "--estadisticas",
        action="store_true",
        help="calcula min/max/media de columnas numericas (escaneos completos, lento en tablas grandes)",
    )
    args = parser.parse_args()

    if not conectividad():
        return 1
    try:
        inventario()
        if args.tabla:
            perfil(args.tabla, estadisticas=args.estadisticas)
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
