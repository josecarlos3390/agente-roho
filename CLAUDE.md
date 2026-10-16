@AGENTS.md

## Notas específicas de Claude Code

- El servidor MCP del proyecto se declara en [.mcp.json](.mcp.json) con el nombre
  `agente-roho`. Claude Code lo detecta al abrir la carpeta y pide aprobación la
  primera vez.
- Si en tu equipo no está `uv`, cambia el comando del servidor al intérprete del
  entorno virtual:
  - Windows: `.venv\\Scripts\\python.exe`
  - macOS/Linux: `.venv/bin/python`
  y deja `args` como `["servidor_mcp.py"]`.
- Alternativa sin tocar archivos:
  `claude mcp add --transport stdio --scope project agente-roho -- uv run servidor_mcp.py`
