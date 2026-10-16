"""Comprobación de humo del proyecto (sin pytest).

Verifica: datos demo, resolución de alcance, SQL parametrizado y arranque del
panel Streamlit en modo headless.

Ejecutar:  .venv\\Scripts\\python.exe verificar.py
"""

from __future__ import annotations

import sys
import traceback
from datetime import date

import pandas as pd

from src import demo
from src import informe
from src import modelo as modelo_mod
from src import queries
from src.scope import Alcance

fallos: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    print(("  OK   " if condicion else "  FALLO") + f"  {nombre}" + (f"  — {detalle}" if detalle else ""))
    if not condicion:
        fallos.append(nombre)


print("\n[1] Datos de ejemplo")
modelo = modelo_mod.por_defecto()
df = demo.generar(500, semilla=1)
check("genera las filas pedidas", len(df) == 500, f"{len(df)} filas")
columnas_modelo = {
    modelo.fecha, modelo.transaccion, modelo.tipo, modelo.articulo, modelo.descripcion,
    modelo.categoria, modelo.familia, modelo.marca, modelo.proveedor, modelo.tienda,
    modelo.canal, modelo.cantidad, modelo.importe, modelo.costo, modelo.margen,
}
faltan = sorted(columnas_modelo - set(df.columns))
check(
    "el demo cubre TODAS las columnas del modelo",
    not faltan,
    f"faltan: {faltan}" if faltan else f"{len(columnas_modelo)} columnas",
)
check("incluye nulos para probar calidad", df.isna().any().any())

from src import config as config_mod  # noqa: E402

check(
    "detecta la plantilla sin editar",
    config_mod.es_cadena_de_plantilla(
        r"Server=HOST\INSTANCIA,1433;Database=BASE_DE_DATOS;User Id=USUARIO;Password=CLAVE"
    ),
)
check(
    "no confunde una conexión real con la plantilla",
    not config_mod.es_cadena_de_plantilla(
        "Server=10.1.2.3,1433;Database=Ventas;User Id=lector;Password=secreta"
    ),
)

print("\n[2] Alcance por usuario")
total = Alcance("local", "administrador local", {})
pred, params = total.predicado("t")
check("alcance total no añade parámetros", pred == "1=1" and params == [], f"{pred} / {params}")

restringido = Alcance("juan", "lector", {"Sucursal": ["Norte", "Sur"]})
pred, params = restringido.predicado("t")
check(
    "alcance restringido parametriza los valores",
    pred == "t.[Sucursal] IN (?,?)" and params == ["Norte", "Sur"],
    f"{pred} / {params}",
)

try:
    Alcance("x", "y", {"Sucursal; DROP TABLE t": ["a"]}).predicado("t")
    check("rechaza nombre de columna inyectable", False)
except ValueError:
    check("rechaza nombre de columna inyectable", True)

print("\n[3] SQL parametrizado")
sql, params = queries.sql_detalle(
    restringido,
    modelo,
    desde=date(2025, 1, 1),
    hasta=date(2025, 12, 31),
    filtros={modelo.categoria: ["Textil"]},
    busqueda="ABC",
)
check("usa marcadores, no literales", "?" in sql and "Textil" not in sql and "ABC" not in sql)
check("inyecta el alcance del usuario", "Sucursal] IN (?,?)" in sql)
check("recorta columnas con relleno (nchar)", "RTRIM(t.[" in sql)
check("limita el número de filas", "TOP (" in sql)

sql_agr, _ = queries.sql_agregado(total, modelo, modelo.tienda)
sql_mes, _ = queries.sql_mensual(total, modelo)
check("el agregado agrupa por dimensión", "GROUP BY" in sql_agr)
check("el mensual agrupa por mes", "DATEFROMPARTS" in sql_mes)

print("\n[4] Calculos del informe ejecutivo")
meses = pd.date_range("2025-08-01", periods=14, freq="MS")
mensual_prueba = pd.DataFrame(
    [
        {
            "Mes": m,
            "Importe": 1000.0 + i * 10,
            "Costo": (1000.0 + i * 10) * 0.8,
            "Margen": (1000.0 + i * 10) * 0.2,
            "Cantidad": 100,
            "Filas": 50,
        }
        for i, m in enumerate(meses)
    ]
)
datos = informe.kpis(mensual_prueba, meses[-1])
venta_esperada = 1000.0 + 13 * 10
check("KPIs: venta del mes", abs(datos["venta"] - venta_esperada) < 0.01, f"{datos['venta']:.0f}")
check(
    "KPIs: variacion interanual",
    datos["var_yoy"] is not None and abs(datos["var_yoy"] - (venta_esperada / 1010.0 - 1) * 100) < 0.01,
    f"{datos['var_yoy']:.2f}%",
)
check("KPIs: margen porcentual", abs(datos["margen_pct"] - 20.0) < 0.01, f"{datos['margen_pct']:.2f}%")
check("KPIs: variacion mensual calculada", datos["var_mom"] is not None, f"{datos['var_mom']:.2f}%")

filas_dim = []
for i, m in enumerate(meses):
    for nombre, base in (("A", 600.0), ("B", 400.0)):
        venta = base + i * 5
        filas_dim.append(
            {
                "Mes": m,
                "Dimension": nombre,
                "Importe": venta,
                "Costo": venta * 0.75,
                "Margen": venta * 0.25,
                "Cantidad": 10,
                "Filas": 5,
            }
        )
tabla = informe.tabla_dimension(pd.DataFrame(filas_dim), meses[-1])
check("tabla por dimension: filas", len(tabla) == 2, f"{len(tabla)} filas")
check("tabla por dimension: participacion suma 100", abs(tabla["Part. %"].sum() - 100) < 0.01)
check("tabla por dimension: margen %", abs(tabla["Margen %"].iloc[0] - 25.0) < 0.01)
check("tabla por dimension: variacion interanual", not tabla["Var YoY %"].isna().all())
frases = informe.lectura(datos, {"Categoría": tabla})
check("lectura del mes genera conclusiones", len(frases) >= 3 and all(isinstance(f, str) for f in frases), f"{len(frases)} frases")

print("\n[5] El panel arranca (headless)")
try:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("app.py", default_timeout=180).run()
    if at.exception:
        detalle = "; ".join(getattr(e, "message", str(e)) for e in at.exception)
        check("sin excepciones al ejecutar app.py", False, detalle)
    else:
        check("sin excepciones al ejecutar app.py", True, f"{len(at.metric)} métricas en pantalla")

    # Un error capturado por el panel (st.error + st.stop) no genera excepción,
    # pero deja la pantalla vacía. Estas dos comprobaciones detectan ese caso.
    errores = [str(getattr(e, "value", "")) for e in getattr(at, "error", [])]
    check("el panel no muestra errores", not errores, "; ".join(errores)[:160])
    check(
        "el panel pinta métricas",
        len(at.metric) >= 4,
        f"{len(at.metric)} métricas (¿modo demo roto o sin datos?)",
    )
except Exception:  # noqa: BLE001
    check("sin excepciones al ejecutar app.py", False, traceback.format_exc(limit=4))

print()
if fallos:
    print(f"RESULTADO: {len(fallos)} fallo(s) -> {fallos}")
else:
    print("RESULTADO: todo correcto")
sys.exit(1 if fallos else 0)
