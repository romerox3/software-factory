# ADR-0013 · La factory como capa de verificación y medición sobre Agent Swarm

- **Estado**: aceptada, condicionada a la prueba de la sección «Decisión» · **Fecha**: 2026-11-04 · **Pausa**: la parte de orquestación de [ADR-0002](0002-orchestrator.md) y de las fases B y C de [07](../07-roadmap.md)

## Contexto

La organización a la que esta factory quiere aportar va a adoptar [Agent Swarm](https://github.com/desplega-ai/agent-swarm) (desplega-ai, MIT) como plataforma en 1–2 semanas. Lo que trae, según su repositorio a 2026-11-04 [Cierto, `README.md`, `docs/orchestration-patterns.md`, `apps/evals/README.md`]:
- Entrada desde Slack, GitHub, Jira, Linear, email y API, con dashboard y memoria persistente.
- Dos modos de orquestación: un *lead agent* que decide a quién delega y un motor de workflows con grafo fijo, checkpoint por paso, reintentos, aprobaciones humanas y nodos `script` (bash, ts o python, tope de 300 s).
- Workers en Docker con Claude Code, Codex, OpenCode y otros. Claude Code admite un gateway LiteLLM con `ANTHROPIC_BASE_URL` (`guides/provider-auth/model-gateways.mdx`).
- Un harness de evals: matriz escenario × configuración, checks deterministas y jueces LLM, escenarios held-out, pass^k con IC y detección de regresiones. Corre en E2B y Turso con jueces de OpenRouter.

Lo que no trae, o no se ha visto:
- Verificar cada ticket en producción con código. Su nodo `validate` comprueba un JSON Schema o pide juicio a un LLM; no ejecuta tests [Cierto, `src/workflows/executors/validate.ts`].
- Tareas de código real en volumen: de los 14 escenarios de su suite 1.0, uno es un PR real; los demás miden coordinación [Cierto, snapshot del 2026-11-01].
- Una política de proveedores por clasificación de datos y un presupuesto por ejecución: la credencial va por worker [Probable].
- Aislamiento de red del worker: no verificado.

En la matriz de la fase A, el verificador rechaza el 33 % de las ejecuciones en que el agente declara haber terminado (134 de 410, en los cuatro brazos) [Cierto, recuento del 2026-11-04; pendiente de la auditoría F0-19]. Ese hueco no depende de la plataforma.

## Opciones

1. **Fork de Agent Swarm.** Control total. Con una versión casi diaria y la mayor parte de los commits de un bot [Cierto, API de GitHub], la deuda de fusión crece en semanas y obliga a mantener la plataforma entera [Probable].
2. **Agent Swarm como plataforma y esta factory como capa encima.** Versión fijada, Extensions y PRs upstream en lugar de fork.
3. **Seguir con la factory entera**, con runner, entrada y UI propios, al margen de la plataforma que se adopta.

## Decisión

**Opción 2**, condicionada a una prueba de un día en la torre: Agent Swarm sin túnel y con la telemetría apagada, 4–5 tareas de la fase A por un workflow, con el gateway y el verificador de esta factory. Criterios de corte:
1. La misma entrada al workflow, dos veces, recorre los mismos nodos.
2. Los workers pasan por el gateway LiteLLM con una virtual key.
3. La red del worker solo alcanza el gateway.
4. El verificador corre desde un nodo `script` o como servicio externo, con su sandbox separado del del worker.
5. Funciona con `--no-tunnel` y la telemetría apagada.

Si fallan el 2 o el 3, la plataforma queda bloqueada para código de clase `client-product` ([ADR-0009](0009-data-policy-per-repo.md)) aunque lo demás funcione.

**Se queda en esta factory**: el verificador (tests ocultos, diff-guard, aislamiento), las tareas con el minero y la revalidación, la matriz y las métricas, el gateway con política y fusible, y los oráculos de cada etapa: el escritor y el ejecutor de escenarios ocultos de la fase B.

**Se pausa**: el runner propio de [ADR-0002](0002-orchestrator.md), la entrada por tickets, la UI y el publicador de PRs.

## Consecuencias

- La fase A no cambia: sus datos dicen qué ejecutor y modelo poner en los workers y sirven de línea base para comparar «ejecutor directo» con «ejecutor dentro de Agent Swarm».
- En la fase B, el «frontend de la propia factory» deja de ser material: el dashboard lo da la plataforma. Hay que sustituirlo por otra app real.
- El harness de evals de Agent Swarm sirve para tareas públicas, no para código `client-product`, porque manda trayectorias a E2B, Turso y jueces de OpenRouter. Las tareas públicas de la fase A pueden convertirse a su formato de escenarios y proponerse upstream.
- Se depende de un proyecto con un mantenedor humano principal y versiones casi diarias: la versión se fija por digest de imagen (regla 6 de `CLAUDE.md`) y cada cambio de versión pasa por M8.
- Sigue abierto el hueco común: un ticket nuevo no trae tests ocultos. Resolverlo (fase B, B-03) es el trabajo de más valor de esta factory.

## Cómo revertir

Si la prueba falla un criterio de corte o la organización no adopta Agent Swarm, se reanuda [ADR-0002](0002-orchestrator.md) tal como está. Nada del código actual depende de esta decisión.
