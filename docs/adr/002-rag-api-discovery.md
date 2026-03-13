# ADR-002: RAG-based API Discovery Instead of Curated Tools

## Status

Accepted

## Context

The original plan (ADR-001) called for ~20-25 manually curated MCP tools like
`list_interfaces()`, `get_arp_table()`, etc. However, the RouterOS REST API
exposes 4,607 endpoints. Curating 12-25 tools would cover only a fraction of
what the router can do, requiring constant additions as users discover new needs.

## Decision

Replace curated tools with a RAG (Retrieval-Augmented Generation) approach:

1. **`search_api(query)`** — keyword search over an in-memory index built from
   the RouterOS OpenAPI 2.0 spec. Returns matching endpoints with methods,
   parameters, and available actions.

2. **`routeros_request(method, path, params, body)`** — generic REST tool that
   executes any API call against the router, with path normalization and error
   handling.

3. **`router://api-groups` resource** — compact markdown map of all API groups,
   always available in context.

The OAS2 spec (from tikoci/restraml) is loaded once at startup. An `ApiIndex`
class filters scripting commands, consolidates CRUD actions, and provides
keyword scoring (~689 consolidated resources from 4,607 raw paths).

## Consequences

### Positive

- **Universal coverage**: all 4,607 endpoints accessible from day one
- **Zero maintenance**: new RouterOS versions just need an updated spec file
- **Natural language**: Claude searches like a user would ("firewall rules",
  "dhcp lease", "wifi clients")
- **Simpler codebase**: 2 tools + 1 resource vs 12-25 individual tools

### Negative

- **Less ergonomic**: no per-tool docstrings guiding Claude on specific use cases
- **Search quality**: keyword matching may miss non-obvious endpoints
- **Spec dependency**: relies on third-party OAS2 spec accuracy

### Mitigations

- Scoring weights path segments (+3 exact, +2 substring) over params (+1)
- Domain actions (make-static, monitor, etc.) preserved as separate entries
- Groups summary resource gives Claude an overview without searching
