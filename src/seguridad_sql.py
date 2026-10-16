"""Guardas de solo lectura para SQL arbitrario recibido de un agente.

Motivo: cuando el panel o un agente pueden enviar SQL libre, la barrera no puede
ser un prompt. Estas comprobaciones se aplican ANTES de enviar nada al servidor y
son la tercera capa de defensa, después de:

1. El login de base de datos con permisos mínimos.
2. La conexión abierta con ``readonly=True`` (SQL_ATTR_ACCESS_MODE).

El enfoque (lista blanca de inicio + patrones prohibidos) está inspirado en el
enfoque de ``safety.ts`` de nocentino/sql-mcp-server, con el mismo principio:
la herramienta que no puede ejecutarse no depende del criterio del modelo.
"""

from __future__ import annotations

import re

# La consulta debe EMPEZAR por una de estas palabras.
PERMITIDO_INICIO = re.compile(r"^\s*(SELECT|WITH|DECLARE)\b", re.IGNORECASE)

PATRONES_PROHIBIDOS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("escritura de datos", re.compile(r"\b(INSERT\s+INTO|UPDATE\s+\w|DELETE\s+FROM|MERGE\s+INTO)\b", re.I)),
    ("DDL", re.compile(r"\b(DROP|ALTER|CREATE|TRUNCATE)\s+(TABLE|DATABASE|INDEX|VIEW|PROCEDURE|FUNCTION|TRIGGER|SCHEMA|LOGIN|USER|ROLE)\b", re.I)),
    ("creación de objetos con SELECT INTO", re.compile(r"\bSELECT\b[\s\S]*?\bINTO\b", re.I)),
    ("ejecución dinámica", re.compile(r"\b(EXEC|EXECUTE)\b|\bSP_EXECUTESQL\b", re.I)),
    ("procedimientos del sistema sensibles", re.compile(r"\b(XP_CMDSHELL|XP_REGREAD|SP_CONFIGURE|SP_ADDLOGIN|SP_ADDROLEMEMBER|SP_PASSWORD)\b", re.I)),
    ("permisos", re.compile(r"\b(GRANT|REVOKE|DENY)\b", re.I)),
    ("copia de seguridad y restauración", re.compile(r"\b(BACKUP|RESTORE)\b", re.I)),
    ("acceso a ficheros y fuentes externas", re.compile(r"\b(OPENROWSET|OPENDATASOURCE|OPENQUERY|BULK\s+INSERT)\b", re.I)),
    ("parada del servicio", re.compile(r"\b(SHUTDOWN|RECONFIGURE)\b", re.I)),
    ("segunda sentencia peligrosa", re.compile(r";\s*(EXEC|EXECUTE|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|GRANT|REVOKE)\b", re.I)),
)


class ConsultaNoPermitida(ValueError):
    """La consulta solicitada no cumple la política de solo lectura."""


def validar_consulta(sql: str) -> str:
    """Valida una consulta de solo lectura. Devuelve la consulta o lanza excepción."""
    if not sql or not sql.strip():
        raise ConsultaNoPermitida("La consulta está vacía.")

    limpia = re.sub(r"--[^\n]*", " ", sql)          # comentarios de línea
    limpia = re.sub(r"/\*[\s\S]*?\*/", " ", limpia)  # comentarios de bloque

    if not PERMITIDO_INICIO.match(limpia):
        raise ConsultaNoPermitida(
            "Solo se permiten consultas que empiecen por SELECT, WITH o DECLARE."
        )

    for motivo, patron in PATRONES_PROHIBIDOS:
        if patron.search(limpia):
            raise ConsultaNoPermitida(f"Consulta bloqueada por política de solo lectura ({motivo}).")

    return sql
