"""Genera el informe ejecutivo mensual por línea de comandos.

Uso:
    .venv\\Scripts\\python.exe informe_mensual.py                 # ultimo mes cerrado
    .venv\\Scripts\\python.exe informe_mensual.py --mes 2026-09
    .venv\\Scripts\\python.exe informe_mensual.py --excel         # ademas guarda .xlsx
    .venv\\Scripts\\python.exe informe_mensual.py --umbral 18     # umbral de alerta de margen

Sirve igual para el panel (mismos cálculos, src/informe.py) y para una tarea
programada que reparta el informe cada mes.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from src import config, db, informe
from src import modelo as modelo_mod
from src import queries
from src.scope import resolver_alcance

DIMENSIONES = ("Categoría", "Tienda", "Marca", "Tipo de transacción")
MESES_VENTANA = 36


def cargar(meses_ventana: int = MESES_VENTANA):
    ajustes = config.cargar()
    modelo = modelo_mod.por_defecto()
    alcance = resolver_alcance(ajustes.usuario_local)
    dimensiones = modelo_mod.dimensiones(modelo)

    inicio = (pd.Timestamp(date.today()) - pd.DateOffset(months=meses_ventana)).date()
    fin = date.today()

    sql, params = queries.sql_mensual(alcance, modelo, inicio, fin)
    mensual = db.consultar(sql, params)

    tablas = {}
    for etiqueta in DIMENSIONES:
        sql_dim, p_dim = queries.sql_mensual_dimension(
            alcance, modelo, dimensiones[etiqueta], inicio, fin
        )
        tablas[etiqueta] = db.consultar(sql_dim, p_dim)

    sql_max, p_max = queries.sql_fecha_maxima(alcance, modelo)
    fecha_max = pd.to_datetime(db.consultar(sql_max, p_max)["Ultima"].iloc[0]).date()
    return mensual, tablas, fecha_max


def main() -> int:
    try:  # la consola de Windows puede no ser UTF-8; los informes llevan acentos
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    parser = argparse.ArgumentParser(description="Informe ejecutivo mensual de ventas")
    parser.add_argument("--mes", help="mes a informar en formato YYYY-MM (por defecto, el ultimo cerrado)")
    parser.add_argument("--umbral", type=float, default=15.0, help="umbral de alerta de margen %%")
    parser.add_argument("--excel", action="store_true", help="guarda el informe en out/")
    args = parser.parse_args()

    mensual, tablas, fecha_max = cargar()
    meses = informe.meses_disponibles(mensual)
    if not meses:
        print("Sin datos en la ventana analizada.")
        return 1

    if args.mes:
        anio, mes = (int(x) for x in args.mes.split("-"))
        mes_sel = pd.Timestamp(year=anio, month=mes, day=1)
        if mes_sel not in meses:
            print(f"El mes {args.mes} no tiene datos. Disponibles: {meses[0]:%Y-%m} a {meses[-1]:%Y-%m}")
            return 1
    else:
        mes_sel = informe.mes_completo_por_defecto(mensual, fecha_max)

    datos = informe.kpis(mensual, mes_sel)
    tablas_mes = {etiqueta: informe.tabla_dimension(tabla, mes_sel, args.umbral)
                  for etiqueta, tabla in tablas.items()}

    ancho = 100
    print("=" * ancho)
    print(f"INFORME EJECUTIVO DE VENTAS — {mes_sel:%B %Y}".upper())
    print(f"Fuente: {config.cargar().tabla} · datos hasta {fecha_max:%d/%m/%Y}")
    print("=" * ancho)

    def miles(valor) -> str:
        return f"{valor:,.0f}" if valor is not None and not pd.isna(valor) else "s/d"

    def pct(valor) -> str:
        return f"{valor:+,.1f}%" if valor is not None and not pd.isna(valor) else "s/d"

    print("\nCIFRAS DEL MES")
    print(f"  Venta .................. {miles(datos['venta']):>18}   ({pct(datos['var_mom'])} vs mes anterior, {pct(datos['var_yoy'])} interanual)")
    print(f"  Costo .................. {miles(datos['costo']):>18}")
    pp = datos["margen_pp_yoy"]
    texto_pp = "s/d" if pp is None or pd.isna(pp) else f"{pp:+.1f} puntos vs ano anterior"
    print(f"  Margen ................. {miles(datos['margen']):>18}   ({datos['margen_pct']:.1f}% sobre venta)")
    print(f"  Variacion de margen .... {texto_pp:>18}")
    print(f"  Unidades ............... {miles(datos['unidades']):>18}")
    print(f"  Lineas ................. {miles(datos['lineas']):>18}")
    print(f"  Ticket medio por linea . {miles(datos['ticket_medio']):>18}")
    print(f"  Acumulado del ano ...... {miles(datos['ytd_venta']):>18}   ({pct(datos['ytd_var'])} vs mismo tramo {mes_sel.year - 1})")

    print("\nLECTURA DEL MES")
    for frase in informe.lectura(datos, tablas_mes, args.umbral):
        print("  - " + frase.replace("**", ""))

    for etiqueta, tabla in tablas_mes.items():
        print(f"\n{etiqueta.upper()} — {mes_sel:%m/%Y}")
        if tabla.empty:
            print("  (sin datos)")
            continue
        columnas = ["Dimensión", "Venta", "Var MoM %", "Var YoY %", "Margen", "Margen %",
                    "Margen pp YoY", "Part. %", "Alerta"]
        vista = tabla[columnas].head(15).copy()
        for columna in ("Venta", "Margen"):
            vista[columna] = vista[columna].map(lambda v: f"{v:,.0f}")
        for columna in ("Var MoM %", "Var YoY %", "Margen pp YoY"):
            vista[columna] = vista[columna].map(
                lambda v: "s/d" if v is None or pd.isna(v) else f"{v:+,.1f}"
            )
        vista["Margen %"] = vista["Margen %"].map(lambda v: f"{v:,.1f}")
        vista["Part. %"] = vista["Part. %"].map(lambda v: f"{v:,.1f}")
        print(vista.to_string(index=False))

    if args.excel:
        salida = Path("out")
        salida.mkdir(exist_ok=True)
        destino = salida / f"informe_ejecutivo_{mes_sel:%Y_%m}.xlsx"
        hojas = {"Resumen": pd.DataFrame(datos.items(), columns=["Métrica", "Valor"])}
        hojas.update(tablas_mes)
        serie = mensual.copy()
        serie["Mes"] = pd.to_datetime(serie["Mes"])
        serie["Margen %"] = (serie["Margen"] / serie["Importe"].replace(0, pd.NA) * 100).round(2)
        hojas["Serie mensual"] = serie
        with pd.ExcelWriter(destino, engine="openpyxl") as escritor:
            for nombre, hoja in hojas.items():
                hoja.to_excel(escritor, index=False, sheet_name=str(nombre)[:31])
        print(f"\nExcel guardado en {destino}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
