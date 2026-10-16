"""Prueba de humo del servidor MCP por stdio.

Levanta servidor_mcp.py como lo haría un cliente (Claude Code, Codex, VS Code...),
hace el handshake, lista las herramientas y llama a un par de ellas, incluida una
consulta que DEBE ser rechazada por la política de solo lectura.

Ejecutar:  .venv\\Scripts\\python.exe verificar_mcp.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

fallos: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    print(("  OK   " if condicion else "  FALLO") + f"  {nombre}" + (f"  — {detalle}" if detalle else ""))
    if not condicion:
        fallos.append(nombre)


async def probar() -> None:
    parametros = StdioServerParameters(
        command=sys.executable,
        args=["servidor_mcp.py"],
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    async with stdio_client(parametros) as (lectura, escritura):
        async with ClientSession(lectura, escritura) as sesion:
            informacion = await sesion.initialize()
            # En el SDK v2 los campos pasaron de camelCase a snake_case.
            print(f"servidor: {informacion.server_info.name} {informacion.server_info.version}")

            catalogo = await sesion.list_tools()
            nombres = [h.name for h in catalogo.tools]
            print(f"herramientas ({len(nombres)}): {', '.join(nombres)}")
            esperadas = {
                "estado_conexion",
                "meses_disponibles",
                "informe_ejecutivo",
                "tabla_dimension",
                "serie_mensual",
                "buscar_articulos",
                "ejecutar_consulta",
            }
            check("expone las 7 herramientas", esperadas.issubset(set(nombres)), f"{len(nombres)} herramientas")

            descripciones = {h.name: (h.description or "") for h in catalogo.tools}
            check("las herramientas están descritas", all(descripciones[n].strip() for n in nombres))

            estado = await sesion.call_tool("estado_conexion", {})
            texto_estado = estado.content[0].text
            check(
                "estado_conexion responde",
                "Conexión: OK" in texto_estado,
                texto_estado.splitlines()[0][:90],
            )

            meses = await sesion.call_tool("meses_disponibles", {"meses_atras": 6})
            texto_meses = meses.content[0].text
            check("meses_disponibles responde", "-" in texto_meses, texto_meses[:70])

            informe = await sesion.call_tool("informe_ejecutivo", {})
            texto_informe = informe.content[0].text
            check(
                "informe_ejecutivo genera el informe",
                "Informe ejecutivo" in texto_informe and "Lectura del mes" in texto_informe,
                f"{len(texto_informe)} caracteres",
            )

            dimension = await sesion.call_tool(
                "tabla_dimension", {"dimension": "categoria", "mes": None}
            )
            check(
                "tabla_dimension acepta nombres sin acentos",
                "Dimensión desconocida" not in dimension.content[0].text,
                dimension.content[0].text.splitlines()[0][:70],
            )

            rechazo = await sesion.call_tool(
                "ejecutar_consulta", {"sql": "UPDATE dbo.Tabla SET Columna = 0"}
            )
            check(
                "rechaza una escritura",
                "rechazada" in rechazo.content[0].text.lower(),
                rechazo.content[0].text[:80],
            )

            rechazo2 = await sesion.call_tool(
                "ejecutar_consulta", {"sql": "SELECT 1; EXEC xp_cmdshell 'whoami'"}
            )
            check(
                "rechaza ejecución dinámica",
                "rechazada" in rechazo2.content[0].text.lower(),
                rechazo2.content[0].text[:80],
            )

            from src import config

            tabla = config.cargar().validar_tabla()
            permitida = await sesion.call_tool(
                "ejecutar_consulta",
                {"sql": f"SELECT COUNT_BIG(*) AS Filas FROM {tabla}", "max_filas": 5},
            )
            check(
                "permite una consulta de lectura",
                "Filas" in permitida.content[0].text,
                permitida.content[0].text.splitlines()[-1][:70],
            )


if __name__ == "__main__":
    print("\n[Prueba del servidor MCP por stdio]")
    try:
        asyncio.run(probar())
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        check("el servidor arranca y responde", False, f"{type(exc).__name__}: {exc}")

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s) -> {fallos}")
        sys.exit(1)
    print("RESULTADO: servidor MCP correcto")
