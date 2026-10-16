"""Configuración central del proyecto.

Precedencia: variables de entorno del proceso > archivo .env.local.

La cadena de conexión NUNCA se imprime ni se devuelve en las respuestas del
panel: contiene la contraseña. Solo se usa dentro de src/db.py.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ENV_FILE = RAIZ / ".env.local"

# Un nombre de objeto válido de SQL Server (esquema.tabla). Se valida para poder
# interpolar el nombre en el SQL sin riesgo: los valores van SIEMPRE parametrizados.
IDENTIFICADOR_SQL = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#]{0,127}(\.[A-Za-z_][A-Za-z0-9_$#]{0,127})?$")


def _leer_env_local() -> dict[str, str]:
    valores: dict[str, str] = {}
    if not ENV_FILE.exists():
        return valores
    for linea in ENV_FILE.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        valores[clave.strip()] = valor.strip().strip('"').strip("'")
    return valores


_ENV = _leer_env_local()


def _get(clave: str, por_defecto: str | None = None) -> str | None:
    return os.environ.get(clave) or _ENV.get(clave) or por_defecto


# Valores de la plantilla .env.local.example. Mientras sigan presentes, la
# configuración NO está lista: se trata como "sin conexión" y el panel arranca en
# modo demo, en lugar de fallar con un error de conexión incomprensible.
PATRONES_PLANTILLA = (
    "host\\instancia",
    "database=base_de_datos",
    "user id=usuario",
    "password=clave",
    "server=tu_servidor",
    "server=host",
)


def es_cadena_de_plantilla(cadena: str | None) -> bool:
    """¿La cadena de conexión sigue teniendo los valores de ejemplo?"""
    if not cadena:
        return False
    minusculas = cadena.lower()
    return any(patron in minusculas for patron in PATRONES_PLANTILLA)


@dataclass(frozen=True)
class Ajustes:
    connstring: str | None
    tabla: str
    usuario_local: str

    @property
    def es_plantilla(self) -> bool:
        return es_cadena_de_plantilla(self.connstring)

    @property
    def hay_conexion(self) -> bool:
        return bool(self.connstring) and not self.es_plantilla

    def validar_tabla(self) -> str:
        if not IDENTIFICADOR_SQL.match(self.tabla):
            raise ValueError(
                f"MSSQL_TABLE inválido: {self.tabla!r}. Se espera 'esquema.tabla' o 'tabla'."
            )
        return self.tabla


def cargar() -> Ajustes:
    return Ajustes(
        connstring=_get("MSSQL_CONNSTRING"),
        tabla=_get("MSSQL_TABLE", "dbo.Ventas") or "dbo.Ventas",
        usuario_local=_get("REPORT_USER", "local") or "local",
    )
