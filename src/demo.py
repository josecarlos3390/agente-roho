"""Datos sintéticos para trabajar sin conexión a la base (modo demo).

Imitan el esquema de dbo.WHS_VENTA (ventas con costo y margen) para poder
desarrollar y probar el panel sin tocar el servidor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TIENDAS = ["Tienda Centro", "Tienda Norte", "Tienda Sur", "Tienda Este", "Outlet"]
CANALES = ["Retail", "Mayoreo", "E-commerce"]
TIPOS = ["Factura", "Nota de crédito"]
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
    rng = np.random.default_rng(semilla)

    fechas = pd.to_datetime("2025-10-01") + pd.to_timedelta(rng.integers(0, 380, filas), unit="D")
    familias = rng.choice(list(FAMILIAS), filas, p=[0.3, 0.25, 0.15, 0.15, 0.15])
    subcategorias = np.array([rng.choice(FAMILIAS[f]) for f in familias])
    articulos = np.array([f"{s[:3].upper()}-{rng.integers(100, 999)}" for s in subcategorias])

    precio = np.round(rng.uniform(12, 480, filas), 2)
    cantidad = rng.integers(1, 30, filas)
    tipo = rng.choice(TIPOS, filas, p=[0.96, 0.04])
    signo = np.where(tipo == "Nota de crédito", -1.0, 1.0)

    importe = np.round(precio * cantidad, 2) * signo
    costo_unitario = np.round(precio * rng.uniform(0.55, 0.85, filas), 2)
    costo = np.round(costo_unitario * cantidad, 2) * signo
    margen = np.round(importe - costo, 2)

    df = pd.DataFrame(
        {
            "Fecha": fechas,
            "IdTicket": [f"T{200000 + i}" for i in range(filas)],
            "Tipo": tipo,
            "Articulo": articulos,
            "Descripcion": [f"Producto {a}" for a in articulos],
            "Categoria": subcategorias,
            "Familia": familias,
            "Marca": rng.choice(MARCAS, filas),
            "Proveedor": rng.choice(PROVEEDORES, filas),
            "Tienda": rng.choice(TIENDAS, filas),
            "Canal": rng.choice(CANALES, filas, p=[0.6, 0.25, 0.15]),
            "Cantidad": cantidad,
            "Importe": importe,
            "Costo": costo,
            "Margen": margen,
        }
    )

    # Ruido deliberado para que la pestaña de calidad de datos tenga qué mostrar.
    df.loc[df.sample(frac=0.02, random_state=1).index, "Categoria"] = None
    df.loc[df.sample(frac=0.01, random_state=2).index, "Proveedor"] = None
    df.loc[df.sample(frac=0.015, random_state=3).index, "IdTicket"] = df["IdTicket"].iloc[0]

    return df.sort_values("Fecha", ascending=False).reset_index(drop=True)
