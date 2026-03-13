# MikroTik MCP Server

MCP server para gestionar uno o múltiples MikroTik routers desde Claude Code via REST API nativa de RouterOS v7.

## Arquitectura

- **Framework**: Python + FastMCP (SDK oficial MCP)
- **Conexion**: REST API nativa de RouterOS v7 (HTTPS) via httpx async
- **Transporte MCP**: stdio (optimizado para Claude Code)
- **Testing**: Docker CHR (Linux) o Hyper-V CHR (Windows)

## Decisiones clave

- Solo REST API, sin fallback a puerto 8728 (ver ADR-001)
- RAG search + generic REST + list_routers (3 tools + 1 resource, 4607 endpoints) (ver ADR-002)
- Escritura guiada por uso real
- Quirks de la REST API encapsulados en `RouterOSClient`

## Estructura del proyecto

```
src/mikrotik_mcp/
  server.py            # FastMCP entry point (tools + resource registration)
  client.py            # RouterOSClient (httpx wrapper con manejo de quirks)
  router_registry.py   # RouterRegistry (multi-router client management)
  api_index.py         # OAS2 keyword search index (689 resources consolidados)
  types.py             # Modelos Pydantic
  config.py            # Configuracion desde env vars o routers.json
  tools/
    api_tools.py       # search_api + routeros_request + list_routers (3 tools)
    writing.py         # Tools de escritura (Fase futura)
  data/
    routeros-7.16-oas2.json  # OpenAPI 2.0 spec (4607 paths, 6.4MB)
tests/
gns3/                  # Scripts para GNS3 enterprise rack en mvp-server
docker/                # Docker CHR para testing (Linux)
docs/
  adr/                 # Architecture Decision Records
  IMPLEMENTATION-PLAN.md
```

## Convenciones

- Linting: ruff
- Tests: pytest + pytest-asyncio
- Commits: conventional commits (feat:, fix:, docs:, etc.)
- Env vars para config: ROUTEROS_URL, ROUTEROS_USER, ROUTEROS_PASSWORD, ROUTEROS_CA_CERT, ROUTEROS_VERIFY_SSL
- Multi-router: ROUTEROS_CONFIG apunta a routers.json, o colocar routers.json en CWD
- Fallback: sin ROUTEROS_CONFIG ni routers.json, usa env vars single-router con key "default"

## Quirks de la REST API a recordar

- Content-Type DEBE ser `application/json` exacto (sin charset=utf-8 o devuelve 415)
- Todos los valores JSON son strings (requieren conversion)
- Errores de permisos devuelven HTTP 500, no 403
- Timeout fijo de 60 segundos
- Crashes bajo carga paralela en hardware de gama baja
