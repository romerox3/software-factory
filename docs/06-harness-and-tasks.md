# 06 · Harness y tareas

> **Resumen.** El harness ejecuta la matriz *tareas × brazos × repeticiones* sobre Harbor y entrega cada diff al verificador aislado. Las tareas se minan de PRs fusionados de los repos piloto con la receta de SWE-bench: separar el parche de código del de tests, construir la imagen en el commit base, derivar FAIL_TO_PASS y PASS_TO_PASS con el gold ejecutado 3 veces y ocultar el parche de tests. Se añaden dos protecciones: snapshot sin historial y detector automático de specs que delatan la solución. En los pipelines públicos, solo ~20 % de los PRs que tocan tests acaban siendo tareas válidas [Probable]: para 30 tareas hacen falta unos 150 PRs candidatos. La primera comparación de F0 tiene cinco brazos, diseñados para separar el efecto del agente del efecto del modelo. El equipo orca-roles queda fuera porque no puede ejecutarse desatendido.

## 1. Runner

- **Harbor** (Apache-2.0, v0.25.0 del 2026-10-25, commit del 2026-10-31) [Cierto] como runner de la matriz: formato de tarea propio y `--n-concurrent`. Los agentes `claude-code`, `codex`, `opencode` y `mini-swe-agent` ya vienen integrados ([ADR-0001](adr/0001-harness-runner.md)). Lo cierra el spike 1.
- **Uso de Harbor**: solo se le encarga la **fase de generación** y la extracción del diff. Su verificador «separado» (`environment_mode = "separate"`) corre en el mismo host Docker [Cierto en la documentación de tareas de Harbor]. Eso no cumple la tesis 2, así que el verificador de Harbor solo ejecuta los tests visibles como señal temprana (no decisiva) y exporta el diff como artefacto. **El veredicto lo da el verificador de Hetzner** ([05](05-verification-design.md)).
- **Formato de tarea de Harbor**: `instruction.md`, `task.toml` (schema 1.4), `environment/` (Dockerfile), `solution/solve.sh` y `tests/test.sh`. La recompensa va en `/logs/verifier/reward.txt` o `reward.json` [Cierto]. La parte de la tarea que se replica a la torre **no lleva `solution/` ni los tests ocultos**: `solution/` queda vacío y `tests/` solo tiene los tests visibles. Un conversor genera la tarea de Harbor a partir de la tarea OpenSpec.

## 2. Receta de minado de PRs fusionados

Se basa en el pipeline de colección de SWE-bench ([SWE-bench/SWE-bench](https://github.com/SWE-bench/SWE-bench), MIT; `swebench/collect/utils.py` y `grading.py`) [Cierto] y en SWE-rebench V2 ([arXiv 2602.23866](https://arxiv.org/abs/2602.23866); código en [SWE-rebench/SWE-rebench-V2](https://github.com/SWE-rebench/SWE-rebench-V2), MIT) [Cierto]. Cambia en los cuatro puntos marcados con ★.

| Paso | Qué hace | Criterio de descarte |
|---|---|---|
| 1. Candidatos | PRs fusionados en la rama principal, de los últimos 18 meses, con un ticket enlazado o una descripción ≥ 2 frases | Sin descripción ni ticket; PRs de bots y de dependencias (salvo en C5) |
| 2. Clasificación | Clase de tarea C1–C5 por ficheros tocados y etiquetas (§4) | Toca auth, facturación, infraestructura o migraciones, o la clase no es elegible |
| 3. Separación | El diff del PR se parte en *parche de tests* (rutas que contienen `test`, `tests`, `e2e`, `testing`, `__tests__`, `*.spec.*`, `*.test.*`) y *parche de código* (el resto). Es la heurística de SWE-bench ampliada a JS/TS [Cierto para SWE-bench] | Sin parche de tests |
| 4. Entorno | Dockerfile en el **commit base** (`merge-base` del PR) con dependencias del lockfile de la base, instaladas con los scripts de instalación desactivados donde se pueda (T11) | La imagen no construye en 2 intentos. En SWE-rebench V2 solo ~20 % de los repos construyen al primer intento [Probable] |
| 5. Ejecución en la base | Los tests del parche de tests sobre la base, **3 veces** | — |
| 6. Ejecución con el gold | El parche de código + el parche de tests, **3 veces** | — |
| 7. Derivación | **FAIL_TO_PASS** = tests que fallan (o no existen) en la base en las 3 ejecuciones y pasan con el gold en las 3. **PASS_TO_PASS** = tests de los ficheros tocados y sus vecinos que pasan en la base y con el gold en las 3 | F2P vacío; cualquier test que cambie de estado entre repeticiones (flaky). SWE-rebench V2 descartó por flaky 970 de 33 049 instancias, ~3 % [Probable] |
| 8. ★ Snapshot | Para la parte visible: `git archive <base>` → `git init` nuevo → un único commit, sin remotos, tags ni objetos futuros. SWE-bench hace un *clone timesafe* (quita `origin`, borra tags posteriores, `reflog expire`, `gc --prune` y falla si queda algún commit posterior en `--all`) [Cierto, `docker_utils.py`]. El snapshot es más fuerte porque no queda nada que limpiar | — |
| 9. ★ Spec | `proposal.md` y `specs/` de OpenSpec se escriben a partir del ticket y la descripción del PR. Un modelo los redacta **sin ver el parche gold** y una persona los revisa (~10 min por tarea [Suposición]) | La persona no puede escribir el comportamiento esperado sin describir la implementación |
| 10. ★ Detector de fuga en el spec | Determinista: falla si el spec contiene identificadores (funciones, clases, constantes, rutas) que aparecen **solo** en las líneas añadidas del gold y no en la base | Fuga sin corregir. En SWE-rebench V2, el 23 % de las tareas derivadas de PRs tenían fuga [Probable] |
| 11. ★ Partición | Lo visible (spec, `visible_tests`, Dockerfile) va al almacén de tareas replicado. Lo oculto (parche de tests, listas F2P/P2P, gold) solo al almacén del verificador | — |

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
| El modelo vio el repo en su preentrenamiento | Bajo: los repos piloto son privados [Probable] | Se registra si algún repo tuvo un espejo público. Si lo tuvo, se aplica el corte temporal: solo PRs posteriores a la fecha de corte de conocimiento declarada por cada modelo |
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
| **C3 · Refactor sin cambio funcional** | Reestructura sin cambiar el comportamiento | P2P amplio (≥ 20 tests en los ficheros tocados); mutation sobre el código tocado | P2P + mutation sin empeorar + M7a/M7b mejoran o se mantienen | Solo con M7 sólida |
| **C4 · Solo tests** | Añade tests a código existente | No toca código de producción | Los tests nuevos pasan en la base; el mutation score sobre el código cubierto sube | Sí (bajo riesgo) |
| **C5 · Dependencias** | Sube versiones dentro de un rango menor o de parche | Hay lockfile; la suite pasa en la base | P2P completo + build | Más tarde (cadena de suministro) |
| Excluidas | Autenticación, facturación, infraestructura, migraciones de datos, contratos públicos | — | — | Nunca |

Una clase necesita **≥ 8 tareas** en el conjunto de F0 para reportarse por separado. Con menos, solo cuenta en el agregado [Suposición: con menos de 8 tareas el IC es demasiado ancho para leer nada].

## 5. Primera comparación (F0)

### Brazos

| Brazo | Ejecutor | Modelo (alias) | Repeticiones (k) | Qué aísla |
|---|---|---|---|---|
| **A1 · Baseline** | Claude Code 2.1.316 | Sonnet vía la API de Anthropic | 3 (de pago) | Referencia |
| **A2** | Codex CLI 0.166.0 | GLM vía z.ai (puente Responses de LiteLLM) | 5 | Codex frente a A1, con otro modelo |
| **A3** | OpenCode 1.19.5 | GLM vía z.ai | 5 | **Efecto del ejecutor** con el modelo fijo (A2 frente a A3) |
| **A4** | OpenCode 1.19.5 | Qwen local en la 5090 (clase Qwen3.6-35B-A3B, parser `qwen3_coder`) | 5 | **Efecto del modelo** con el ejecutor fijo (A3 frente a A4) |
| **A5** | mini-swe-agent 2.4.6 | El mismo Qwen local | 5 | **Efecto del harness** con el modelo fijo (A4 frente a A5) |

- **Total**: 30 × (3 + 4 × 5) = **690 ejecuciones**. El coste real solo lo pone A1: 90 ejecuciones a 1–3 USD, entre 90 y 270 USD [Suposición].
- **Concurrencia**: A2 y A3 van con ≤ 4 en paralelo, porque z.ai devuelve 429 con más de ~6 concurrentes [Cierto, medido en otro proyecto del propietario]. A4 y A5 dependen de vLLM en una sola GPU [Suposición: ~4 secuencias concurrentes con contexto de 64k].
- **Tiempo de pared estimado**: 1–2 días de ejecución desatendida [Suposición].
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
- **Informe por brazo**: pass@1, pass^k, M1.gen, M1.total, tasa de `error`, tasa de aborto, M7a/b/c y la distribución de tiempos.
- **Un fallo de infraestructura no es un fallo del brazo**: un 429, un contenedor que no arranca o un timeout del verificador se repiten y se reportan aparte.

## 6. Ciclo de vida del conjunto de tareas

- **Congelado**: las 30 tareas de F0 forman el conjunto congelado v1 (M8). No se modifican; una tarea con un defecto descubierto se retira y se registra.
- **Rotativo**: el minado mensual de PRs nuevos alimenta el conjunto rotativo y las canarias.
- **Auditoría**: cada trimestre una persona revisa 10 tareas al azar (spec, F2P y gold), siguiendo la lección de la auditoría de OpenAI sobre SWE-bench Verified ([post](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/)).

## Decisiones abiertas

- Qué modelo local exacto y con qué cuantización. Depende de la memoria que deje libre el contexto de 64k en 32 GB [Suposición]. Se fija en F0-03.
- Si el conjunto de F0 debe incluir tareas de los tres repos o solo de los dos con más rendimiento. Lo decide la medición de F0-05.
- La tarifa sombra exacta por modelo: hay que documentarla con fuente y fecha en la configuración del gateway.
