# 07 · Roadmap

> **Resumen.** Cuatro fases, cada una con un criterio de salida y un criterio de abandono medibles:
> - **F0**: harness, ~30 tareas públicas recientes (Python y TS) y la baseline de 6 brazos. Sin datos del cliente.
> - **F1**: verificador con holdouts y canarias, más pipeline issue→PR en borrador para C1 **sobre el piloto**.
> - **F2**: intensidad del harness por modelo (best-of-n, cascada, revisor de otro vendor) y modelos locales para las clases baratas.
> - **F3**: auto-merge por clase según el ADR-0008, condicionado sobre todo al volumen.
>
> El backlog de F0 son 21 tareas que se pueden despachar sin decisiones de arquitectura pendientes, cada una con un comando de aceptación. Todas las duraciones son estimaciones [Suposición].

## 1. Fases

### F0 · Harness y baseline

- **Objetivo**: medir los seis brazos de [06](06-harness-and-tasks.md) §5 sobre ~30 tareas públicas posteriores al corte de los modelos ([06](06-harness-and-tasks.md) §2.1), con un verificador v0 aislado. F0 no usa código del piloto, salvo el historial git para la baseline de M4 (F0-16), que se calcula en local sin pasar por ningún proveedor.
- **Duración estimada**: 4–6 semanas [Suposición].

| Tipo | Criterio | Cómo se mide |
|---|---|---|
| **Salida** | ≥ 30 tareas públicas revalidadas en nuestro entorno, no sintéticas y posteriores al corte único de [06](06-harness-and-tasks.md) §3: F2P no vacío, gold 3/3, base 3/3 en rojo y detector de fuga en verde. Al menos 8 son TS | Inventario del almacén de tareas |
| **Salida** (salud del harness, no calidad) | ≥ 95 % de las 840 ejecuciones producen una salida de contrato válida contra el schema y la tasa final de `error_infra` es ≤ 5 % (cada `error_infra` se repite hasta 2 veces) | `check-jsonschema` sobre `runs/` |
| **Salida** | Verificador reproducible: ≥ 99 % de veredictos idénticos al repetir 100 veredictos al azar | Script de reverificación |
| **Salida** | **Falsos `accept`**: en una auditoría humana de 30 veredictos `accept` elegidos al azar, ≤ 1 es incorrecto (cota superior al 95 % ≈ 15 %), y la concordancia en 10 `reject`/`cheat_suspected` es ≥ 9 de 10 | Hoja de auditoría |
| **Salida** | Informe con pass@1, pass^k, M1 y M7a–c por brazo, con IC, y baseline humana de M4 calculada sobre 12 meses del piloto | `reports/f0-baseline.md` |
| **Zona intermedia** | Entre 15 y 29 tareas posteriores al corte → se completa con el split `js` de MultiLang y con los splits mensuales que se vayan publicando. Si en 4 semanas sigue < 30, F0 continúa con las que haya y el informe declara el efecto mínimo detectable con ese n (`power_sim.py`) | F0-17 |
| **Abandono** | < 15 tareas posteriores al corte → **los datasets públicos no sirven para estos modelos**: se pasa a minar el piloto con la receta de [06](06-harness-and-tasks.md) §2.2, lo que exige confirmar antes S3 y S4 | F0-17 |
| **Abandono** | El mejor brazo saca pass@1 < 15 % → **revisar el harness** (snapshot, prompt, red, entorno) con 5 tareas a mano antes de culpar al modelo. Si tras la revisión sigue < 15 %, las tareas son demasiado difíciles para F1 con C1 | Informe F0 |
| **Zona intermedia** | 2 o 3 falsos `accept` de 30 → una iteración del verificador y una auditoría nueva de 30 `accept` distintos | Auditoría |
| **Abandono** | ≥ 4 falsos `accept` de 30 tras 2 iteraciones del verificador → **la verificación automática no es viable en estos repos**: parar y replantear (tests insuficientes en el piloto) | Auditoría |

### F1 · Verificador completo y pipeline issue→PR en borrador (una clase: C1)

- **Objetivo**: los issues etiquetados `factory:C1` **del piloto** producen PRs en borrador verificados con holdouts, y las canarias miden la propensión a hacer trampa.
- **Requisito de entrada**: S3 y S4 están confirmados por el propietario desde el 2026-11-01 ([09](09-open-questions.md)). El verificador de Hetzner tiene que tener ya el mirror de los repos piloto, con Docker rootless y un volumen que no vean los demás servicios del host ([02](02-architecture.md) §2). Si no se puede, el verificador pasa a otra máquina antes de que entre código del cliente.
- **Duración estimada**: 6–10 semanas [Suposición].

| Tipo | Criterio | Cómo se mide |
|---|---|---|
| **Salida** | ≥ 20 PRs en borrador de C1 abiertos desde issues reales y revisados por personas | GitHub |
| **Salida** | M3 ≥ 50 % sobre esos 20 PRs | Diff entre lo verificado y lo fusionado |
| **Salida** | ≥ 30 **tareas-canaria distintas** (construidas a partir de tareas públicas, sin datos del cliente), en lotes dedicados fuera del flujo de PRs, en el brazo de F1, con cota superior al 95 % de M5 ≤ 10 % (0 trampas en 30). Coste de A1: 30–90 USD [Suposición] | Veredictos de canarias |
| **Salida** | La prueba `leak-holdout-path` falla siempre (0 lecturas de holdouts desde el generador) en cada versión | CI del harness |
| **Salida** | Mediana y p90 de M6 reportadas, revisión humana incluida | Eventos de GitHub |
| **Zona intermedia** | M3 entre 30 y 50 % tras 20 PRs → se revisan los specs y se abren 10 PRs más. Si M3 sigue < 50 % sobre los 30, se aplica el abandono | M3 |
| **Abandono** | M3 < 30 % tras 20 PRs (o < 50 % tras 30) → no pasar a F2. Revisar la calidad de los specs y si C1 es la clase adecuada | M3 |
| **Abandono** | Cota superior de M5 > 25 % en **todos** los brazos → ninguna autonomía con estos modelos; se mantiene la factory como generador de borradores | M5 |
| **Abandono** | La mediana del tiempo de revisión por PR ≥ la mediana del tiempo estimado de hacerlo a mano → parar: la factory no ahorra trabajo | **Formulario de revisión**: al cerrar cada PR de la factory, el revisor deja un comentario con la plantilla `review-minutes: N` y `manual-estimate-minutes: M`, que se exporta a `prs/*.jsonl`. Un PR sin formulario no cuenta, y si faltan en > 20 % de los PRs el criterio queda «sin dato» y se pregunta al propietario |

### F2 · Intensidad del harness por modelo y modelos locales

- **Objetivo**: elegir, **por modelo**, la estrategia (un intento, best-of-n, cascada de [ADR-0010](adr/0010-escalation-on-verified-failure.md) o reintento con motivo) que minimiza `M1.total` sin perder M2. Añadir un revisor de otro vendor como señal blanda y habilitar modelos locales para C4.
- **Duración estimada**: 6–8 semanas [Suposición].

| Tipo | Criterio | Cómo se mide |
|---|---|---|
| **Salida** | Sobre ≥ 50 tareas con k = 5 (o ≥ 80 con k = 3), al menos una variante cumple la regla única de coste de [01](01-metrics.md) M1: `M1.total` ≤ 50 % del intento único y M2 no inferior con Δ = 10 puntos | Comparación pareada |
| **Salida** | Un brazo con modelo local en C4 cumple la misma regla frente al baseline, sobre ≥ 8 tareas C4 minadas con la receta de `K_gold` ([06](06-harness-and-tasks.md) §4) | M1, M2 |
| **Salida** | El juez de otro vendor concuerda con las personas en ≥ 75 % de una muestra de 30 ([05](05-verification-design.md)) | Auditoría |
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

Todo PR que toque `prompts/`, `pipelines/`, `factory/adapters/`, `factory/verifier/` o la configuración de modelos ejecuta el conjunto congelado con el brazo afectado (M8, [01](01-metrics.md)). Se fusiona solo si pasa la regla de no-inferioridad de M8. **Arranque**: en F0 aún no hay congelado. F0-12 y F0-13 se aceptan con su comando y la revisión del orquestador, y M8 rige desde que F0-18 fija el congelado v1 y la versión 0.0.

## 2. Backlog de F0

**Convenciones de despacho** (ver [CLAUDE.md](../CLAUDE.md)):
- **Peón**: OpenCode con GLM o DeepSeek a través del gateway, en un worktree aislado. Recibe la spec tal cual. Nunca recibe datos del almacén privado: se le dan fixtures públicos.
- **Sonnet**: piezas delicadas (verificador antitrampas, contrato de ejecutor, aislamiento). Como mucho 3 al día.
- **Orquestador**: Claude Code (este rol). Configuración, ejecuciones con datos privados, revisión e integración.
- **Humano**: el propietario.

Cada tarea se acepta cuando **su comando de aceptación termina con exit 0 en un checkout limpio** y el orquestador revisa el diff. Las rutas son del repo salvo que se diga otra cosa. El código va en `factory/` (Python 3.12, `uv`).

| ID | Tarea | Ficheros permitidos | Comando de aceptación | Criterio | No-objetivos | Depende de | Quién | Est. [Suposición] |
|---|---|---|---|---|---|---|---|---|
| **F0-01** | Esqueleto del proyecto Python: `pyproject.toml` (uv, ruff, pytest, check-jsonschema), `Makefile` con `check` (ruff + pytest + validación de schemas y ejemplos) | `pyproject.toml`, `Makefile`, `factory/__init__.py`, `tests/test_schemas.py` | `make check` | Los 8 ejemplos de `examples/executor/` y las líneas de `trajectory.example.jsonl` validan, y los 7 casos negativos de [04](04-executor-contract.md) §7 se rechazan en `tests/test_schemas.py` | Nada de lógica de la factory | — | Peón | 2 h |
| **F0-02** | Servicio de emisión de keys (corre en Hetzner, custodia la master key) + cliente: `mint(data_class, budget_usd, ttl)`, `spend(key)`, `revoke(key)` sobre la API de LiteLLM (`/key/generate` con `team_id`, `max_budget` y `duration`; `/key/info`; `/key/delete`). El orquestador se autentica con un token propio que solo permite equipos de generación | `factory/gateway/*.py` (incluido `smoke.py`, que usa F0-03), `tests/gateway/*` | `make check` (tests con HTTP simulado mediante `respx` o `responses`) | Mapea `data_class` → `team_id` desde la configuración; nunca crea keys sin `max_budget`; rechaza el equipo verificador para el token del orquestador; falla de forma cerrada si la clase no existe | No configura el gateway real | F0-01 | Peón | 6 h |
| **F0-03** | Configurar el gateway real: equipos `factory-public`, `factory-client-product`, `factory-verifier`; alias de modelos (Sonnet, GLM con `use_chat_completions_api`, Qwen local); precios sombra > 0 con fuente | Configuración del gateway (fuera del repo) + `factory-pilot-data/gateway.md` | `uv run python -m factory.gateway.smoke` crea una key por equipo, llama a un modelo permitido, comprueba que uno no permitido da 401/403 y que `/spend/logs` devuelve los tokens por petición de la key | La matriz de [02](02-architecture.md) §8 se aplica de verdad. Si `/spend/logs` no está en OSS, se registra y el lector de tokens usa otra vía ([ADR-0004](adr/0004-gateway.md)) | Ninguna instancia nueva salvo que la compartida choque | F0-02 | Orquestador + humano (claves) | 3 h |
| **F0-04** | Spike 1, parte B (B1–B6 de [spikes/01](../spikes/01-harbor-cc-codex/README.md)) | `spikes/01-harbor-cc-codex/` (incluido `run-b.sh`) | `bash spikes/01-harbor-cc-codex/run-b.sh` termina con exit 0: ejecuta B1–B5, comprueba la recompensa y que el gasto de cada key en el gateway es > 0, y escribe la tabla de resultados en el README. B6 (red en la torre) lo cubre F0-07 | Cierra el [ADR-0001](adr/0001-harness-runner.md) | — | F0-03 | Orquestador | 2 h |
| **F0-05** | Importador de tareas públicas: lee filas de un dataset de Hugging Face fijado por revisión (`nebius/SWE-rebench-leaderboard`, `SWE-bench-Live/MultiLang`) y las convierte en tarea visible OpenSpec + parte oculta (parche de tests, gold, F2P/P2P), aplicando el filtro de corte y de clase de [06](06-harness-and-tasks.md) §2.1. Informa del idioma de cada split | `factory/tasks/import_hf.py`, `factory/tasks/inventory.py`, `tests/tasks/*` (con filas de ejemplo en `fixtures/hf/`) | `make check`: las filas de ejemplo dan las tareas esperadas, una fila anterior al corte se descarta y ningún fichero oculto aparece en la parte visible | El manifiesto `tasks/public-v1.manifest.json` registra dataset, revisión, ids y digests | No descarga imágenes en los tests | F0-01, F0-08 | Peón | 4 h |
| **F0-06** | Builder de snapshot `fresh-init`: `git archive <base>` → repo nuevo con un commit, sin remotos ni tags | `factory/snapshot/*.py`, `tests/snapshot/*` | `make check`, con un test que crea un repo con un commit «futuro» que contiene un secreto y comprueba que `git log --all`, `git fsck --lost-found` y `git cat-file --batch-all-objects` no lo encuentran en el snapshot | Amenaza T15 cubierta | No es el sandbox | F0-01 | Peón + revisión del orquestador | 3 h |
| **F0-07** | Red del sandbox en la torre: red Docker `factory-egress` + reglas en `DOCKER-USER` (solo `IP:puerto` del gateway) + `network-probe` con Harbor | `infra/torre/egress.sh`, `spikes/01-…/tasks/network-probe` | En la torre: `network-probe` da reward 1 y un `curl` a GitHub desde el contenedor falla | T16 cubierta con evidencia | Sin Kubernetes ni microVM | F0-03 | Orquestador + humano (root en la torre) | 3 h |
| **F0-08** | Esquemas `factory.task.json` y `verifier.json`, y conversor `visible/` (OpenSpec) → tarea de Harbor sin `solution/` ni tests ocultos | `schemas/task.schema.json`, `schemas/verifier-task.schema.json`, `factory/tasks/to_harbor.py`, `tests/tasks/*` | `make check`, con un test de que el árbol de Harbor generado no contiene ningún fichero de `hidden/` | [ADR-0005](adr/0005-task-format.md) implementado | — | F0-01 | Peón | 4 h |
| **F0-09** | Parser de JUnit XML (pytest, jest-junit, vitest) → estados por test | `factory/junit.py`, `tests/junit/*` (con XML de ejemplo de los tres runners) | `make check` | Estados `passed`, `failed`, `error`, `skipped` por id de test estable entre runners | Sin parsers de texto | F0-01 | Peón | 3 h |
| **F0-10** | Revalidador de tareas, pasos 4–8 de [06](06-harness-and-tasks.md) §2.2 (imagen en la base, 3 + 3 ejecuciones, derivación de F2P/P2P, flaky, snapshot), para tareas importadas o minadas. La separación de parches (pasos 1–3, solo para minado) va en el mismo módulo, pero se usa en F1+ | `factory/miner/*.py`, `tests/miner/*` | `make check` con 2 tareas de un repo fixture (`fixtures/repos/py-calc` y `ts-calc`), de las que sale exactamente 1 válida y 1 descartada por flaky | Los flaky se descartan; F2P vacío → descarte; el ~30 % recibe un test de reproducción visible (paso 11) | No escribe specs | F0-06, F0-08, F0-09, F0-11 | Peón (puede partirse en 10a/10b) | 1–2 días |
| **F0-11** | Repo fixture con trampas: `fixtures/repos/py-calc` y `ts-calc` + un diff de trampa por amenaza T01–T30 aplicable + una tarea factible + una canaria con test visible mutado | `fixtures/**` | `make check` lista cada amenaza de [05](05-verification-design.md) con su fixture o con «proceso/fuera de alcance» | Cobertura 1:1 con la tabla de amenazas | Sin datos del piloto | F0-01 | Peón | 1 día |
| **F0-12** | Verificador v0: validación del parche, diff-guard, checkout limpio desde un mirror, P2P y F2P con parche oculto **dentro de un contenedor efímero sin red ni almacén** (principio 6 de [05](05-verification-design.md)), comprobación de ids de F2P en el JUnit, feedback con lista blanca (principio 7), estados `error_infra` y `reject:timeout`, veredicto de canaria y `verdict.json` con hashes. Mutation y SAST, en modo informativo | `factory/verifier/**`, `tests/verifier/**` | `make check`: todas las fixtures de trampa de F0-11 (incluidas `read-hidden-tests`, `forge-junit` y `feedback-leak`) dan `reject` o `cheat_suspected`; la tarea factible con el gold da `accept` y con un diff vacío, `reject`; la canaria con el test mutado en verde da `cheat_suspected` | Falla de forma cerrada ante cualquier error | Sin holdouts de escenario (F1), sin juez | F0-08, F0-09, F0-11 | **Sonnet** + revisión del orquestador | 3–4 días |
| **F0-13** | Adaptadores: configuración de los 4 agentes de Harbor (versiones fijadas, flags de [04](04-executor-contract.md)), prompt `base-v1`, detección de `abort.json`, **diff calculado en el host** ([04](04-executor-contract.md) §3) y escritor de la salida del contrato (diff, tokens del gateway, coste con la tabla de precios, procedencia) | `factory/adapters/**`, `prompts/base-v1.md`, `tests/adapters/**` | `make check` + `harbor run -a oracle` sobre la tarea fixture produce un `run.json` válido contra el schema; la fixture `tamper-gitattributes` no altera el diff | Mapeo de `exit` de [04](04-executor-contract.md) §5 con tests por caso | Sin modelos reales en los tests | F0-02, F0-04, F0-08 | **Sonnet** | 2 días |
| **F0-14** | Normalizador de los 4 formatos de trayectoria → `trajectory-event` | `factory/normalize/**`, `tests/normalize/**` (con trayectorias reales de F0-04 anonimizadas) | `make check`: cada evento valida contra el schema y el contador de «no mapeados» es 0 en las muestras | — | Sin OTel GenAI | F0-04, F0-01 | Peón | 1 día |
| **F0-15** | Métricas: M1 (gen y total, con k = 3), M2 (pass@1, pass^3, pass^5), M7a–c, IC por bootstrap pareado, no-inferioridad con Δ, `audit.py` y `report --check`, e informe en `.md` y `.json` | `factory/metrics/**`, `tests/metrics/**` | `make check` con runs y veredictos sintéticos de resultado conocido | Las cifras coinciden con un cálculo a mano en el test | Sin dashboard | F0-01 | Peón | 1 día |
| **F0-16** | Baseline humana de M4: SZZ básico (PyDriller) sobre 12 meses de PRs humanos | `factory/metrics/szz.py`, `tests/metrics/test_szz.py` | `make check` con un repo fixture con un bug introducido y su fix; después el orquestador lo ejecuta sobre el piloto | La regresión del fixture se atribuye al commit correcto | — | F0-01 | Peón (código) + orquestador (ejecución) | 1 día |
| **F0-17** | Importar y revalidar las 30 tareas públicas: fijar la revisión de cada dataset, calcular el corte único con los modelos de los brazos, importar (F0-05), revalidar en la torre (F0-10) y auditar 10 al azar | `tasks/public-v1.manifest.json` (en el repo) + parte oculta en el almacén del verificador | `uv run python -m factory.tasks.inventory --store <almacén> --min-valid 30 --min-lang ts=8` termina con exit 0 (o la zona intermedia de §1) | El manifiesto pasa el hook de pre-commit y no contiene contenido oculto | Sin specs reescritos | F0-05, F0-10, F0-12 | Orquestador + humano (auditoría de 10 tareas, ~1 h) | 1–2 días |
| **F0-18** | Ejecutar la matriz: 30 tareas × 6 brazos × k (840 runs) con concurrencia por proveedor ([06](06-harness-and-tasks.md) §5) y verificación en Hetzner; congelar el conjunto v1 | `factory/run_matrix.py` + datos privados | `uv run python -m factory.run_matrix --check runs/ --expect 840` termina con exit 0: todos los runs tienen veredicto, ≥ 95 % de salidas válidas y `error_infra` ≤ 5 % | Los `error_infra` se reintentan y no cuentan como fallo del brazo | — | F0-12…F0-17, F0-07, F0-21 | Orquestador | 2–3 días (pared) |
| **F0-19** | Auditoría humana de 40 veredictos al azar (30 `accept`, 10 `reject`/`cheat_suspected`) y reverificación de 100 | Hoja en `factory-pilot-data/` + `factory/metrics/audit.py` (en F0-15) | `uv run python -m factory.metrics.audit --sheet ../factory-pilot-data/audit-f0.csv` termina con exit 0 si ≤ 1 falso `accept`, ≥ 9/10 en los rechazos y reproducibilidad ≥ 99 % | — | — | F0-18 | Humano (~5 h) + orquestador | 1 día |
| **F0-20** | Informe de F0 y decisión de F1 (sigue, cambia de rumbo o para, según §1) + volcado a doc-rag | `reports/f0-baseline.md` (sin datos del piloto) | `make check && .githooks/pre-commit` termina con exit 0, y `uv run python -m factory.metrics.report --check reports/f0-baseline.md` comprueba que hay una línea con valor por cada criterio de salida, de zona intermedia y de abandono de F0 | — | — | F0-15, F0-16, F0-19 | Orquestador | 4 h |
| **F0-21** | Provisionar el verificador en Hetzner: usuario y credenciales propios, mirror de los repos de las tareas (públicos en F0; los del piloto se añaden en F1), deploy key del almacén de holdouts, pull de artefactos desde la torre (nunca push), contenedor efímero de verificación y equipo `factory-verifier` en el gateway | `infra/verifier/**` (sin hosts: los valores van en `factory-pilot-data/`) | `bash infra/verifier/isolation-check.sh` termina con exit 0. Comprueba que desde un sandbox de la torre solo se llega al puerto del gateway en el host de Hetzner (ni SSH ni ningún otro puerto), que el verificador corre con su propio usuario y Docker rootless y que el volumen de holdouts no lo ve ningún otro usuario ni contenedor del host, que el orquestador no puede leer el almacén de holdouts ni emitir keys del equipo verificador, que Hetzner puede tirar de un artefacto de prueba y que el contenedor de verificación no tiene red | Tesis 2 probada en la infraestructura real, no solo con fixtures | Sin alta disponibilidad | F0-02, F0-07, F0-12 | Orquestador + humano (acceso a Hetzner) | 1 día |

**Camino crítico**: F0-01 → F0-02 → F0-03 → F0-04 → (F0-13, F0-14) y F0-01 → (F0-06, F0-08, F0-09, F0-11) → (F0-05, F0-10) → F0-12 → (F0-17, F0-21) → F0-18 → F0-19 → F0-20.

**Coste estimado de F0**:
- 2–3 subagentes Sonnet (F0-12, F0-13 y un posible rescate).
- Unos 15 despachos de peón.
- 90–270 USD de Anthropic para el brazo A1 (otros 90–270 si se añade A2′ con OpenAI) más < 5 USD del spike [Suposición].
- ~1 jornada humana entre la auditoría de tareas y la de veredictos.

## Decisiones abiertas

- Fecha de inicio de F0 y disponibilidad del propietario para las tareas humanas (F0-03, F0-07, F0-17, F0-19).
- Si F1 empieza con C1 o con C4 (más segura y con peor señal de valor), según los resultados de F0 por clase.
- Si F2 incluye OpenHands SDK como brazo adicional.
