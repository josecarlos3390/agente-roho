"""Alcance de datos por usuario (quién puede ver qué).

Este módulo es el ÚNICO lugar del proyecto autorizado a decidir qué filas ve un
usuario. Dos reglas no negociables:

1. El filtro se aplica en el SQL (lo decide el servidor), nunca filtrando un
   DataFrame ya cargado. Si se filtra en pandas, un descuido en una página
   nueva expone datos de otro usuario.
2. El fragmento SQL se arma con nombres de columna validados y valores
   parametrizados. Jamás se concatena un valor.

Hoy `resolver_alcance` devuelve alcance total (un solo usuario: tú). La firma ya
es la definitiva, así que pasar a multiusuario es rellenar el TODO de abajo con
la tabla de configuración, sin tocar ninguna página.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

_COLUMNA_VALIDA = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


@dataclass(frozen=True)
class Alcance:
    """Dimensiones de seguridad que se aplican al usuario actual.

    ``dimensiones`` mapea columna -> valores permitidos, por ejemplo
    ``{"Sucursal": ["Norte", "Sur"]}``. Si está vacío, el alcance es total.
    """

    usuario: str
    rol: str
    dimensiones: Mapping[str, Sequence[str]] = field(default_factory=dict)

    @property
    def es_total(self) -> bool:
        return not self.dimensiones

    def descripcion(self) -> str:
        if self.es_total:
            return f"{self.usuario} ({self.rol}) — sin restricción de filas"
        partes = [f"{col} ∈ {list(vals)}" for col, vals in self.dimensiones.items()]
        return f"{self.usuario} ({self.rol}) — " + "; ".join(partes)

    def predicado(self, alias: str = "t") -> tuple[str, list]:
        """Devuelve (fragmento_sql, parametros) para añadir con AND al WHERE."""
        if self.es_total:
            return "1=1", []

        condiciones: list[str] = []
        params: list = []
        for columna, valores in self.dimensiones.items():
            if not _COLUMNA_VALIDA.match(columna):
                raise ValueError(f"Nombre de columna de alcance inválido: {columna!r}")
            valores_limpios = [v for v in valores if v is not None]
            if not valores_limpios:
                # Una dimensión configurada sin valores no debe ampliar el acceso.
                condiciones.append("1=0")
                continue
            marcadores = ",".join("?" for _ in valores_limpios)
            condiciones.append(f"{alias}.[{columna}] IN ({marcadores})")
            params.extend(valores_limpios)

        return (" AND ".join(condiciones) if condiciones else "1=0"), params


def resolver_alcance(usuario: str) -> Alcance:
    """Alcance efectivo del usuario.

    Fase 1 (actual): un único usuario, alcance total.

    TODO fase multiusuario: leer la configuración aplicada desde SQL Server, p.ej.

        SELECT Dimension, Valor
        FROM seguridad.UsuarioAlcance
        WHERE Usuario = ? AND Activo = 1

    y agrupar por Dimension. Ese cambio queda contenido aquí: ninguna página
    del panel necesita modificarse.
    """
    return Alcance(usuario=usuario, rol="administrador local", dimensiones={})
