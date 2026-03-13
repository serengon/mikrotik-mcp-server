# MikroTik MCP Server

MCP server para gestionar un MikroTik hAP ax² desde Claude Code via REST API nativa de RouterOS v7.

## Arquitectura

- **Framework**: Python + FastMCP (SDK oficial MCP)
- **Conexion**: REST API nativa de RouterOS v7 (HTTPS) via httpx async
- **Transporte MCP**: stdio (optimizado para Claude Code)
- **Testing**: Docker CHR (Linux) o Hyper-V CHR (Windows)

## Decisiones clave

- Solo REST API, sin fallback a puerto 8728 (ver ADR-001)
- Tools curados manualmente (~20-25), no generacion automatica desde OpenAPI
- Fase 1: solo lectura (12 tools). Escritura guiada por uso real
- Quirks de la REST API encapsulados en `RouterOSClient`

## Estructura del proyecto

```
src/mikrotik_mcp/
  server.py          # FastMCP entry point
  client.py          # RouterOSClient (httpx wrapper con manejo de quirks)
  types.py           # Modelos Pydantic
  config.py          # Configuracion desde env vars
  tools/
    reading.py       # Tools de solo lectura
    writing.py       # Tools de escritura (Fase 3)
tests/
docker/              # Docker CHR para testing (Linux)
docs/
  adr/               # Architecture Decision Records
  IMPLEMENTATION-PLAN.md
```

## Convenciones

- Linting: ruff
- Tests: pytest + pytest-asyncio
- Commits: conventional commits (feat:, fix:, docs:, etc.)
- Env vars para config: ROUTEROS_URL, ROUTEROS_USER, ROUTEROS_PASS, ROUTEROS_CA_CERT, ROUTEROS_VERIFY_SSL

## Quirks de la REST API a recordar

- Content-Type DEBE ser `application/json` exacto (sin charset=utf-8 o devuelve 415)
- Todos los valores JSON son strings (requieren conversion)
- Errores de permisos devuelven HTTP 500, no 403
- Timeout fijo de 60 segundos
- Crashes bajo carga paralela en hardware de gama baja
