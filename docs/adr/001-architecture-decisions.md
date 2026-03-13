# ADR-001: Decisiones de Arquitectura — MCP Server para MikroTik RouterOS

- **Estado**: Propuesto
- **Fecha**: 2026-03-13
- **Autor**: @andres + Claude Code
- **Contexto**: MCP server custom para gestionar un hAP ax² desde Claude Code via REST API nativa de RouterOS v7

---

## 1. Usar REST API nativa como unico canal de comunicacion

### Contexto
Existen 5+ MCP servers para MikroTik. Todos usan SSH o el protocolo propietario del puerto 8728. La REST API nativa (disponible desde RouterOS v7.1) no ha sido utilizada por ninguno.

La investigacion inicial proponia un esquema dual: REST API como primario + librouteros (puerto 8728) como fallback para streaming/monitor.

### Decision
**Solo REST API. Sin fallback a puerto 8728.**

### Justificacion
- Elimina una dependencia completa (`librouteros`) y un segundo vector de autenticacion.
- Para un home lab, no hay caso de uso real de streaming/monitor que justifique la complejidad adicional.
- HTTP es debuggeable con cualquier herramienta (curl, httpie, browser dev tools).
- JSON nativo elimina la necesidad de parsear formatos propietarios.
- Si en el futuro aparece un caso real que requiera 8728, se agrega en ese momento (YAGNI).

### Riesgos aceptados
- El timeout de 60 segundos de la REST API limita operaciones de larga duracion.
- No se puede hacer `monitor` en tiempo real (ej: traffic counters continuos).

---

## 2. Tools curados manualmente, no generacion automatica desde OpenAPI

### Contexto
El proyecto `tikoci/restraml` mapea ~6,000 endpoints de RouterOS via ingenieria inversa. Existen herramientas como `FastMCP.from_openapi()` y `openapi-to-mcp` que convierten specs OpenAPI en MCP servers automaticamente.

### Decision
**Curar manualmente un subconjunto de ~20-25 tools iniciales. Usar restraml solo como referencia para discovery de paths.**

### Justificacion
- FastMCP advierte explicitamente: "LLMs logran significativamente mejor rendimiento con MCP servers bien disenados que con servidores auto-convertidos desde OpenAPI".
- 6,000 tools saturarian el context window del LLM y degradarian la calidad del razonamiento.
- Tools curados permiten descripciones precisas, validacion especifica, y agrupacion logica.
- El spec de restraml tiene ~90% de precision, todos los params marcados como opcionales, y tipos genericos — insuficiente para generacion automatica confiable.

### Consecuencias
- Cada tool nuevo requiere implementacion manual.
- Se necesita consultar el RAML/HTML de restraml para descubrir paths y parametros exactos de endpoints nuevos.

---

## 3. Arrancar con tools de solo lectura (~12 tools en Fase 1)

### Contexto
La investigacion proponia ~60 tools en 7 categorias. Incluso 60 tools curados son muchos para un LLM.

### Decision
**Fase inicial: solo 12 tools de lectura. Las operaciones de escritura se agregan en Fase 2 guiadas por uso real.**

### Tools de Fase 1 (solo lectura)
1. `get_system_info` — CPU, RAM, uptime, version, modelo
2. `list_interfaces` — Todas las interfaces con estado y trafico
3. `list_vlans` — VLANs con IDs e interfaces padre
4. `list_dhcp_leases` — Dispositivos conectados por VLAN
5. `list_firewall_filter` — Reglas de filter
6. `list_firewall_nat` — Reglas NAT
7. `list_dns_static` — Entradas DNS estaticas
8. `get_arp_table` — Tabla ARP
9. `list_routes` — Tabla de routing
10. `list_wireless_clients` — Clientes WiFi conectados
11. `get_interface_traffic` — Estadisticas de trafico por interfaz
12. `run_cli_command` — Ejecutar comando CLI arbitrario de solo lectura (con whitelist)

### Justificacion
- Read-only elimina riesgo de romper la red durante desarrollo.
- Permite validar la arquitectura completa (auth, parsing, error handling) sin consecuencias.
- El uso real revelara que operaciones de escritura son realmente necesarias.
- 12 tools es un numero manejable para un LLM.

---

## 4. Backup por sesion, no por operacion

### Contexto
La investigacion proponia ejecutar `/system/backup/save` antes de cada operacion de escritura como guardrail de seguridad.

### Decision
**Un backup automatico al inicio de cada sesion de escritura + `/export` text antes de cambios criticos. No backup por cada operacion individual.**

### Justificacion
- `/system/backup/save` genera archivos binarios en el flash NAND del hAP ax². Multiples backups por sesion consumen almacenamiento limitado.
- Un backup al inicio de sesion cubre el rollback completo.
- `/export` genera texto plano (diff-friendly) y es instantaneo. Sirve como registro de estado pre-cambio sin consumir flash.
- Se implementa rotacion: maximo 5 backups automaticos, el mas viejo se elimina.

### Consecuencias
- Si se hacen 10 cambios en una sesion y el 7mo causa un problema, el rollback es al estado pre-sesion completo, no al cambio 6.
- Para rollback granular, se depende de los `/export` intermedios.

---

## 5. Manejo explicito de los quirks de la REST API

### Contexto
La REST API de RouterOS tiene bugs conocidos que afectan la implementacion.

### Decision
**Encapsular todos los quirks en una clase `RouterOSClient` que los maneje transparentemente.**

### Quirks a manejar

| Quirk | Impacto | Solucion en el cliente |
|-------|---------|----------------------|
| Content-Type solo acepta `application/json` exacto (sin charset) | Error 415 si se agrega `; charset=utf-8` | Header hardcodeado, sin dejar que httpx lo modifique |
| Todos los valores son strings JSON | `"true"`, `"1234"` en vez de `true`, `1234` | Capa de conversion automatica con type hints |
| Errores de permisos devuelven HTTP 500 | No se puede distinguir de errores reales | Parsear body del error y re-clasificar |
| Timeout de 60 segundos fijo | Operaciones largas fallan | Timeout en httpx a 55s + mensaje claro al usuario |
| Crashes bajo carga paralela | Router puede dejar de responder | Rate limiting: max 1 request concurrente, 100ms entre requests |
| SSL self-signed por defecto | `verify=False` es inseguro | Exportar cert del router y usarlo como CA custom |

### Consecuencias
- Toda la logica de quirks queda aislada en una clase.
- Los tools no necesitan saber sobre estos problemas.
- Se puede testear cada quirk individualmente.

---

## 6. Manejo de desconexion y resiliencia

### Contexto
La investigacion no cubria escenarios de desconexion: router reiniciandose, perdida de red, o servicio web crasheado.

### Decision
**Implementar health check, retry con backoff, y mensajes claros al usuario.**

### Mecanismo
- **Health check**: `GET /rest/system/resource` al inicio de cada interaccion. Si falla, informar al usuario antes de intentar cualquier operacion.
- **Retry**: Maximo 2 reintentos con backoff exponencial (1s, 3s) solo para operaciones de lectura. Las escrituras nunca se reintentan automaticamente (riesgo de duplicacion).
- **Circuit breaker**: Despues de 3 fallos consecutivos, marcar el router como "no disponible" y no intentar mas hasta que el usuario lo solicite.
- **Timeout por operacion**: 55 segundos (5s menos que el limite del router para evitar race conditions).

---

## 7. Resource MCP para contexto persistente del router

### Contexto
Cada vez que Claude necesita saber el estado basico del router, debe hacer una llamada a `get_system_info`. Esto consume tokens y agrega latencia.

### Decision
**Exponer un MCP Resource `router://status` que provea contexto basico automaticamente.**

### Contenido del resource
```
Router: MikroTik hAP ax² (RBD53IG-5HacD2HnD)
RouterOS: v7.16 (stable)
Uptime: 14d 3h 22m
CPU: 25% | RAM: 128/256 MB
Interfaces: 8 active / 12 total
DHCP Leases: 42 active
Last backup: 2026-03-13 08:00
```

### Justificacion
- Claude tiene contexto sin gastar una llamada a tool.
- Reduce friccion en conversaciones multi-turno.
- El resource se refresca cada 60 segundos o al inicio de conversacion.

---

## 8. Dry-run para operaciones de escritura

### Contexto
Las operaciones de escritura en un router de produccion son riesgosas. El usuario necesita poder revisar que va a pasar antes de confirmar.

### Decision
**Cada tool de escritura tiene un modo dry-run que muestra el comando CLI equivalente y el request HTTP que se enviaria, sin ejecutarlo.**

### Ejemplo
```
[DRY-RUN] Agregar regla de firewall:
  CLI equivalente: /ip/firewall/filter add chain=forward action=drop src-address=10.0.0.0/24 dst-address=192.168.1.0/24
  HTTP: PUT /rest/ip/firewall/filter
  Body: {"chain":"forward","action":"drop","src-address":"10.0.0.0/24","dst-address":"192.168.1.0/24"}

  Confirmar ejecucion? [El usuario decide via Claude Code]
```

### Justificacion
- El CLI equivalente es mas intuitivo para administradores MikroTik.
- El HTTP request permite debugging si algo falla.
- Se delega la confirmacion al flujo natural de Claude Code (human-in-the-loop).

---

## 9. Idempotencia en operaciones de escritura

### Contexto
Si se le pide a Claude "crear VLAN 100" y ya existe, no deberia duplicarla ni fallar silenciosamente.

### Decision
**Verificar existencia antes de crear. Reportar estado actual si el recurso ya existe con la configuracion solicitada.**

### Comportamiento
- **Crear recurso que no existe**: Se crea normalmente.
- **Crear recurso que ya existe con misma config**: Se reporta "VLAN 100 ya existe con la configuracion solicitada, no se realizaron cambios".
- **Crear recurso que ya existe con config diferente**: Se muestra diff y se pregunta si actualizar.

---

## 10. Certificado SSL del router en vez de verify=False

### Contexto
El esqueleto de codigo inicial usa `httpx.AsyncClient(verify=False)`, que deshabilita validacion SSL por completo.

### Decision
**Exportar el certificado self-signed del router y configurar httpx para usarlo como CA custom.**

### Implementacion
```python
# Fase 1 (desarrollo): verify=False con warning en logs
# Fase 2 (produccion):
client = httpx.AsyncClient(verify="/path/to/routeros-ca.crt", auth=auth)
```

### Justificacion
- `verify=False` es aceptable para desarrollo contra Docker CHR.
- Para el router real, el certificado exportado elimina riesgo de MITM sin necesitar una CA publica.
- La configuracion se pasa via variable de entorno `ROUTEROS_CA_CERT` (opcional, default a `verify=False` con warning).

---

## Stack tecnologico final

| Componente | Tecnologia | Justificacion |
|-----------|------------|---------------|
| Framework MCP | FastMCP (Python) | SDK oficial, tools desde type hints, transporte stdio nativo |
| HTTP client | httpx (async) | Async nativo, SSL configurable, timeouts granulares |
| Runtime | Python 3.11+ | Requerido por FastMCP, asyncio maduro |
| Testing | Docker CHR (EvilFreelancer) | RouterOS completo, todas las funcionalidades de software |
| MCP transport | stdio | Optimo para Claude Code, sin servidor HTTP adicional |
| Formato de config | Variables de entorno | Simple, seguro, compatible con Claude Code mcpServers |

---

## Fases revisadas

| Fase | Scope | Entregable |
|------|-------|-----------|
| 1 | Docker CHR + RouterOSClient + health check | Conexion validada con manejo de quirks |
| 2 | 12 tools de lectura + resource de status | MCP server funcional read-only en Claude Code |
| 3 | Tools de escritura con dry-run + idempotencia | Gestion de VLANs, firewall, DNS, DHCP |
| 4 | Testing contra hAP ax² real | Validacion en hardware de produccion |
| 5 | Refinamiento continuo | Tools segun uso real |
