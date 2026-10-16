"""Acceso a SQL Server.

Reglas del módulo (importantes para la fase multiusuario):

1. Todo el SQL de la aplicación vive en src/queries.py o en scripts de consola.
   La interfaz nunca construye SQL.
2. Los valores van SIEMPRE parametrizados (marcadores ``?`` de ODBC).
   Lo único que se interpola es el nombre de tabla, ya validado.
3. La conexión se abre en modo solo lectura (``readonly=True``), como segunda
   barrera además del login de base de datos con permisos mínimos.

Nota sobre la conexión: la cadena de .env.local se descompone en parámetros y se
pasa a pyodbc como argumentos, NO como cadena completa. Motivo comprobado: el
controlador ODBC 17 de este equipo rechazaba la forma de cadena
("Invalid connection string attribute") y el login llegaba vacío, mientras que la
forma por parámetros conecta correctamente.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import pandas as pd
import pyodbc

from . import config

# pandas avisa por usar una conexion DBAPI2 directa; es intencional (evitamos
# depender de SQLAlchemy para una sola base de datos).
warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy connectable")

# Controladores ODBC preferidos, en orden.
DRIVERS_PREFERIDOS = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
)

# Alias de atributos ODBC -> palabras clave que pyodbc acepta como argumento.
_ALIAS_KWARGS = {
    "data source": "server",
    "address": "server",
    "addr": "server",
    "network address": "server",
    "initial catalog": "database",
    "user id": "uid",
    "user": "uid",
    "password": "pwd",
    "integrated security": "trusted_connection",
}


@dataclass(frozen=True)
class Diagnostico:
    ok: bool
    detalle: str


def _resolver_driver(explicito: str | None = None) -> str:
    if explicito:
        return explicito
    disponibles = pyodbc.drivers()
    for candidato in DRIVERS_PREFERIDOS:
        if candidato in disponibles:
            return candidato
    raise RuntimeError(
        "No hay ningún controlador ODBC de SQL Server instalado. "
        f"Disponibles: {disponibles or 'ninguno'}"
    )


def kwargs_desde_cadena(cadena: str) -> dict[str, str]:
    """Convierte 'Server=...;Database=...;...' en argumentos de pyodbc."""
    partes: dict[str, str] = {}
    for trozo in cadena.split(";"):
        if "=" not in trozo:
            continue
        clave, valor = trozo.split("=", 1)
        partes[clave.strip().lower()] = valor.strip()

    kwargs = {_ALIAS_KWARGS.get(clave, clave): valor for clave, valor in partes.items()}
    kwargs.setdefault("driver", _resolver_driver())
    # Estos dos los controla este módulo, no la cadena.
    kwargs.pop("timeout", None)
    kwargs.pop("readonly", None)
    return kwargs


def driver_en_uso(cadena: str | None = None) -> str:
    """Controlador ODBC que se usará, sin revelar la contraseña."""
    if cadena is None:
        cadena = config.cargar().connstring or ""
    return kwargs_desde_cadena(cadena)["driver"]


def _conectar() -> pyodbc.Connection:
    aj = config.cargar()
    if not aj.connstring:
        raise RuntimeError("Falta MSSQL_CONNSTRING en .env.local o en el entorno.")
    # readonly=True => SQL_ATTR_ACCESS_MODE = SQL_MODE_READ_ONLY
    return pyodbc.connect(
        timeout=15,
        readonly=True,
        autocommit=True,
        **kwargs_desde_cadena(aj.connstring),
    )


def consultar(sql: str, params: tuple | list = ()) -> pd.DataFrame:
    """Ejecuta una consulta parametrizada y devuelve un DataFrame."""
    with _conectar() as cn:
        return pd.read_sql_query(sql, cn, params=list(params) or None)


def probar_conexion() -> Diagnostico:
    """Prueba de conectividad + identidad efectiva del login."""
    try:
        with _conectar() as cn:
            cur = cn.cursor()
            cur.execute(
                "SELECT @@VERSION AS version, DB_NAME() AS base, "
                "SUSER_SNAME() AS login_servidor, USER_NAME() AS usuario_base"
            )
            fila = cur.fetchone()
        if fila is None:
            return Diagnostico(False, "La consulta de diagnóstico no devolvió filas.")
        version = str(fila.version).splitlines()[0]
        return Diagnostico(
            True,
            f"{version} | base={fila.base} | login={fila.login_servidor} | usuario={fila.usuario_base}",
        )
    except Exception as exc:  # noqa: BLE001 - se reporta al usuario tal cual
        return Diagnostico(False, f"{type(exc).__name__}: {exc}")


def consultar_limitado(
    sql: str,
    limite_filas: int = 200,
    timeout_segundos: int = 30,
) -> pd.DataFrame:
    """Ejecuta SQL de solo lectura con tope de filas y de tiempo.

    Usa SET ROWCOUNT en lugar de reescribir la consulta: así funciona con ORDER BY,
    CTEs y agregaciones sin tocar el texto original. Debe llamarse SIEMPRE después
    de validar la consulta con src.seguridad_sql.validar_consulta.
    """
    conexion = _conectar()
    try:
        conexion.timeout = int(timeout_segundos)
        cursor = conexion.cursor()
        cursor.execute(f"SET ROWCOUNT {int(limite_filas)}")
        try:
            return pd.read_sql_query(sql, conexion)
        finally:
            try:
                cursor.execute("SET ROWCOUNT 0")
            except Exception:  # noqa: BLE001 - la conexión se cierra igualmente
                pass
    finally:
        conexion.close()
