# Plan de Implementacion — MikroTik MCP Server

> Referencia: [ADR-001](adr/001-architecture-decisions.md) para justificacion de cada decision.

---

## Fase 1: Entorno de desarrollo y cliente base

### Objetivo
Conexion validada contra Docker CHR con manejo completo de quirks de la REST API.

### Tareas

#### 1.1 Scaffolding del proyecto
- [ ] Inicializar repositorio git
- [ ] Crear `pyproject.toml` con dependencias: `mcp[cli]`, `httpx`, `pydantic`
- [ ] Estructura de directorios:
  ```
  mikrotik-mcp-server/
    src/
      mikrotik_mcp/
        __init__.py
        server.py          # FastMCP entry point
        client.py           # RouterOSClient (httpx wrapper)
        types.py            # Modelos Pydantic para respuestas
        tools/
          __init__.py
          reading.py        # Tools de lectura
          writing.py        # Tools de escritura (Fase 3)
        config.py           # Configuracion desde env vars
    tests/
      conftest.py           # Fixtures: mock router, Docker CHR
      test_client.py        # Tests del RouterOSClient
      test_tools_reading.py # Tests de tools de lectura
    docker/
      docker-compose.yml    # Docker CHR para testing
    docs/
      adr/
        001-architecture-decisions.md
      IMPLEMENTATION-PLAN.md
  ```
- [ ] Configurar ruff para linting y formatting

#### 1.2 Docker CHR
- [ ] Crear `docker-compose.yml`:
  ```yaml
  services:
    routeros:
      image: evilfreelancer/docker-routeros:7.16
      ports:
        - "8443:443"   # REST API HTTPS
        - "8080:80"    # REST API HTTP
        - "2222:22"    # SSH (debug)
        - "5900:5900"  # VNC (debug)
      cap_add:
        - NET_ADMIN
      devices:
        - /dev/net/tun
        - /dev/kvm     # Disponible en Linux nativo
      environment:
        - ROUTEROS_VERSION=7.16
  ```
  > **Nota**: El desarrollo se hace en Ubuntu (Linux nativo) donde Docker CHR
  > funciona con KVM y /dev/net/tun sin problemas. En Windows usar Hyper-V CHR.
- [ ] Verificar arranque (30-60s) y conectividad REST
- [ ] Configurar usuario `mcp-agent` con grupo de permisos limitados
- [ ] Habilitar REST API (viene con webfig por defecto)
- [ ] Documentar pasos de setup en un README dentro de `docker/`

#### 1.3 RouterOSClient
- [ ] Clase async sobre httpx que encapsula todos los quirks:
  - Header `Content-Type: application/json` exacto (sin charset)
  - Conversion automatica de strings a tipos Python (bool, int, float)
  - Reclasificacion de HTTP 500 cuando es error de permisos
  - Timeout de 55 segundos por request
  - Rate limiting: max 1 request concurrente, 100ms entre requests
  - `verify=False` con warning en logs (dev), cert custom via env var (prod)
- [ ] Health check: `GET /rest/system/resource`
- [ ] Retry con backoff exponencial (1s, 3s) solo para lecturas
- [ ] Circuit breaker: 3 fallos consecutivos -> router marcado como no disponible
- [ ] Logging estructurado de cada request/response

#### 1.4 Validacion
- [ ] Test manual: curl contra Docker CHR para confirmar endpoints
- [ ] Test automatizado: RouterOSClient conecta, health check pasa, obtiene system/resource
- [ ] Verificar cada quirk documentado (Content-Type, strings, timeout)

### Entregable
`RouterOSClient` testeado contra Docker CHR, listo para que los tools lo consuman.

---

## Fase 2: Tools de lectura + Resource de status

### Objetivo
MCP server funcional read-only, usable desde Claude Code via stdio.

### Tareas

#### 2.1 Resource MCP de status
- [ ] Implementar resource `router://status` que expone:
  ```
  Router: MikroTik [modelo]
  RouterOS: v[version] ([channel])
  Uptime: [uptime]
  CPU: [cpu-load]% | RAM: [free-memory]/[total-memory]
  Interfaces: [active] active / [total] total
  DHCP Leases: [active] active
  ```
- [ ] Refresh cada 60 segundos o al inicio de conversacion
- [ ] Fallback graceful si el router no responde

#### 2.2 Tools de lectura (12 tools)

Cada tool debe tener:
- Docstring clara y concisa (esto es lo que Claude lee para decidir cuando usarlo)
- Type hints completos en parametros y retorno
- Manejo de errores que devuelva mensajes utiles, no stack traces
- Formato de respuesta consistente (JSON con campos relevantes)

| # | Tool | Endpoint REST | Notas |
|---|------|--------------|-------|
| 1 | `get_system_info` | `GET /rest/system/resource` | CPU, RAM, uptime, version, board |
| 2 | `list_interfaces` | `GET /rest/interface` | Filtrar campos: name, type, running, rx/tx bytes |
| 3 | `list_vlans` | `GET /rest/interface/vlan` | ID, nombre, interfaz padre, running |
| 4 | `list_dhcp_leases` | `GET /rest/ip/dhcp-server/lease` | IP, MAC, hostname, status, interfaz |
| 5 | `list_firewall_filter` | `GET /rest/ip/firewall/filter` | Chain, action, src/dst, comment, disabled |
| 6 | `list_firewall_nat` | `GET /rest/ip/firewall/nat` | Chain, action, to-addresses, to-ports |
| 7 | `list_dns_static` | `GET /rest/ip/dns/static` | Name, address, TTL |
| 8 | `get_arp_table` | `GET /rest/ip/arp` | IP, MAC, interface, dynamic/static |
| 9 | `list_routes` | `GET /rest/ip/route` | Dst, gateway, distance, routing-table |
| 10 | `list_wireless_clients` | `GET /rest/interface/wifiwave2/registration-table` | MAC, signal, tx/rx rate, uptime. Fallback a `/interface/wireless/registration-table` si wifiwave2 no existe |
| 11 | `get_interface_traffic` | `GET /rest/interface` + filtro por nombre | rx-byte, tx-byte, rate. Parametro: interface name |
| 12 | `get_dhcp_network_map` | Combina: leases + ARP + DNS static | Vista consolidada de dispositivos en la red |

Nota sobre `get_dhcp_network_map`: este es el tool mas util para un home lab. Combina datos de 3 endpoints para dar una vista unificada de "que hay en mi red". Ejemplo de output:
```json
[
  {
    "ip": "10.0.10.15",
    "mac": "AA:BB:CC:DD:EE:FF",
    "hostname": "iphone-andres",
    "dns_name": "iphone.lan",
    "vlan": "VLAN10-Personal",
    "interface": "bridge1",
    "status": "bound",
    "last_seen": "2m ago"
  }
]
```

#### 2.3 Server entry point
- [ ] `server.py` con FastMCP configurado:
  - Nombre: `mikrotik-router`
  - Transporte: stdio
  - Instructions para el LLM sobre cuando usar cada tool
- [ ] Configuracion via env vars:
  - `ROUTEROS_URL` (requerido)
  - `ROUTEROS_USER` (requerido)
  - `ROUTEROS_PASS` (requerido)
  - `ROUTEROS_CA_CERT` (opcional, path al certificado)
  - `ROUTEROS_VERIFY_SSL` (opcional, default `true`, `false` para dev)

#### 2.4 Integracion con Claude Code
- [ ] Configurar en `~/.claude.json` o en settings del proyecto:
  ```json
  {
    "mcpServers": {
      "mikrotik": {
        "command": "python",
        "args": ["-m", "mikrotik_mcp.server"],
        "env": {
          "ROUTEROS_URL": "https://192.168.88.1/rest",
          "ROUTEROS_USER": "mcp-agent",
          "ROUTEROS_PASS": "...",
          "ROUTEROS_VERIFY_SSL": "false"
        }
      }
    }
  }
  ```
- [ ] Verificar que Claude Code lista los 12 tools + 1 resource
- [ ] Test conversacional: "que dispositivos hay en mi red?", "mostrame las VLANs", "como esta el router?"

#### 2.5 Tests
- [ ] Tests unitarios con respuestas mockeadas (sin Docker)
- [ ] Tests de integracion contra Docker CHR
- [ ] Fixture de pytest que levanta/baja Docker CHR automaticamente (o usa uno existente)

### Entregable
MCP server instalable que funciona en Claude Code. 12 tools de lectura + 1 resource. Testeado contra Docker CHR.

---

## Fase 3: Tools de escritura con guardrails

### Objetivo
Gestion de VLANs, firewall, DNS, DHCP con dry-run, idempotencia, y backup por sesion.

### Tareas

#### 3.1 Infraestructura de escritura
- [ ] Backup automatico al inicio de sesion de escritura:
  - `POST /rest/system/backup/save` con nombre `mcp-auto-YYYYMMDD-HHmmss`
  - Rotacion: mantener max 5 backups automaticos
  - `/system/backup` para listar y `/tool/fetch` para descargar si se necesita
- [ ] Modo dry-run en cada tool de escritura:
  - Parametro `dry_run: bool = True` (default seguro)
  - Retorna CLI equivalente + HTTP request que se enviaria
  - No ejecuta nada contra el router
- [ ] Verificacion de idempotencia:
  - Antes de crear: verificar si ya existe con misma config
  - Si existe igual: reportar "sin cambios"
  - Si existe diferente: mostrar diff y pedir confirmacion
- [ ] `/export` text antes de cada cambio critico (firewall, routing)

#### 3.2 Tools de escritura

| # | Tool | Operacion | Endpoint REST | Riesgo |
|---|------|-----------|--------------|--------|
| 1 | `create_vlan` | PUT | `/rest/interface/vlan` | Medio |
| 2 | `update_vlan` | PATCH | `/rest/interface/vlan/{id}` | Medio |
| 3 | `delete_vlan` | DELETE | `/rest/interface/vlan/{id}` | Alto |
| 4 | `add_firewall_rule` | PUT | `/rest/ip/firewall/filter` | Alto |
| 5 | `toggle_firewall_rule` | PATCH | `/rest/ip/firewall/filter/{id}` | Alto |
| 6 | `add_nat_rule` | PUT | `/rest/ip/firewall/nat` | Alto |
| 7 | `add_dns_entry` | PUT | `/rest/ip/dns/static` | Bajo |
| 8 | `remove_dns_entry` | DELETE | `/rest/ip/dns/static/{id}` | Bajo |
| 9 | `add_dhcp_reservation` | PUT | `/rest/ip/dhcp-server/lease` | Bajo |
| 10 | `set_interface_comment` | PATCH | `/rest/interface/{id}` | Bajo |

#### 3.3 Validaciones por tool

- **VLANs**: ID entre 1-4094, interfaz padre debe existir, no duplicar ID
- **Firewall**: no bloquear subnet de management, no bloquear puerto de la REST API, chain valido (input/forward/output)
- **NAT**: to-addresses debe ser IP valida, to-ports entre 1-65535
- **DNS**: formato de hostname valido, IP valida
- **DHCP**: MAC en formato correcto, IP dentro del pool configurado

#### 3.4 Operaciones bloqueadas (nunca exponer como tools)
- `/system/reset-configuration` — factory reset
- `/system/routerboard/upgrade` — firmware upgrade
- `/user/*` — gestion de usuarios/credenciales
- `/system/license/*` — licenciamiento
- `/interface/*/remove` donde la interfaz sea la de management
- `/ip/address/remove` donde la IP sea la de acceso API

#### 3.5 Tests
- [ ] Test de dry-run: verificar que no se ejecuta nada
- [ ] Test de idempotencia: crear, re-crear, verificar sin duplicacion
- [ ] Test de validacion: inputs invalidos rechazados con mensaje claro
- [ ] Test de backup: verificar que se crea antes de primer cambio
- [ ] Test contra Docker CHR: ciclo completo create/read/update/delete

### Entregable
10 tools de escritura con dry-run, idempotencia, validacion, y backup automatico.

---

## Fase 4: Testing contra hAP ax² real

### Objetivo
Validar que todo funciona en hardware de produccion con configuracion real.

### Tareas

#### 4.1 Preparacion del router
- [ ] Crear usuario `mcp-agent` con grupo custom:
  ```
  /user group add name=mcp-api policy=read,write,api,rest-api,!ftp,!ssh,!reboot,!policy,!sensitive
  /user add name=mcp-agent group=mcp-api password=...
  ```
- [ ] Exportar certificado SSL del router
- [ ] Configurar `ROUTEROS_CA_CERT` con el certificado exportado
- [ ] Verificar conectividad REST desde la maquina de desarrollo

#### 4.2 Validacion de tools de lectura
- [ ] Comparar output de cada tool contra la consola real del router
- [ ] Verificar que `list_wireless_clients` funciona con wifiwave2 del hAP ax²
- [ ] Verificar que `get_dhcp_network_map` muestra los ~40 dispositivos correctamente
- [ ] Medir latencia de cada tool (objetivo: <2s por operacion)

#### 4.3 Validacion de tools de escritura
- [ ] Crear VLAN de prueba, verificar en consola, eliminar
- [ ] Agregar regla de firewall de prueba, verificar, eliminar
- [ ] Agregar entrada DNS de prueba, verificar, eliminar
- [ ] Verificar que el backup automatico funciona
- [ ] Verificar que dry-run muestra el comando correcto

#### 4.4 Stress test liviano
- [ ] 100 operaciones de lectura secuenciales — verificar estabilidad
- [ ] 10 operaciones de escritura secuenciales — verificar que no se acumulan errores
- [ ] Verificar consumo de CPU/RAM del router durante uso normal del MCP

#### 4.5 Edge cases del hardware
- [ ] Comportamiento cuando WiFi esta ocupado (muchos clientes)
- [ ] Respuesta cuando una interfaz esta down
- [ ] Manejo de VLANs en el switch chip real (vs bridge en CHR)
- [ ] Campos adicionales en respuestas del hardware real vs CHR

### Entregable
MCP server validado contra hardware real. Lista de ajustes necesarios documentada.

---

## Fase 5: Refinamiento continuo

### Objetivo
Mejorar basado en uso real. Esta fase no tiene fin definido.

### Actividades recurrentes
- [ ] Agregar tools segun necesidad (no especulativamente)
- [ ] Refinar docstrings de tools para mejorar la seleccion del LLM
- [ ] Ajustar formato de respuestas segun lo que Claude interpreta mejor
- [ ] Agregar prompts MCP (templates de conversacion para tareas comunes)
- [ ] Considerar tools de diagnostico: ping, traceroute, bandwidth-test
- [ ] Considerar integracion con Grafana/Prometheus para metricas historicas
- [ ] Publicar en PyPI si el servidor madura lo suficiente

### Metricas de exito
- Claude puede responder "que hay en mi red?" en <5 segundos
- Claude puede crear una VLAN completa (interfaz + IP + DHCP + firewall) en una conversacion
- Zero incidentes de red causados por el MCP server en 30 dias de uso

---

## Dependencias y versiones

| Dependencia | Version minima | Motivo |
|------------|---------------|--------|
| Python | 3.11+ | Requerido por FastMCP, asyncio.TaskGroup |
| mcp[cli] | 1.x | SDK oficial con FastMCP |
| httpx | 0.27+ | Async HTTP client |
| pydantic | 2.x | Validacion de config y respuestas |
| RouterOS | 7.12+ | Fix de CVE-2023-41570, REST API estable |
| Docker | 24+ | Para Docker CHR de testing |

## Referencias

- [tikoci/restraml](https://github.com/tikoci/restraml) — Esquemas API de RouterOS
- [EvilFreelancer/docker-routeros](https://github.com/EvilFreelancer/docker-routeros) — Docker CHR
- [FastMCP docs](https://gofastmcp.com) — Framework MCP para Python
- [RouterOS REST API docs](https://help.mikrotik.com/docs/display/ROS/REST+API) — Documentacion oficial
- [jeff-nasseri/mikrotik-mcp](https://github.com/jeff-nasseri/mikrotik-mcp) — MCP server existente mas maduro (referencia)
