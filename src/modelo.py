"""Modelo de datos: traduce nombres lógicos a columnas reales.

La tabla objetivo se toma de MSSQL_TABLE en .env.local. Por defecto está mapeada a
una tabla de hechos de ventas (líneas de venta con costo y margen).

Si cambias de tabla, este es el ÚNICO archivo que hay que ajustar (junto con
MSSQL_TABLE en .env.local). Las páginas y las consultas usan nombres lógicos.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class Modelo:
    tabla: str
    fecha: str
    transaccion: str
    tipo: str
    articulo: str
    descripcion: str
    categoria: str
    familia: str
    marca: str
    proveedor: str
    tienda: str
    canal: str
    cantidad: str
    importe: str
    costo: str
    margen: str


def por_defecto() -> Modelo:
    """Mapeo a la tabla de hechos de ventas."""
    return Modelo(
        tabla=config.cargar().validar_tabla(),
        fecha="VTA_FECHA",
        transaccion="VTA_IDTRANSACTION",
        tipo="VTA_TPTRANSACTION",
        articulo="VTA_ARTICULO",
        descripcion="VTA_DESCRIPCION",
        categoria="VTA_CATEGORIA",
        familia="VTA_FAMILIA",
        marca="VTA_MARCA",
        proveedor="VTA_NMBPROV",
        tienda="VTA_TIENDA",
        canal="VTA_CANAL",
        cantidad="VTA_CANTIDAD",
        importe="VTA_TOTAL",
        costo="VTA_COSTOTOTAL",
        margen="VTA_MARGEN",
    )


def dimensiones(modelo: Modelo) -> dict[str, str]:
    """Dimensiones filtrables: etiqueta visible -> columna real."""
    return {
        "Tienda": modelo.tienda,
        "Categoría": modelo.categoria,
        "Familia": modelo.familia,
        "Marca": modelo.marca,
        "Canal": modelo.canal,
        "Tipo de transacción": modelo.tipo,
    }
