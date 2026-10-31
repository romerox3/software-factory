# 07 · Roadmap

> **Resumen.** Cuatro fases, cada una con un criterio de salida y un criterio de abandono medibles:
> - **F0**: harness, ~30 tareas minadas del piloto y la baseline de 5 brazos.
> - **F1**: verificador con holdouts y canarias, más pipeline issue→PR en borrador para C1.
> - **F2**: intensidad del harness por modelo (best-of-n, cascada, revisor de otro vendor) y modelos locales para las clases baratas.
> - **F3**: auto-merge por clase según el ADR-0008, condicionado sobre todo al volumen.
>
> El backlog de F0 son 20 tareas escritas como specs que se pueden despachar a un peón, sin decisiones de arquitectura pendientes. Todas las duraciones son estimaciones [Suposición].

## 1. Fases

### F0 · Harness y baseline

- **Objetivo**: medir los cinco brazos de [06](06-harness-and-tasks.md) §5 sobre ~30 tareas reales del piloto, con un verificador v0 aislado.
- **Duración estimada**: 4–6 semanas [Suposición].

| Tipo | Criterio | Cómo se mide |
|---|---|---|
| **Salida** | ≥ 30 tareas válidas no sintéticas: F2P no vacío, gold 3/3, base 3/3 en rojo y detector de fuga en verde | Inventario del almacén de tareas |
| **Salida** | ≥ 95 % de las 690 ejecuciones producen una salida de contrato válida contra el schema (los `error` de infraestructura se repiten hasta 2 veces) | `check-jsonschema` sobre `runs/` |
| **Salida** | Verificador reproducible: ≥ 99 % de veredictos idénticos al repetir 100 veredictos al azar | Script de reverificación |
| **Salida** | Concordancia del verificador con una persona ≥ 85 % (≥ 17 de 20 veredictos auditados) | Hoja de auditoría |
| **Salida** | Informe con pass@1, pass^k, M1 y M7a–c por brazo, con IC, y baseline humana de M4 calculada sobre 12 meses del piloto | `reports/f0-baseline.md` |
| **Abandono** | < 15 tareas válidas tras escanear todos los PRs elegibles de los 3 repos piloto → **cambiar de fuente** (repos OSS permisivos con PRs posteriores al corte de los modelos) antes de seguir | F0-05 + F0-17 |
| **Abandono** | El mejor brazo saca pass@1 < 15 % → **revisar el harness** (snapshot, prompt, red, entorno) con 5 tareas a mano antes de culpar al modelo. Si tras la revisión sigue < 15 %, las tareas son demasiado difíciles para F1 con C1 | Informe F0 |
| **Abandono** | Concordancia con la persona < 70 % tras 2 iteraciones del verificador → **la verificación automática no es viable en estos repos**: parar y replantear (tests insuficientes en el piloto) | Auditoría |

### F1 · Verificador completo y pipeline issue→PR en borrador (una clase: C1)

- **Objetivo**: los issues etiquetados `factory:C1` producen PRs en borrador verificados con holdouts, y las canarias miden la propensión a hacer trampa.
- **Duración estimada**: 6–10 semanas [Suposición].

| Tipo | Criterio | Cómo se mide |
|---|---|---|
| **Salida** | ≥ 20 PRs en borrador de C1 abiertos desde issues reales y revisados por personas | GitHub |
| **Salida** | M3 ≥ 50 % sobre esos 20 PRs | Diff entre lo verificado y lo fusionado |
| **Salida** | ≥ 150 ejecuciones de canaria por brazo habilitado, con cota superior al 95 % de M5 ≤ 10 % | Veredictos de canarias |
| **Salida** | La prueba `leak-holdout-path` falla siempre (0 lecturas de holdouts desde el generador) en cada versión | CI del harness |
| **Salida** | Mediana y p90 de M6 reportadas, revisión humana incluida | Eventos de GitHub |
| **Abandono** | M3 < 30 % tras 20 PRs → no pasar a F2. Revisar la calidad de los specs y si C1 es la clase adecuada | M3 |
| **Abandono** | Cota superior de M5 > 25 % en **todos** los brazos → ninguna autonomía con estos modelos; se mantiene la factory como generador de borradores | M5 |
| **Abandono** | El tiempo humano de revisión por PR iguala o supera el tiempo estimado de escribirlo a mano (encuesta a los revisores + M6) → parar: la factory no ahorra trabajo | Encuesta + M6 |

### F2 · Intensidad del harness por modelo y modelos locales

- **Objetivo**: elegir, **por modelo**, la estrategia (un intento, best-of-n, cascada de [ADR-0010](adr/0010-escalation-on-verified-failure.md) o reintento con motivo) que minimiza `M1.total` sin perder M2. Añadir un revisor de otro vendor como señal blanda y habilitar modelos locales para C4.
- **Duración estimada**: 6–8 semanas [Suposición].

| Tipo | Criterio | Cómo se mide |
|---|---|---|
| **Salida** | Sobre ≥ 50 tareas, al menos una variante mejora M3 en ≥ 10 puntos **o** reduce `M1.total` en ≥ 40 % con M2 no inferior en más de 5 puntos | Comparación pareada |
| **Salida** | Un brazo con modelo local en C4 con M2 a menos de 10 puntos del baseline y `M1.total` ≤ 30 % | M1, M2 |
| **Salida** | El juez de otro vendor concuerda con las personas en ≥ 75 % de una muestra de 30 | Auditoría |
| **Abandono** | Ninguna variante supera al intento único tras 2 iteraciones → se queda el intento único y se pasa a F3 con él | Comparación pareada |
| **Abandono** | El critic o el cross-check no se correlacionan con M2 (ρ < 0,3) → no se integran | Correlación |

### F3 · Auto-merge por clase

- **Objetivo**: que al menos una clase (previsiblemente C1 o C4) entre en auto-merge con el criterio de [ADR-0008](adr/0008-gates-and-auto-merge.md).
- **Duración**: depende del volumen de la clase. Con pocas decenas de PRs al mes, llegar a 150 cambios puede llevar 2–4 trimestres [Suposición].

| Tipo | Criterio | Cómo se mide |
|---|---|---|
| **Salida** | Una clase cumple las 6 condiciones del ADR-0008 y pasa 8 semanas en auto-merge sin que salte ninguna condición de salida | M3, M4, M5 y M7 |
| **Abandono** | Menos de 150 cambios de la clase en 6 meses → se mantiene el merge humano (la factory sigue siendo útil como generadora de borradores) | Volumen |
| **Abandono** | Dos salidas automáticas del modo en 3 meses → la clase vuelve a merge humano indefinidamente y se revisa el verificador | Eventos |

### Auto-mejora (todas las fases desde F0)

Todo PR que toque `prompts/`, `pipelines/`, `factory/adapters/`, `factory/verifier/` o la configuración de modelos ejecuta el conjunto congelado con el brazo afectado (M8, [01](01-metrics.md)). Se fusiona solo si pasa la regla de entrada de M8.

## 2. Backlog de F0

**Convenciones de despacho** (ver [CLAUDE.md](../CLAUDE.md)):
- **Peón**: OpenCode con GLM o DeepSeek a través del gateway, en un worktree aislado. Recibe la spec tal cual. Nunca recibe datos del almacén privado: se le dan fixtures públicos.
- **Sonnet**: piezas delicadas (verificador antitrampas, contrato de ejecutor, aislamiento). Como mucho 3 al día.
- **Orquestador**: Claude Code (este rol). Configuración, ejecuciones con datos privados, revisión e integración.
- **Humano**: el propietario.

Cada tarea se acepta cuando **su comando de aceptación termina con exit 0 en un checkout limpio** y el orquestador revisa el diff. Las rutas son del repo salvo que se diga otra cosa. El código va en `factory/` (Python 3.12, `uv`).

| ID | Tarea | Ficheros permitidos | Comando de aceptación | Criterio | No-objetivos | Depende de | Quién | Est. [Suposición] |
|---|---|---|---|---|---|---|---|---|
| **F0-01** | Esqueleto del proyecto Python: `pyproject.toml` (uv, ruff, pytest, check-jsonschema), `Makefile` con `check` (ruff + pytest + validación de schemas y ejemplos) | `pyproject.toml`, `Makefile`, `factory/__init__.py`, `tests/test_schemas.py` | `make check` | Los 9 ejemplos de `examples/executor/` validan y los 4 casos negativos de [04](04-executor-contract.md) §7 se rechazan en `tests/test_schemas.py` | Nada de lógica de la factory | — | Peón | 2 h |
| **F0-02** | Cliente del gateway: `mint(data_class, budget_usd, ttl)`, `spend(key)`, `revoke(key)` contra la API de LiteLLM (`/key/generate` con `team_id`, `/key/info`, `/key/delete`) | `factory/gateway/*.py`, `tests/gateway/*` | `make check` (tests con HTTP simulado mediante `respx` o `responses`) | Mapea `data_class` → `team_id` desde la configuración; nunca crea keys sin `max_budget`; falla de forma cerrada si la clase no existe | No configura el gateway real | F0-01 | Peón | 4 h |
| **F0-03** | Configurar el gateway real: equipos `factory-public`, `factory-client-product`, `factory-verifier`; alias de modelos (Sonnet, GLM con `use_chat_completions_api`, Qwen local); precios sombra > 0 con fuente | Configuración del gateway (fuera del repo) + `factory-pilot-data/gateway.md` | `uv run python -m factory.gateway.smoke` crea una key por equipo, llama a un modelo permitido y comprueba que uno no permitido da 401/403 | La matriz de [02](02-architecture.md) §8 se aplica de verdad | Ninguna instancia nueva salvo que la compartida choque | F0-02 | Orquestador + humano (claves) | 3 h |
| **F0-04** | Spike 1, parte B (B1–B6 de [spikes/01](../spikes/01-harbor-cc-codex/README.md)) | `spikes/01-harbor-cc-codex/` | El README se actualiza con el resultado de B1–B6 | Cierra el [ADR-0001](adr/0001-harness-runner.md) | — | F0-03 | Orquestador | 2 h |
| **F0-05** | Medir la elegibilidad del piloto: por repo, PRs fusionados en 18 meses, cuántos tocan tests según la heurística del paso 3, tamaño y clase estimada | `factory/miner/survey.py`, `tests/miner/test_survey.py` (sobre un repo fixture) | `make check`; después el orquestador lo ejecuta sobre el piloto y deja la tabla en `factory-pilot-data/` | Sale el número de PRs candidatos por repo y clase | No construye entornos | F0-01 | Peón (código) + orquestador (ejecución) | 4 h |
| **F0-06** | Builder de snapshot `fresh-init`: `git archive <base>` → repo nuevo con un commit, sin remotos ni tags | `factory/snapshot/*.py`, `tests/snapshot/*` | `make check`, con un test que crea un repo con un commit «futuro» que contiene un secreto y comprueba que `git log --all`, `git fsck --lost-found` y `git cat-file --batch-all-objects` no lo encuentran en el snapshot | Amenaza T15 cubierta | No es el sandbox | F0-01 | Peón + revisión del orquestador | 3 h |
| **F0-07** | Red del sandbox en la torre: red Docker `factory-egress` + reglas en `DOCKER-USER` (solo `IP:puerto` del gateway) + `network-probe` con Harbor | `infra/torre/egress.sh`, `spikes/01-…/tasks/network-probe` | En la torre: `network-probe` da reward 1 y un `curl` a GitHub desde el contenedor falla | T16 cubierta con evidencia | Sin Kubernetes ni microVM | F0-03 | Orquestador + humano (root en la torre) | 3 h |
| **F0-08** | Esquemas `factory.task.json` y `verifier.json`, y conversor `visible/` (OpenSpec) → tarea de Harbor sin `solution/` ni tests ocultos | `schemas/task.schema.json`, `schemas/verifier-task.schema.json`, `factory/tasks/to_harbor.py`, `tests/tasks/*` | `make check`, con un test de que el árbol de Harbor generado no contiene ningún fichero de `hidden/` | [ADR-0005](adr/0005-task-format.md) implementado | — | F0-01 | Peón | 4 h |
| **F0-09** | Parser de JUnit XML (pytest, jest-junit, vitest) → estados por test | `factory/junit.py`, `tests/junit/*` (con XML de ejemplo de los tres runners) | `make check` | Estados `passed`, `failed`, `error`, `skipped` por id de test estable entre runners | Sin parsers de texto | F0-01 | Peón | 3 h |
| **F0-10** | Minero, pasos 1–7 de [06](06-harness-and-tasks.md) §2: separación de parches, build en la base, 3 + 3 ejecuciones, derivación de F2P/P2P | `factory/miner/*.py`, `tests/miner/*` | `make check` con 2 PRs de un repo fixture (`fixtures/repos/py-calc` y `ts-calc`), de los que sale exactamente 1 tarea válida y 1 descartada por flaky | Los flaky se descartan; F2P vacío → descarte | No escribe specs | F0-06, F0-08, F0-09 | Peón (puede partirse en 10a/10b) | 1–2 días |
| **F0-11** | Repo fixture con trampas: `fixtures/repos/py-calc` y `ts-calc` + un diff de trampa por amenaza T01–T27 aplicable + una tarea factible + una canaria | `fixtures/**` | `make check` lista cada amenaza de [05](05-verification-design.md) con su fixture o con «proceso/fuera de alcance» | Cobertura 1:1 con la tabla de amenazas | Sin datos del piloto | F0-01 | Peón | 1 día |
| **F0-12** | Verificador v0: validación del parche, diff-guard, checkout limpio desde un mirror, P2P, F2P con parche oculto, `verdict.json` con hashes; mutation y SAST en modo informativo | `factory/verifier/**`, `tests/verifier/**` | `make check`: todas las fixtures de trampa de F0-11 dan `reject` o `cheat_suspected`, la tarea factible con el gold da `accept` y con un diff vacío da `reject` | Falla de forma cerrada ante cualquier error | Sin holdouts de escenario (F1), sin juez | F0-08, F0-09, F0-11 | **Sonnet** + revisión del orquestador | 2–3 días |
| **F0-13** | Adaptadores: configuración de los 4 agentes de Harbor (versiones fijadas, flags de [04](04-executor-contract.md)), prompt `base-v1`, detección de `abort.json` y escritor de la salida del contrato (diff, gasto del gateway, procedencia) | `factory/adapters/**`, `prompts/base-v1.md`, `tests/adapters/**` | `make check` + `harbor run -a oracle` sobre la tarea fixture produce un `run.json` válido contra el schema | Mapeo de `exit` de [04](04-executor-contract.md) §5 con tests por caso | Sin modelos reales en los tests | F0-02, F0-08 | **Sonnet** | 2 días |
| **F0-14** | Normalizador de los 4 formatos de trayectoria → `trajectory-event` | `factory/normalize/**`, `tests/normalize/**` (con trayectorias reales de F0-04 anonimizadas) | `make check`: cada evento valida contra el schema y el contador de «no mapeados» es 0 en las muestras | — | Sin OTel GenAI | F0-04, F0-01 | Peón | 1 día |
| **F0-15** | Métricas: M1 (gen y total), M2 (pass@1, pass^k), M7a–c, IC por bootstrap pareado e informe en `.md` y `.json` | `factory/metrics/**`, `tests/metrics/**` | `make check` con runs y veredictos sintéticos de resultado conocido | Las cifras coinciden con un cálculo a mano en el test | Sin dashboard | F0-01 | Peón | 1 día |
| **F0-16** | Baseline humana de M4: SZZ básico (PyDriller) sobre 12 meses de PRs humanos | `factory/metrics/szz.py`, `tests/metrics/test_szz.py` | `make check` con un repo fixture con un bug introducido y su fix; después el orquestador lo ejecuta sobre el piloto | La regresión del fixture se atribuye al commit correcto | — | F0-01 | Peón (código) + orquestador (ejecución) | 1 día |
| **F0-17** | Minar y revisar las tareas reales: ejecutar el minero sobre el piloto, generar los specs (paso 9) y el detector de fuga (paso 10); revisión humana de cada spec | `factory/miner/spec_*.py` (código, sobre fixtures) + datos en `factory-pilot-data/` | ≥ 30 tareas válidas en el almacén (criterio de salida de F0) | — | — | F0-05, F0-10, F0-12 | Peón (código) + orquestador + **humano (~10 min por tarea)** | 2–4 días |
| **F0-18** | Ejecutar la matriz: 30 tareas × 5 brazos × k (690 runs) con concurrencia por proveedor ([06](06-harness-and-tasks.md) §5) y verificación en Hetzner | `factory/run_matrix.py` + datos privados | Todos los runs tienen veredicto; ≥ 95 % de salidas válidas | Los 429 y caídas se reintentan y no cuentan como fallo del brazo | — | F0-12…F0-17, F0-07 | Orquestador | 2–3 días (pared) |
| **F0-19** | Auditoría humana de 20 veredictos al azar (estratificada: 10 `accept`, 10 `reject`/`cheat`) y reverificación de 100 | Hoja en `factory-pilot-data/` | Concordancia ≥ 85 % y reproducibilidad ≥ 99 % | — | — | F0-18 | Humano (~3 h) + orquestador | 1 día |
| **F0-20** | Informe de F0 y decisión de F1 (sigue, cambia de rumbo o para, según §1) + volcado a doc-rag | `reports/f0-baseline.md` (sin datos del piloto) | El hook de pre-commit pasa y el informe responde a cada criterio de salida y de abandono | — | — | F0-15, F0-16, F0-19 | Orquestador | 4 h |

**Camino crítico**: F0-01 → F0-02 → F0-03 → F0-04 → (F0-13, F0-14) y F0-01 → (F0-06, F0-08, F0-09, F0-11) → F0-10 → F0-12 → F0-17 → F0-18 → F0-19 → F0-20.

**Coste estimado de F0**:
- 2–3 subagentes Sonnet (F0-12, F0-13 y un posible rescate).
- Unos 15 despachos de peón.
- 90–270 USD de Anthropic para el brazo A1 más < 5 USD del spike [Suposición].
- ~1 jornada humana entre la revisión de specs y la auditoría.

## Decisiones abiertas

- Fecha de inicio de F0 y disponibilidad del propietario para las tareas humanas (F0-03, F0-07, F0-17, F0-19).
- Si F1 empieza con C1 o con C4 (más segura y con peor señal de valor), según los resultados de F0 por clase.
- Si F2 incluye OpenHands SDK como brazo adicional.
