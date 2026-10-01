# Security policy

## Supported versions
The project is pre-1.0; only the latest release of each package (`agent-fabric`, `statistics`, `lakehouse`, `coworker`) receives fixes.

## Reporting a vulnerability
Please **do not open a public issue**. Use GitHub's private
[security advisory form](https://github.com/marcionicolau/spec-agents/security/advisories/new). You can expect an acknowledgement
within a few days.

## Scope notes
Areas that deserve extra care when reporting or reviewing:
- **Generated code**: `airflow_dag_render` / `dag_check` (lakehouse). Values are `pprint`-ed into a static template; SQL identifiers are validated and quoted.
- **Filesystem access**: the coworker pack only reads allowlisted roots (`COWORKER_ALLOWED_ROOTS`) and never writes to disk; paths go through `analysis.safe_path`.
- **LLM output**: model text must never become data or executable code outside declared `runtime: prompt` outputs.
- **Credentials** live in Airflow connections, never in params, URLs or generated files.
