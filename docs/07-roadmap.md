# 07 · Roadmap

> **Resumen.** Rediseño del 2026-11-02 ([ADR-0012](adr/0012-stage-chain-and-profiles.md)). Cuatro fases, cada una con un criterio de salida y un criterio de abandono medibles:
> - **A · Núcleo**: medir las etapas implementar y verificar con las tareas públicas ya revalidadas. Es la antigua F0, recortada.
> - **B · De la spec al producto**: construir **apps web internas desde cero** a partir de una spec aprobada, con escenarios ocultos y un agente de navegador como oráculo. Primer perfil de software. Sin código del cliente.
> - **C · Cadena completa en el piloto**: las ocho etapas sobre los repos reales (issues, épicas, migraciones), con despliegue tras feature flags y vuelta desde producción.
> - **D · Más perfiles**: API o servicio, CLI o librería, pipeline de datos y producto con IA, uno a uno.
>
> Dos líneas atraviesan todas las fases: la intensidad del harness por modelo y el auto-merge por etapa, tipo de trabajo y perfil. Todas las duraciones son estimaciones [Suposición].

## 1. Fases

### A · Núcleo: implementar y verificar

- **Objetivo**: medir los seis brazos de [06](06-harness-and-tasks.md) §5 sobre las tareas públicas ya revalidadas ([06](06-harness-and-tasks.md) §2.1). Mide la factory, no qué modelo es mejor: las comparaciones entre modelos distintos llevan la etiqueta «posible contaminación» ([06](06-harness-and-tasks.md) §3).
- **Punto de partida (2026-11-02)**: 26 tareas Python válidas [Cierto]; 0 TS por fallos de la revalidación en monorepos grandes ([09](09-open-questions.md)). Backlog en §2: casi todo hecho.
- **Duración estimada**: 1–2 semanas [Suposición].

| Tipo | Criterio | Cómo se mide |
|---|---|---|
| **Salida** | ≥ 15 tareas válidas (zona intermedia de la antigua F0 aceptada). Las TS se intentan con un tope de 1 día (decisión del 2026-11-02); si no salen ≥ 8, el informe declara que la etapa solo está medida en Python | Inventario del almacén |
| **Salida** (salud del harness) | ≥ 95 % de las ejecuciones producen una salida de contrato válida y `error_infra` ≤ 5 % (cada `error_infra` se repite hasta 2 veces) | `check-jsonschema` sobre `runs/` |
| **Salida** | Verificador reproducible: ≥ 99 % de veredictos idénticos al repetir 100 veredictos al azar | Reverificación |
| **Salida** | **Falsos `accept`**: ≤ 1 en una auditoría de 30 `accept` al azar, y ≥ 9/10 en 10 `reject`/`cheat_suspected` | Hoja de auditoría |
| **Salida** | Informe con pass@1, pass^k, M1 y M7a–c por brazo, con IC | `reports/a-baseline.md` |
| **Abandono** | El mejor brazo saca pass@1 < 15 % → revisar el harness con 5 tareas a mano antes de culpar al modelo | Informe |
| **Abandono** | ≥ 4 falsos `accept` de 30 tras 2 iteraciones del verificador → la verificación automática no es viable con estas suites: parar y replantear | Auditoría |

### B · De la spec al producto: perfil app web

- **Objetivo**: que la factory construya una app web interna desde cero (login, formularios, listados, flujos de negocio) a partir de una spec aprobada, la despliegue en staging y la compruebe con escenarios ocultos. Cubre E2, E3, E4, E5 y E7 en staging.
- **Por qué antes que el piloto**: no necesita código del cliente, prueba la parte nueva más arriesgada (el oráculo de producto) y es lo que más se parece a «construir cualquier software».
- **Material**: 5 specs de apps internas pequeñas escritas por el orquestador y aprobadas por el propietario, más una app real: **el frontend de la propia factory** (decisión del 2026-11-02). Se construye contra un contrato de API con datos de prueba, para no depender de la fase C, y se conecta a la API real cuando exista. Las specs de [Vibe Code Bench](https://arxiv.org/abs/2603.04601) no son públicas [Probable], así que no hay conjunto externo con el que calibrar.
- **Duración estimada**: 4–6 semanas [Suposición].

| Tipo | Criterio | Cómo se mide |
|---|---|---|
| **Salida** (el oráculo funciona) | El ejecutor de escenarios detecta ≥ 90 % de los **defectos sembrados** (flujos rotos a propósito en apps correctas) y da como buenos ≥ 95 % de los escenarios en las apps de referencia | M10 sobre ≥ 40 defectos |
| **Salida** (el oráculo es fiable) | Concordancia ≥ 85 % con la revisión humana en 50 pasos de escenario al azar | Auditoría |
| **Salida** (la factory construye) | Al menos un brazo pasa ≥ 60 % de los escenarios ocultos de media en las 6 apps, con k = 3 (referencia externa: 61,8 % en Vibe Code Bench [Cierto]) | M9 |
| **Salida** | Antitrampas: 0 accesos a escenarios ocultos desde el constructor en todas las ejecuciones; la diferencia entre escenarios visibles y ocultos se publica | Logs del sandbox; M9 visibles frente a ocultos |
| **Salida** | Revisión humana de arquitectura de las apps del mejor brazo sin bloqueantes, y M7a–c dentro de lo comparable | Hoja de revisión |
| **Zona intermedia** | Detección de defectos entre 75 y 90 % → una iteración del ejecutor de escenarios y otra medición con defectos nuevos | M10 |
| **Abandono** | Detección < 75 % tras 2 iteraciones → el oráculo de navegador no sirve: el perfil app web pasa a escenarios deterministas (Playwright escritos por el escritor de escenarios) y se repite la fase | M10 |
| **Abandono** | El mejor brazo pasa < 20 % de los escenarios ocultos → revisar spec, plan y entorno en 2 apps a mano antes de culpar al modelo | M9 |

### C · Cadena completa en el piloto

- **Objetivo**: las ocho etapas sobre los repos del piloto. Issues (antigua F1), épicas y migraciones recorren la cadena; el despliegue va a staging tras una feature flag, y las señales de producción vuelven a E1.
- **Requisito de entrada**: revisar el aislamiento de [ADR-0011](adr/0011-single-host-f0.md) antes de meter código del cliente ([09](09-open-questions.md)), con S3 y S4 confirmados (2026-11-01).
- **Duración estimada**: 8–12 semanas [Suposición].

| Tipo | Criterio | Cómo se mide |
|---|---|---|
| **Salida** (issues) | ≥ 20 PRs en borrador desde issues reales, revisados por personas, con M3 ≥ 50 % | GitHub |
| **Salida** (épicas) | ≥ 3 épicas recorren E2–E7 con escenarios ocultos, y el propietario acepta la entrega de al menos 2 | Hoja de entrega |
| **Salida** (migraciones) | Una migración real cubre ≥ 80 % de los ficheros afectados con la suite en verde y revisión humana | Diff y CI |
| **Salida** (canarias) | ≥ 30 tareas-canaria distintas, con cota superior al 95 % de M5 ≤ 10 % | Veredictos de canarias |
| **Salida** (vuelta desde producción) | ≥ 5 tareas de E1 nacen de señales de producción y llegan a PR | Trazas de E8 → E1 |
| **Salida** | Mediana y p90 de M6, con la revisión humana incluida | Eventos de GitHub |
| **Abandono** | M3 < 30 % tras 20 PRs → revisar specs y tipo de trabajo antes de seguir | M3 |
| **Abandono** | La mediana del tiempo de revisión por PR ≥ la del tiempo estimado a mano → parar: la factory no ahorra trabajo | Formulario de revisión (`review-minutes`, `manual-estimate-minutes`) |

### D · Más perfiles

- **Objetivo**: admitir perfiles nuevos uno a uno. Orden por decidir ([09](09-open-questions.md)); candidatos: API o servicio, CLI o librería, pipeline de datos y producto con IA.
- **Criterio de admisión de un perfil**:
  - su oráculo detecta ≥ 90 % de los defectos sembrados;
  - la concordancia con revisión humana es ≥ 85 %;
  - la cota de M5 en sus canarias es ≤ 10 %.

  Los perfiles con oráculo débil (UX, juegos, contenido) se admiten solo con puerta humana en E5.

### Líneas transversales

- **Intensidad del harness por modelo** (antigua F2): elegir por modelo entre un intento, best-of-n, cascada de [ADR-0010](adr/0010-escalation-on-verified-failure.md) o reintento con motivo, por coste por cambio aceptado. Empieza con los datos de la fase A.
- **Auto-merge** (antigua F3, [ADR-0008](adr/0008-gates-and-auto-merge.md)): por etapa, tipo de trabajo y perfil. Depende sobre todo del volumen: llegar a 150 cambios de una misma clase puede llevar 2–4 trimestres [Suposición].
- **Auto-mejora**: todo PR que toque `prompts/`, `pipelines/`, `factory/adapters/`, `factory/verifier/`, los perfiles o la configuración de modelos ejecuta el conjunto congelado con el brazo afectado (M8). M8 rige desde que la fase A congela el conjunto v1.

## 2. Backlog de la fase A (antes «F0»)

Los identificadores `F0-NN` se mantienen. Estado a 2026-11-02: F0-01 a F0-16 hechas; F0-17 con 26 tareas Python y TS pendiente; F0-18 a F0-21 pendientes.

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
| **F0-03** | Configurar el gateway real: equipos `factory-public`, `factory-client-product`, `factory-verifier`; alias de modelos (Sonnet, GLM con `use_chat_completions_api`, Qwen local); precios sombra > 0 con fuente | Configuración del gateway (fuera del repo) + `factory-pilot-data/gateway.md` | `uv run python -m factory.gateway.smoke` crea una key por equipo, llama a un modelo permitido, comprueba que uno no permitido da 401/403 y que `/spend/logs` devuelve los tokens por petición de la key | La matriz de [02](02-architecture.md) §8 se aplica de verdad. Si `/spend/logs` no está en OSS, se registra y el lector de tokens usa otra vía ([ADR-0004](adr/0004-gateway.md)) | Ninguna instancia nueva salvo que la compartida choque | F0-02 | Orquestador (tiene acceso al gateway) | 3 h |
| **F0-04** | Spike 1, parte B (B1–B6 de [spikes/01](../spikes/01-harbor-cc-codex/README.md)) | `spikes/01-harbor-cc-codex/` (incluido `run-b.sh`) | `bash spikes/01-harbor-cc-codex/run-b.sh` termina con exit 0: ejecuta B1–B5 y B7, comprueba la recompensa, que el gasto de cada key en el gateway es > 0 (salvo A1 en la variante (c)) y el porcentaje de ventana por ejecución de los dos planes, y escribe la tabla de resultados en el README. B6 (red en la torre) lo cubre F0-07 | Cierra el [ADR-0001](adr/0001-harness-runner.md) | — | F0-03 | Orquestador | 2 h |
| **F0-05** | Importador de tareas públicas: lee filas de un dataset de Hugging Face fijado por revisión (`nebius/SWE-rebench-leaderboard`, `SWE-bench-Live/MultiLang`) y las convierte en tarea visible OpenSpec + parte oculta (parche de tests, gold, F2P/P2P), aplicando el filtro de corte y de clase de [06](06-harness-and-tasks.md) §2.1. Informa del idioma de cada split | `factory/tasks/import_hf.py`, `factory/tasks/inventory.py`, `tests/tasks/*` (con filas de ejemplo en `fixtures/hf/`) | `make check`: las filas de ejemplo dan las tareas esperadas, una fila anterior al corte se descarta y ningún fichero oculto aparece en la parte visible | El manifiesto `tasks/public-v1.manifest.json` registra dataset, revisión, ids y digests | No descarga imágenes en los tests | F0-01, F0-08 | Peón | 4 h |
| **F0-06** | Builder de snapshot `fresh-init`: `git archive <base>` → repo nuevo con un commit, sin remotos ni tags | `factory/snapshot/*.py`, `tests/snapshot/*` | `make check`, con un test que crea un repo con un commit «futuro» que contiene un secreto y comprueba que `git log --all`, `git fsck --lost-found` y `git cat-file --batch-all-objects` no lo encuentran en el snapshot | Amenaza T15 cubierta | No es el sandbox | F0-01 | Peón + revisión del orquestador | 3 h |
| **F0-07** | Red del sandbox en la torre: modo `allowlist` de Harbor con el nombre del gateway (filtro SNI; las reglas `DOCKER-USER` por IP se descartan porque el gateway está detrás de Cloudflare, [02](02-architecture.md) §6) + `network-probe` | La variante del probe con el host vive en `factory-pilot-data/spikes/np-gw` | En la torre: `network-probe` da reward 1, con el gateway alcanzable y GitHub, example.com y otra web de la misma CDN inalcanzables. **Hecho el 2026-11-01** | T16 cubierta con evidencia | Sin Kubernetes ni microVM | F0-03 | Orquestador + humano (root en la torre) | 3 h |
| **F0-08** | Esquemas `factory.task.json` y `verifier.json`, y conversor `visible/` (OpenSpec) → tarea de Harbor sin `solution/` ni tests ocultos | `schemas/task.schema.json`, `schemas/verifier-task.schema.json`, `factory/tasks/to_harbor.py`, `tests/tasks/*` | `make check`, con un test de que el árbol de Harbor generado no contiene ningún fichero de `hidden/` | [ADR-0005](adr/0005-task-format.md) implementado | — | F0-01 | Peón | 4 h |
| **F0-09** | Parser de JUnit XML (pytest, jest-junit, vitest) → estados por test | `factory/junit.py`, `tests/junit/*` (con XML de ejemplo de los tres runners) | `make check` | Estados `passed`, `failed`, `error`, `skipped` por id de test estable entre runners | Sin parsers de texto | F0-01 | Peón | 3 h |
| **F0-10** | Revalidador de tareas, pasos 4–8 de [06](06-harness-and-tasks.md) §2.2 (imagen en la base, 3 + 3 ejecuciones, derivación de F2P/P2P, flaky, snapshot), para tareas importadas o minadas. La separación de parches (pasos 1–3, solo para minado) va en el mismo módulo, pero se usa en F1+ | `factory/miner/*.py`, `tests/miner/*` | `make check` con 2 tareas de un repo fixture (`fixtures/repos/py-calc` y `ts-calc`), de las que sale exactamente 1 válida y 1 descartada por flaky | Los flaky se descartan; F2P vacío → descarte; el ~30 % recibe un test de reproducción visible (paso 11) | No escribe specs | F0-06, F0-08, F0-09, F0-11 | Peón (puede partirse en 10a/10b) | 1–2 días |
| **F0-11** | Repo fixture con trampas: `fixtures/repos/py-calc` y `ts-calc` + un diff de trampa por amenaza T01–T30 aplicable + una tarea factible + una canaria con test visible mutado | `fixtures/**` | `make check` lista cada amenaza de [05](05-verification-design.md) con su fixture o con «proceso/fuera de alcance» | Cobertura 1:1 con la tabla de amenazas | Sin datos del piloto | F0-01 | Peón | 1 día |
| **F0-12** | Verificador v0: validación del parche, diff-guard, checkout limpio desde un mirror, P2P y F2P con parche oculto **dentro de un contenedor efímero sin red ni almacén** (principio 6 de [05](05-verification-design.md)), comprobación de ids de F2P en el JUnit, feedback con lista blanca (principio 7), estados `error_infra` y `reject:timeout`, veredicto de canaria y `verdict.json` con hashes. Mutation y SAST, en modo informativo | `factory/verifier/**`, `tests/verifier/**` | `make check`: todas las fixtures de trampa de F0-11 (incluidas `read-hidden-tests`, `forge-junit` y `feedback-leak`) dan `reject` o `cheat_suspected`; la tarea factible con el gold da `accept` y con un diff vacío, `reject`; la canaria con el test mutado en verde da `cheat_suspected` | Falla de forma cerrada ante cualquier error | Sin holdouts de escenario (F1), sin juez | F0-08, F0-09, F0-11 | **Sonnet** + revisión del orquestador | 3–4 días |
| **F0-13** | Adaptadores: configuración de los 4 agentes de Harbor (versiones fijadas, flags de [04](04-executor-contract.md)), prompt `base-v1`, detección de `abort.json`, **diff calculado en el host** ([04](04-executor-contract.md) §3) y escritor de la salida del contrato (diff, tokens del gateway, coste con la tabla de precios, procedencia) | `factory/adapters/**`, `prompts/base-v1.md`, `tests/adapters/**` | `make check` + `harbor run -a oracle` sobre la tarea fixture produce un `run.json` válido contra el schema; la fixture `tamper-gitattributes` no altera el diff | Mapeo de `exit` de [04](04-executor-contract.md) §5 con tests por caso | Sin modelos reales en los tests | F0-02, F0-04, F0-08 | **Sonnet** | 2 días |
| **F0-14** | Normalizador de los 4 formatos de trayectoria → `trajectory-event` | `factory/normalize/**`, `tests/normalize/**` (con trayectorias reales de F0-04 anonimizadas) | `make check`: cada evento valida contra el schema y el contador de «no mapeados» es 0 en las muestras | — | Sin OTel GenAI | F0-04, F0-01 | Peón | 1 día |
| **F0-15** | Métricas: M1 (gen y total, con k = 3), M2 (pass@1, pass^3, pass^5), M7a–c, IC por bootstrap pareado, no-inferioridad con Δ, `audit.py` y `report --check`, e informe en `.md` y `.json` | `factory/metrics/**`, `tests/metrics/**` | `make check` con runs y veredictos sintéticos de resultado conocido | Las cifras coinciden con un cálculo a mano en el test | Sin dashboard | F0-01 | Peón | 1 día |
| **F0-16** | Baseline humana de M4: SZZ básico (PyDriller) sobre 12 meses de PRs humanos | `factory/metrics/szz.py`, `tests/metrics/test_szz.py` | `make check` con un repo fixture con un bug introducido y su fix; después el orquestador lo ejecuta sobre el piloto | La regresión del fixture se atribuye al commit correcto | — | F0-01 | Peón (código) + orquestador (ejecución) | 1 día |
| **F0-17** | Importar y revalidar las 30 tareas públicas: fijar la revisión de cada dataset, anotar en el informe las fechas de corte de los modelos de los brazos ([06](06-harness-and-tasks.md) §3), importar (F0-05), revalidar en la torre (F0-10) y auditar 10 al azar | `tasks/public-v1.manifest.json` (en el repo) + parte oculta en el almacén del verificador | `uv run python -m factory.tasks.inventory --store <almacén> --min-valid 15` termina con exit 0 (§1, fase A) | El manifiesto pasa el hook de pre-commit y no contiene contenido oculto | Sin specs reescritos | F0-05, F0-10, F0-12 | Orquestador (audita las 10 con el método de F0-19; el propietario solo ve las dudosas) | 1–2 días |
| **F0-18** | Ejecutar la matriz: las tareas válidas × 6 brazos × k con concurrencia por proveedor ([06](06-harness-and-tasks.md) §5) y verificación en la torre ([ADR-0011](adr/0011-single-host-f0.md)); congelar el conjunto v1 | `factory/run_matrix.py` + datos privados | `uv run python -m factory.run_matrix --check runs/` termina con exit 0: todos los runs tienen veredicto, ≥ 95 % de salidas válidas y `error_infra` ≤ 5 % | Los `error_infra` se reintentan y no cuentan como fallo del brazo | — | F0-12…F0-17, F0-07, F0-21 | Orquestador | 2–3 días (pared) |
| **F0-19** | El orquestador audita 40 veredictos al azar (30 `accept`, 10 `reject`/`cheat_suspected`) y reverifica 100. **Método**: por cada veredicto, leer spec, diff, gold y tests ocultos, y decidir si el diff resuelve el issue y no solo pasa los tests. Si hay duda, escribir una prueba extra y ejecutarla en un contenedor sin red. Las dudas se le preguntan al propietario con el formulario (regla 10 de `CLAUDE.md`). Después de leer la parte oculta, el auditor no cambia specs ni prompts: una tarea mala se descarta, no se reescribe | Hoja en `factory-pilot-data/` + `factory/metrics/audit.py` (en F0-15) | `uv run python -m factory.metrics.audit --sheet ../factory-pilot-data/audit-f0.csv` termina con exit 0 si ≤ 1 falso `accept`, ≥ 9/10 en los rechazos y reproducibilidad ≥ 99 % | — | — | F0-18 | Orquestador + propietario (solo las dudosas, ~15–30 min [Suposición]) | 1 día |
| **F0-20** | Informe de la fase A y decisión de pasar a B (sigue, cambia de rumbo o para, según §1) + volcado a doc-rag | `reports/a-baseline.md` (sin datos del piloto) | `make check && .githooks/pre-commit` termina con exit 0, y `uv run python -m factory.metrics.report --check reports/a-baseline.md` comprueba que hay una línea con valor por cada criterio de salida y de abandono de la fase A | — | — | F0-15, F0-16, F0-19 | Orquestador | 4 h |
| **F0-21** | Separar el verificador del generador en la torre ([ADR-0011](adr/0011-single-host-f0.md)): almacén de tareas en una carpeta 700 que ningún sandbox monta, contenedor efímero de verificación sin red y equipo `factory-verifier` en el gateway | `infra/verifier/**` (sin hosts: los valores van en `factory-pilot-data/`) | `bash infra/verifier/isolation-check.sh` termina con exit 0. Comprueba que desde un sandbox solo se llega al puerto del gateway, que ningún contenedor de agente monta el almacén, que el contenedor de verificación no tiene red y que las keys del agente no pueden emitir keys del equipo verificador | Tesis 2 por proceso y montaje en F0; se revisa antes de F1 | Sin alta disponibilidad ni aislamiento por máquina | F0-02, F0-07, F0-12 | Orquestador | 0,5 días |

**Camino crítico**: F0-01 → F0-02 → F0-03 → F0-04 → (F0-13, F0-14) y F0-01 → (F0-06, F0-08, F0-09, F0-11) → (F0-05, F0-10) → F0-12 → (F0-17, F0-21) → F0-18 → F0-19 → F0-20.

**Coste estimado de F0**:
- 2–3 subagentes Sonnet (F0-12, F0-13 y un posible rescate).
- Unos 15 despachos de peón.
- No hay gasto real en F0. A1 consume la suscripción de Anthropic del propietario (90–270 USD a precio de lista [Suposición]) y los brazos de GLM, el coding plan de z.ai. El coste se paga en cuota y en días de reloj ([06](06-harness-and-tasks.md) §5).
- ~1 jornada humana entre la auditoría de tareas y la de veredictos.

## 3. Backlog de la fase B (esbozo)

Se detalla como specs despachables cuando la fase A cierre. Las piezas, en orden:

| ID | Pieza | Quién |
|---|---|---|
| B-01 | Escribir la spec de la app real (el **frontend de la propia factory**: trabajo en curso, puertas humanas, veredictos y métricas; decisión del 2026-11-02) contra un contrato de API con datos de prueba, y las 5 specs de apps pequeñas, todas con sus escenarios visibles | Orquestador + aprobación del propietario |
| B-02 | Perfil app web: entorno (app + base de datos en contenedores), despliegue en staging en la torre y contrato del perfil ([06](06-harness-and-tasks.md) §7) | Sonnet (diseño) + peones |
| B-03 | Escritor de escenarios ocultos: un proceso aparte que, a partir de la spec aprobada, escribe escenarios que el constructor nunca ve | Sonnet + revisión del orquestador |
| B-04 | Ejecutor de escenarios: agente de navegador sobre la app desplegada, con veredicto por paso | Sonnet + peones |
| B-05 | Defectos sembrados: variantes rotas de las apps de referencia para medir M10 | Peones |
| B-06 | Etapas E2 y E3 automatizadas: de la spec aprobada al plan de tareas | Peones |
| B-07 | Ejecución: 6 apps × brazos × k = 3, auditoría y revisión de arquitectura | Orquestador + propietario |

## Decisiones abiertas

- Si el ejecutor de escenarios es un agente de navegador (como Vibe Code Bench) o scripts deterministas; se decide con los datos de B-04 y B-05.
- Qué perfil va después de app web (fase D).
- Si la fase C empieza con issues sueltos o con una épica.
