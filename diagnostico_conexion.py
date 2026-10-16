"""Diagnostico de conexion. No imprime la contrasena en ningun caso."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pyodbc

from src import config

MASCARA = re.compile(r"(?i)(pwd|password)\s*=\s*[^;]*")


def ocultar(texto: str) -> str:
    return MASCARA.sub(r"\1=***", texto)


print("== 1. Variables de entorno relevantes ==")
for clave in ("MSSQL_CONNSTRING", "MSSQL_SERVER", "MSSQL_USER", "MSSQL_PASSWORD", "MSSQL_DATABASE"):
    valor = os.environ.get(clave)
    print(f"  {clave}: {'(no definida)' if valor is None else ocultar(valor)!r}")

print("\n== 2. Contenido crudo de .env.local (clave oculta) ==")
ruta = Path(".env.local")
lineas = ruta.read_text(encoding="utf-8").splitlines()
for i, linea in enumerate(lineas, 1):
    print(f"  {i:>2}: {ocultar(linea)}")

print("\n== 3. Cadena que interpreta la app ==")
aj = config.cargar()
cs = aj.connstring or ""
print(f"  longitud: {len(cs)}")
print(f"  {ocultar(cs)}")

print("\n== 4. Atributos detectados ==")
for atributo in cs.split(";"):
    if not atributo.strip():
        continue
    nombre = atributo.split("=", 1)[0].strip()
    valor = ocultar(atributo).split("=", 1)[1] if "=" in atributo else ""
    print(f"  {nombre!r} -> {valor!r}")

print("\n== 5. Intento A: cadena tal cual (con DRIVER anadido) ==")
final = f"DRIVER={{ODBC Driver 17 for SQL Server}};{cs}"
try:
    cn = pyodbc.connect(final, timeout=10, readonly=True, autocommit=True)
    print("  OK:", cn.cursor().execute("SELECT DB_NAME()").fetchval())
    cn.close()
except Exception as exc:  # noqa: BLE001
    print(f"  FALLO: {type(exc).__name__}: {str(exc)[:300]}")

print("\n== 6. Intento B: parametros por separado ==")
campos = {}
for atributo in cs.split(";"):
    if "=" in atributo:
        k, v = atributo.split("=", 1)
        campos[k.strip().lower()] = v.strip()
try:
    cn = pyodbc.connect(
        driver="ODBC Driver 17 for SQL Server",
        server=campos.get("server", ""),
        database=campos.get("database", ""),
        uid=campos.get("user id", campos.get("uid", "")),
        pwd=campos.get("password", campos.get("pwd", "")),
        encrypt="yes",
        trustservercertificate="yes",
        timeout=10,
        readonly=True,
        autocommit=True,
    )
    cur = cn.cursor()
    cur.execute("SELECT @@VERSION AS v, DB_NAME() AS b, SUSER_SNAME() AS l, USER_NAME() AS u")
    fila = cur.fetchone()
    print("  OK:", str(fila.v).splitlines()[0])
    print(f"  base={fila.b} | login={fila.l} | usuario_base={fila.u}")
    cn.close()
except Exception as exc:  # noqa: BLE001
    print(f"  FALLO: {type(exc).__name__}: {str(exc)[:300]}")
