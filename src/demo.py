"""Datos sintéticos para trabajar sin conexión a la base (modo demo).

Imitan una tabla de hechos de ventas (venta con costo y margen) para poder
desarrollar y probar el panel sin tocar el servidor.

IMPORTANTE: los nombres de columna NO se escriben a mano; se toman del modelo
(src/modelo.py). Así el modo demo sigue funcionando cuando el mapeo apunta a las
columnas reales de la tabla (por ejemplo VTA_FECHA, VTA_TOTAL...).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .modelo import por_defecto

TIENDAS = ["Tienda Centro", "Tienda Norte", "Tienda Sur", "Tienda Este", "Outlet"]
CANALES = ["Retail", "Mayoreo", "E-commerce"]
TIPOS = ["Sale", "Refund"]
FAMILIAS = {
    "Bebidas": ["Refrescos", "Aguas", "Jugos"],
    "Abarrotes": ["Pastas", "Aceites", "Enlatados"],
    "Limpieza": ["Detergentes", "Jabones"],
    "Cuidado personal": ["Shampoo", "Cremas"],
    "Botanas": ["Frituras", "Galletas"],
}
MARCAS = ["Marca A", "Marca B", "Marca C", "Marca D", "Genérica"]
PROVEEDORES = ["Prov Alfa", "Prov Beta", "Prov Gamma", "Prov Delta"]


def generar(filas: int = 4000, semilla: int = 7) -> pd.DataFrame:
    modelo = por_defecto()
    rng = np.random.default_rng(semilla)

    fechas = pd.to_datetime("2025-10-01") + pd.to_timedelta(rng.integers(0, 380, filas), unit="D")
    familias = rng.choice(list(FAMILIAS), filas, p=[0.3, 0.25, 0.15, 0.15, 0.15])
    categorias = np.array([rng.choice(FAMILIAS[f]) for f in familias])
    articulos = np.array([f"{c[:3].upper()}-{rng.integers(100, 999)}" for c in categorias])

    precio = np.round(rng.uniform(12, 480, filas), 2)
    cantidad = rng.integers(1, 30, filas)
    tipo = rng.choice(TIPOS, filas, p=[0.96, 0.04])
    signo = np.where(tipo == "Refund", -1.0, 1.0)

    importe = np.round(precio * cantidad, 2) * signo
    costo_unitario = np.round(precio * rng.uniform(0.55, 0.85, filas), 2)
    costo = np.round(costo_unitario * cantidad, 2) * signo
    margen = np.round(importe - costo, 2)

    # Las claves del diccionario son las columnas reales del modelo.
    df = pd.DataFrame(
        {
            modelo.fecha: fechas,
            modelo.transaccion: [f"T{200000 + i}" for i in range(filas)],
            modelo.tipo: tipo,
            modelo.articulo: articulos,
            modelo.descripcion: [f"Producto {a}" for a in articulos],
            modelo.categoria: categorias,
            modelo.familia: familias,
            modelo.marca: rng.choice(MARCAS, filas),
            modelo.proveedor: rng.choice(PROVEEDORES, filas),
            modelo.tienda: rng.choice(TIENDAS, filas),
            modelo.canal: rng.choice(CANALES, filas, p=[0.6, 0.25, 0.15]),
            modelo.cantidad: cantidad,
            modelo.importe: importe,
            modelo.costo: costo,
            modelo.margen: margen,
        }
    )

    # Ruido deliberado para que la pestaña de calidad de datos tenga qué mostrar.
    df.loc[df.sample(frac=0.02, random_state=1).index, modelo.categoria] = None
    df.loc[df.sample(frac=0.01, random_state=2).index, modelo.proveedor] = None
    df.loc[df.sample(frac=0.015, random_state=3).index, modelo.transaccion] = df[
        modelo.transaccion
    ].iloc[0]

    return df.sort_values(modelo.fecha, ascending=False).reset_index(drop=True)
