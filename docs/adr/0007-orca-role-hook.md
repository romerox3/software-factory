# ADR-0007 · Relación con orca-role-hook

- **Estado**: aceptada (bloqueada por licencia para cualquier port) · **Fecha**: 2026-10-31

## Contexto

orca-role-hook es un kit de equipos de agentes sobre Orca con activos relevantes: oráculo con detección de trampas, cross-check, round log, procedencia, métricas y protocolo A/B. **No tiene licencia** (`gh api` → `license: null`, verificado el 2026-10-31) [Cierto].

Autoría de los activos candidatos (`git log` sobre upstream `72000c4`) [Cierto]:
- el oráculo: Felipe Castaño y el propietario;
- `metrics.sh`: solo el propietario;
- `agent.sh`: el único con commits firmados con el correo de Vicomtech y de otra organización.

Este repo será Apache-2.0.

## Opciones

1. **Extraer una librería compartida** que usen los dos repos: exige una licencia de orca-role-hook y coordinar dos proyectos.
2. **Portar código**: exige una licencia compatible con Apache-2.0 concedida por los autores.
3. **Reimplementar a partir de las ideas**: sin dependencia legal.

## Decisión

**Reimplementar a partir de las ideas** (opción 3). El verificador de este repo recibe un diff, no un worktree, y corre en otra máquina: su código sería distinto de todos modos. La tabla de [03](../03-reuse-inventory.md) §2 dice qué idea va a cada componente.

Excepción posible: `metrics.sh`, obra exclusiva del propietario, que él podría relicenciar si se decide portarlo.

## Consecuencias

- No se copia código ni prompts de orca-role-hook. Una revisión antes de cada commit lo comprueba (el hook de pre-commit no lo cubre).
- Las ideas reutilizadas se citan con el enlace al fichero y al commit `72000c4`.
- Si Felipe concede una licencia, se reconsidera portar `verify_task.py` (integridad), siempre que ahorre trabajo frente a la reimplementación.

## Cómo revertir

Con licencia, el port es una tarea del backlog que sustituye la reimplementación de una capa por el código portado, con atribución. Nada en la arquitectura depende de esta decisión.
