# Software factory

Una software factory con agentes de IA que lleva el trabajo de la intención al producto en producción mediante una cadena determinista de etapas: entrada, spec, plan, implementar, verificar, integrar, desplegar y operar. Cada etapa tiene su oráculo y su puerta humana. Ningún LLM decide el flujo: los modelos ejecutan nodos y el código decide qué pasa después.

Los ejecutores son intercambiables (Claude Code, Codex CLI, OpenCode y mini-swe-agent) y van detrás de un contrato único y de un gateway LiteLLM con una key y un presupuesto por ejecución. Lo que se acepta lo decide un verificador separado del generador, que solo confía en los bytes del diff, con tests ocultos que el agente no ve y un diff-guard antitrampas.

El objetivo es L4 por etapa, tipo de trabajo y perfil, y se gana con datos: cada brazo (ejecutor × modelo) se mide sobre un conjunto fijo de tareas reales.

## Estado

Fase A (línea base) en curso: el núcleo de implementar y verificar está en `factory/`, y la matriz de brazos corre sobre 32 tareas públicas de SWE-rebench auditadas a ciegas. El roadmap y su estado están en [`docs/07-roadmap.md`](docs/07-roadmap.md).

## Por dónde empezar

- [`CLAUDE.md`](CLAUDE.md): mapa del repo, reglas y cómo se valida.
- [`docs/`](docs/): el diseño. Se lee en orden, de [`00-vision.md`](docs/00-vision.md) a [`10-rediseno-propuesta.md`](docs/10-rediseno-propuesta.md).
- [`docs/adr/`](docs/adr/): una decisión por fichero, con sus alternativas.
- [`docs/05-verification-design.md`](docs/05-verification-design.md): el modelo de amenazas y cómo se verifica un cambio.

```bash
make check   # lint, esquemas y tests
```

## Licencia

Apache-2.0. Ver [`LICENSE`](LICENSE).
