# 06 · Harness y tareas

> **Resumen.** El harness ejecuta *tareas × brazos × repeticiones* sobre Harbor y entrega cada diff al verificador aislado. Las tareas C1/C2 se minan de PRs fusionados del piloto con la receta de SWE-bench (F2P/P2P con el gold 3 veces, tests ocultos), más un snapshot sin historial y un detector de fugas en el spec. Sale ~1 tarea válida por cada 5 PRs con tests [Probable]. Hay seis brazos, comparados con k = 3, para separar el efecto del agente del efecto del modelo. orca-roles queda fuera porque no corre desatendido.

## 1. Runner

- **Harbor** (Apache-2.0, v0.25.0 del 2026-10-25, commit del 2026-10-31) [Cierto] como runner de la matriz: formato de tarea propio y `--n-concurrent`. Los agentes `claude-code`, `codex`, `opencode` y `mini-swe-agent` ya vienen integrados ([ADR-0001](adr/0001-harness-runner.md)). Lo cierra el spike 1.
- **Uso de Harbor**: solo se le encarga la **fase de generación** y la extracción del diff. Su verificador «separado» (`environment_mode = "separate"`) corre en el mismo host Docker [Cierto en la documentación de tareas de Harbor]. Eso no cumple la tesis 2, así que el verificador de Harbor solo ejecuta los tests visibles como señal temprana (no decisiva) y exporta el diff como artefacto. **El veredicto lo da el verificador de Hetzner** ([05](05-verification-design.md)).
- **Formato de tarea de Harbor**: `instruction.md`, `task.toml` (schema 1.4), `environment/` (Dockerfile), `solution/solve.sh` y `tests/test.sh`. La recompensa va en `/logs/verifier/reward.txt` o `reward.json` [Cierto]. La parte de la tarea que se replica a la torre **no lleva `solution/` ni los tests ocultos**: `solution/` queda vacío y `tests/` solo tiene los tests visibles. Un conversor genera la tarea de Harbor a partir de la tarea OpenSpec.

## 2. Receta de minado de PRs fusionados

Se basa en el pipeline de colección de SWE-bench ([SWE-bench/SWE-bench](https://github.com/SWE-bench/SWE-bench), MIT; `swebench/collect/utils.py` y `grading.py`) [Cierto] y en SWE-rebench V2 ([arXiv 2602.23866](https://arxiv.org/abs/2602.23866); código en [SWE-rebench/SWE-rebench-V2](https://github.com/SWE-rebench/SWE-rebench-V2), MIT) [Cierto]. Cambia en los cuatro puntos marcados con ★.

| Paso | Qué hace | Criterio de descarte |
|---|---|---|
| 1. Candidatos | PRs fusionados en la rama principal, de los últimos 18 meses, con un ticket enlazado o una descripción ≥ 2 frases | Sin descripción ni ticket; PRs de bots y de dependencias (salvo en C5) |
| 2. Clasificación | Clase de tarea C1–C5 por ficheros tocados y etiquetas (§4). **En F0 solo se minan C1 y C2**. C4 tiene su propia receta (§4) y C3 y C5 quedan diferidas | Toca auth, facturación, infraestructura o migraciones, o la clase no es elegible |
| 3. Separación | El diff del PR se parte en *parche de tests* (rutas que contienen `test`, `tests`, `e2e`, `testing`, `__tests__`, `*.spec.*`, `*.test.*`) y *parche de código* (el resto). Es la heurística de SWE-bench ampliada a JS/TS [Cierto para SWE-bench] | Sin parche de tests |
| 4. Entorno | Dockerfile en el **commit base** (`merge-base` del PR) con dependencias del lockfile de la base, instaladas con los scripts de instalación desactivados donde se pueda (T11) | La imagen no construye en 2 intentos. En SWE-rebench V2 solo ~20 % de los repos construyen al primer intento [Probable] |
| 5. Ejecución en la base | Los tests del parche de tests sobre la base, **3 veces** | — |
| 6. Ejecución con el gold | El parche de código + el parche de tests, **3 veces** | — |
| 7. Derivación | **FAIL_TO_PASS** = tests que fallan (o no existen) en la base en las 3 ejecuciones y pasan con el gold en las 3. **PASS_TO_PASS** = tests de los ficheros tocados y sus vecinos que pasan en la base y con el gold en las 3 | F2P vacío; cualquier test que cambie de estado entre repeticiones (flaky). SWE-rebench V2 descartó por flaky 970 de 33 049 instancias, ~3 % [Probable] |
| 8. ★ Snapshot | Para la parte visible: `git archive <base>` → `git init` nuevo → un único commit, sin remotos, tags ni objetos futuros. SWE-bench hace un *clone timesafe* (quita `origin`, borra tags posteriores, `reflog expire`, `gc --prune` y falla si queda algún commit posterior en `--all`) [Cierto, `docker_utils.py`]. El snapshot es más fuerte porque no queda nada que limpiar | — |
| 9. ★ Spec | `proposal.md` y `specs/` de OpenSpec se escriben a partir del ticket y la descripción del PR. Los redacta **Claude Opus vía la API de Anthropic, con una key del equipo `factory-client-product`** (la misma clase de datos que la tarea), **sin ver el parche gold**. Después una persona los revisa (~10 min por tarea [Suposición]). Opus no es el modelo de ningún brazo, pero es de la misma familia que A1. Para medir ese sesgo, 8 tareas llevan un spec escrito entero por la persona, y se compara el pass@1 de A1 frente al de los demás brazos en ese subconjunto | La persona no puede escribir el comportamiento esperado sin describir la implementación |
| 10. ★ Detector de fuga en el spec | Determinista: falla si el spec contiene identificadores (funciones, clases, constantes, rutas) que aparecen **solo** en las líneas añadidas del gold y no en la base | Fuga sin corregir. En SWE-rebench V2, el 23 % de las tareas derivadas de PRs tenían fuga [Probable] |
| 11. ★ Partición | Lo visible (spec, `visible_tests`, Dockerfile) va al almacén de tareas replicado. Lo oculto (parche de tests, listas F2P/P2P, gold) solo al almacén del verificador. **En el ~30 % de las tareas, elegido al azar, un único test F2P se expone como *test de reproducción visible***. Es el formato del que parten las canarias, y así una canaria no se distingue por llevarlo ([05](05-verification-design.md) §7). El veredicto sigue usando todos los F2P | — |

**Formato de resultados de tests**: todos los runners emiten **JUnit XML** (`pytest --junitxml`, `jest-junit`, el reporter `junit` de `vitest`), y un único parser lee los estados por test. SWE-PolyBench parsea el JSON de Jest y Mocha por `assertionResults` y no admite vitest [Cierto en su código]. Con JUnit no hacen falta parsers por runner.

**Rendimiento esperado del minado**:
- SWE-bench: 93 139 PRs → 11 407 tras el filtro de atributos (resuelven un issue y aportan tests) → 2 294 tras la ejecución, un **~20 % de los PRs con tests** ([arXiv 2310.06770](https://arxiv.org/abs/2310.06770), Tabla 10) [Probable, cifras leídas por un subagente].
- SWE-rebench V2: de 583 809 candidatos, 41 349 con F2P (~7 %) [Probable].
- En un repo privado con PRs pequeños y tests ligados a cada PR, el rendimiento estará más cerca del de SWE-bench que del de SWE-rebench [Suposición].
- **La tarea F0-05 lo mide antes de comprometer las 30.**

### Fuera del minado: síntesis

Si el piloto no da 30 tareas válidas, se completa con **inyección de bugs al estilo SWE-smith** ([arXiv 2504.21798](https://arxiv.org/abs/2504.21798); [SWE-bench/SWE-smith](https://github.com/SWE-bench/SWE-smith), MIT): se reescribe una función con un bug y se usan como F2P los tests existentes que pasan a fallar. El rendimiento de validación de SWE-smith fue del 50,1 % [Probable].

Las tareas sintéticas se etiquetan `synthetic`, se reportan aparte y no cuentan para el criterio de salida de F0. Sesgo conocido: sobrerrepresentan bugs pequeños y locales.

## 3. Contaminación y corte temporal

| Vector | Riesgo en este proyecto | Control |
|---|---|---|
| El modelo vio el repo en su preentrenamiento | Bajo: los repos piloto son privados [Probable] | Se registra si algún repo tuvo un espejo público. Si lo tuvo, se aplica **un único corte para todos los brazos**: solo entran PRs fusionados después de la fecha más tardía de entre las fechas de corte de conocimiento declaradas por los modelos de los brazos. Si un modelo no declara su corte, se usa su **fecha de publicación**. La fecha resultante se anota en el informe |
| El agente lee la solución en el historial | Alto sin control (T15) | Snapshot fresh-init (paso 8) + prueba `leak-git-history` |
| El agente la descarga de la red (T16) | Alto sin control | Red solo hacia el gateway |
| El spec delata la solución | Medio: 23 % en SWE-rebench V2 [Probable] | Pasos 9 y 10 |
| Los prompts se ajustan a las tareas del conjunto congelado (Goodhart) | Medio con M8 | Conjunto rotativo + canarias que rotan ([05](05-verification-design.md) §7) |
| Las tareas del piloto acaban en el repo público | Alto si se mezclan | [ADR-0009](adr/0009-data-policy-per-repo.md) + hook de pre-commit |

## 4. Clases de tarea

Cada tarea pertenece a una sola clase. La autonomía se concede por clase ([ADR-0008](adr/0008-gates-and-auto-merge.md)).

| Clase | Descripción | Elegibilidad | Evidencia de aceptación | Candidata a L4 |
|---|---|---|---|---|
| **C1 · Bugfix localizado** | Corrige un comportamiento descrito en un ticket | ≤ 3 ficheros de producción, ≤ 200 líneas cambiadas en el gold; existe un test F2P; no toca la API pública | F2P + P2P + mutation ≥ umbral + SAST | **Sí, la primera** |
| **C2 · Feature pequeña** | Añade un comportamiento acotado detrás de una interfaz existente | ≤ 5 ficheros, ≤ 300 líneas; tests F2P; sin migraciones | Igual que C1 + holdouts de escenario (F1+) | Después de C1 |
| **C3 · Refactor sin cambio funcional** | Reestructura sin cambiar el comportamiento | P2P amplio (≥ 20 tests en los ficheros tocados) | **Diferida a F3+**: sin F2P, la evidencia depende de un P2P amplio y de M7, que aún no tiene umbrales probados | No antes de F3 |
| **C4 · Solo tests** | Añade tests a código existente | No toca código de producción; el PR minado solo añade tests | **Mutantes del verificador**, no tests del agente. Al minar, el verificador genera mutantes del código de producción cubierto (StrykerJS o mutmut, con semilla fijada) y guarda como `K_gold` los que matan los tests del gold. El candidato se acepta si sus tests pasan en la base sin tocar código de producción y matan ≥ 80 % de `K_gold` [Suposición sobre el umbral]. Los mutantes y `K_gold` quedan ocultos. Receta propia: el paso 7 sustituye F2P por `K_gold`, y se descarta si `K_gold` < 5 | Sí (bajo riesgo), desde F2 |
| **C5 · Dependencias** | Sube versiones dentro de un rango menor o de parche | Hay lockfile; la suite pasa en la base | **Diferida a F3+**: sin F2P y con riesgo de cadena de suministro | No antes de F3 |
| Excluidas | Autenticación, facturación, infraestructura, migraciones de datos, contratos públicos | — | — | Nunca |

Una clase necesita **≥ 8 tareas** en el conjunto de F0 para reportarse por separado. Con menos, solo cuenta en el agregado [Suposición: con menos de 8 tareas el IC es demasiado ancho para leer nada].

## 5. Primera comparación (F0)

### Brazos

| Brazo | Ejecutor | Modelo (alias) | Repeticiones (k) | Qué aísla |
|---|---|---|---|---|
| **A1 · Baseline** | Claude Code 2.1.316 | Sonnet vía la API de Anthropic | 3 (de pago) | Referencia |
| **A6** | Claude Code 2.1.316 | GLM vía z.ai (`/v1/messages` de LiteLLM) | 5 | **Efecto del modelo con Claude Code fijo** (A1 frente a A6) y **efecto del ejecutor con GLM fijo** sin puente Responses (A6 frente a A3) |
| **A2** | Codex CLI 0.166.0 | GLM vía z.ai (puente Responses de LiteLLM) | 5 | Codex **más el puente** frente a A3. Codex solo admite `wire_api = "responses"`, así que el efecto del puente no se puede separar del de Codex con GLM: forma parte del brazo |
| **A3** | OpenCode 1.19.5 | GLM vía z.ai | 5 | **Efecto del ejecutor** con el modelo fijo (A2 frente a A3) |
| **A4** | OpenCode 1.19.5 | Qwen local en la 5090 (clase Qwen3.6-35B-A3B, parser `qwen3_coder`) | 5 | **Efecto del modelo** con el ejecutor fijo (A3 frente a A4) |
| **A5** | mini-swe-agent 2.4.6 | El mismo Qwen local | 5 | **Efecto del harness** con el modelo fijo (A4 frente a A5) |

- **Total**: 30 × (3 + 5 × 5) = **840 ejecuciones**. El coste real solo lo pone A1: 90 ejecuciones a 1–3 USD, entre 90 y 270 USD [Suposición].
- **Las comparaciones entre brazos usan las 3 primeras repeticiones de cada brazo** (pass@1, pass^3 y M1 con el mismo k). Las repeticiones 4 y 5 de los brazos sin coste real solo sirven para estimar pass^5 y la varianza dentro de cada brazo; nunca se comparan con A1.
- **Concurrencia**: A2, A3 y A6 comparten ≤ 4 en paralelo **entre los tres**, porque z.ai devuelve 429 con más de ~6 concurrentes [Cierto, medido en otro proyecto del propietario]. A4 y A5 dependen de vLLM en una sola GPU [Suposición: ~4 secuencias concurrentes con contexto de 64k].
- **Tiempo de pared estimado**: 2–3 días de ejecución desatendida [Suposición].
- Si la autorización de OpenAI para el código del piloto llega ([ADR-0009](adr/0009-data-policy-per-repo.md)), se añade **A2′ · Codex × un modelo de OpenAI** con k = 3.
- Los brazos con modelo local o de cuota usan **coste sombra**: el precio de lista de un modelo equivalente publicado por el proveedor (GLM, el precio de su API de pago; Qwen local, el precio por token de un proveedor que lo sirva), configurado en el gateway y declarado en el informe.

### Por qué no está el «equipo orca-roles»

No se puede ejecutar **desatendido** con su diseño actual [Cierto, README de orca-role-hook leído el 2026-10-31]:

1. El Planner es el único rol que habla con el usuario. El flujo se pausa a la espera de sus decisiones, y tras 3 rondas rechazadas «el Planner consulta contigo».
2. Los workers viven en pestañas de Orca y se coordinan con Orca Orchestration (`dispatch --inject`). No hay una entrada headless con una tarea y una salida con diff.
3. El E2E-Tester pide aprobación humana de su plan.

Además, su coste medido fue de **~37,6 USD por tarea** (4 tareas reales, 44 sesiones), y el 89 % fue de los tres roles Opus de larga vida [Cierto, medición propia del 2026-10-23]. 30 tareas con 3 repeticiones costarían ~3 400 USD. **Lo que sí se aprovecha**: su protocolo A/B «equipo frente a sesión única con coste por tarea aceptada» es el diseño de M1, y sus `rounds.jsonl` sirven de dato histórico. Un rol (por ejemplo, un revisor) solo entraría en la factory como variante de configuración de un brazo en F2, y solo si mejora M1 o M3.

### Lectura de resultados

- **Pareado**: misma tarea y diferencia por tarea, con las pruebas de [01](01-metrics.md) §3. Con 30 tareas solo se afirman diferencias de ~17 puntos o más.
- **Informe por brazo**: pass@1, pass^3 (y pass^5 donde haya), M1.gen, M1.total, tasa de `error_infra`, tasa de aborto, M7a/b/c y la distribución de tiempos.
- **Un fallo de infraestructura no es un fallo del brazo**: un 429 o un contenedor que no arranca son `error_infra`, se repiten y se reportan aparte. En cambio, un timeout o un OOM de los tests con el diff aplicado son `reject` y cuentan ([05](05-verification-design.md) principio 5).

## 6. Ciclo de vida del conjunto de tareas

- **Congelado**: las 30 tareas de F0 forman el conjunto congelado v1 (M8), que se congela al terminar F0-18. No se modifican; una tarea con un defecto descubierto se retira y se registra. En F2 crece hasta ≥ 80 tareas para bajar el margen de no-inferioridad de M8 a 10 puntos ([01](01-metrics.md) §3).
- **Rotativo**: el minado mensual de PRs nuevos alimenta el conjunto rotativo y las canarias.
- **Auditoría**: cada trimestre una persona revisa 10 tareas al azar (spec, F2P y gold), siguiendo la lección de la auditoría de OpenAI sobre SWE-bench Verified ([post](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/)).

## Decisiones abiertas

- Qué modelo local exacto y con qué cuantización. Depende de la memoria que deje libre el contexto de 64k en 32 GB [Suposición]. Se fija en F0-03.
- Si el conjunto de F0 debe incluir tareas de los tres repos o solo de los dos con más rendimiento. Lo decide la medición de F0-05.
- La tarifa sombra exacta por modelo: hay que documentarla con fuente y fecha en la configuración del gateway.
