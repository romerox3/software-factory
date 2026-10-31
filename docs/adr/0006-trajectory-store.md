# ADR-0006 · Almacén de trayectorias: JSONL crudo frente a CXDB

- **Estado**: aceptada · **Fecha**: 2026-10-31

## Contexto

Ningún CLI garantiza estabilidad de su formato de eventos [Probable]. Las trayectorias sirven para diagnosticar coste (M1), buscar patrones de trampa (M5) y, en el futuro, hacer replay. CXDB (Apache-2.0) guarda turnos en un DAG con content-addressing y ramificación, pero no tiene releases, su último push es del 2026-08-28 y el propietario fue adquirido [Cierto/Probable, [03](../03-reuse-inventory.md)].

## Decisión

**JSONL crudo** (lo que emite cada CLI, sin tocar) + **JSONL normalizado** ([`trajectory-event.schema.json`](../../schemas/trajectory-event.schema.json)), en disco con `rsync` hacia Hetzner. Las trayectorias del piloto van en el almacén privado. Sin base de datos de trayectorias en F0 ni en F1.

## Consecuencias

- El análisis se hace con scripts sobre JSONL (`jq`, Python).
- Si la búsqueda o el clustering se vuelve un cuello de botella (por ejemplo, al revisar trayectorias de canarias en F1), Docent entra como piloto **leyendo los mismos ficheros**.
- Se guarda siempre el crudo: un cambio de formato del CLI rompe el normalizador, no los datos.

## Cómo revertir

CXDB, o cualquier almacén, se puede poblar después desde el JSONL crudo. `cxtx` de CXDB captura sesiones de `claude` y `codex` [Cierto según el informe], así que se podría adoptar sin cambiar los adaptadores.
