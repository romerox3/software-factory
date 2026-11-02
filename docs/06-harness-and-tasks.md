# 06 · Harness y tareas

> **Resumen.** El harness ejecuta *tareas × brazos × repeticiones* sobre Harbor y entrega cada diff al verificador aislado. **Las tareas de F0 son públicas y recientes**: se importan de los splits de 2026 de SWE-rebench y SWE-bench-Live (Python y TS) y se revalidan en nuestro entorno (gold 3/3, base en rojo 3/3, sin flaky, snapshot sin historial). El código del piloto entra en F1, como issues reales. La receta de minado de PRs queda para F1+. Hay seis brazos, comparados con k = 3, y orca-roles queda fuera porque no corre desatendido.

## 1. Runner

- **Harbor** (Apache-2.0, v0.25.0 del 2026-10-25, commit del 2026-10-31) [Cierto] como runner de la matriz: formato de tarea propio y `--n-concurrent`. Los agentes `claude-code`, `codex`, `opencode` y `mini-swe-agent` ya vienen integrados ([ADR-0001](adr/0001-harness-runner.md)). Lo cierra el spike 1.
- **Uso de Harbor**: solo se le encarga la **fase de generación** y la extracción del diff. Su verificador «separado» (`environment_mode = "separate"`) corre en el mismo host Docker [Cierto en la documentación de tareas de Harbor]. Eso no cumple la tesis 2, así que el verificador de Harbor solo ejecuta los tests visibles como señal temprana (no decisiva) y exporta el diff como artefacto. **El veredicto lo da el verificador de Hetzner** ([05](05-verification-design.md)).
- **Formato de tarea de Harbor**: `instruction.md`, `task.toml` (schema 1.4), `environment/` (Dockerfile), `solution/solve.sh` y `tests/test.sh`. La recompensa va en `/logs/verifier/reward.txt` o `reward.json` [Cierto]. La parte de la tarea que se replica a la torre **no lleva `solution/` ni los tests ocultos**: `solution/` queda vacío y `tests/` solo tiene los tests visibles. Un conversor genera la tarea de Harbor a partir de la tarea OpenSpec.

## 2. Fuentes de tareas

| Fase | Fuente | Por qué |
|---|---|---|
| **F0** | **Tareas públicas recientes** (§2.1) | F0 mide el harness y compara brazos, y para eso da igual de quién sea el código, siempre que la tarea sea posterior al corte de los modelos y del stack que interesa. Sin datos del cliente, F0 no depende de S3, S4 ni D1 ([09](09-open-questions.md)); los peones trabajan con tareas reales; y el conjunto congelado de M8 se puede publicar |
| **F1+** | **Issues reales del piloto** (pipeline issue → PR en borrador) y PRs minados del piloto (S3 confirmado el 2026-11-01) para el conjunto rotativo (§2.2) | M3, M4 y M6 solo existen donde una persona revisa y fusiona. La autonomía (F3) se gana en el repo donde se fusiona el código |

F0 no dice nada concreto sobre el código del piloto: lo dice F1. **Ninguna decisión de autonomía se toma con datos de F0.**

### 2.1 F0: importar y revalidar tareas públicas

- **Fuentes**, fijadas por la revisión (commit) del dataset en Hugging Face. Datos de la API de HF del 2026-10-31 [Cierto]:
  - [`nebius/SWE-rebench-leaderboard`](https://huggingface.co/datasets/nebius/SWE-rebench-leaderboard) (CC-BY-4.0). Un split por mes: el último, `2026_03`, tiene 110 tareas creadas entre el 2026-03-01 y el 2026-05-12. Trae F2P/P2P, la imagen Docker de cada tarea y columnas `harbor_*`. Aporta **~20 tareas Python** [Probable que todo el split sea Python; se comprueba en F0-05].
  - [`SWE-bench-Live/MultiLang`](https://huggingface.co/datasets/SWE-bench-Live/MultiLang), split `ts` (MIT): 111 tareas creadas hasta el 2026-04-20. Aporta **~10 tareas TS**.
  - Respaldo, si no hay bastantes tareas posteriores al corte: los splits mensuales siguientes que se publiquen y el split `js` de MultiLang (108).
- **Selección**:
  - las tareas más recientes de cada fuente (sin filtro de corte en F0, §3);
  - clasificadas como C1 o C2 según el tamaño del gold (§4);
  - se descartan las de repos excluidos por clase (auth, facturación, infraestructura);
  - el muestreo es aleatorio con semilla fijada dentro de lo elegible.
- **Revalidación en nuestro entorno**: se aplican los pasos 4–8, 10 y 11 de la receta de §2.2. La imagen sale del dataset, fijada por digest, en lugar de construirse.
  - Gold 3/3 y base en rojo 3/3.
  - F2P y P2P **se vuelven a derivar** en nuestro entorno; los del dataset no se aceptan tal cual.
  - Se descartan los flaky.
  - El snapshot se hace `fresh-init` a partir del directorio del repo de la imagen.
  - Las tareas con fuga en el enunciado **se descartan**, no se reescriben.
- **Spec**: `proposal.md` es el enunciado del issue tal cual, más el campo `interface` donde lo haya. No hay reescritura humana. Se audita una muestra de 10 tareas.
- **Lo oculto no va al repo**: el parche de tests, el gold y las listas F2P/P2P viven en el almacén del verificador. El repo solo guarda un manifiesto (`tasks/public-v1.manifest.json`) con el dataset, su revisión, los `instance_id` y los digests de las imágenes. Así el conjunto se reproduce sin redistribuir nada y se cumple la atribución de CC-BY-4.0.
- **Contaminación**: el gold y los tests de estas tareas están publicados en internet. Para el generador están ocultos porque no tiene red, pero un modelo los pudo ver al entrenar si la tarea es anterior a su corte. Por eso las comparaciones entre modelos distintos llevan la etiqueta de §3 y el conjunto se renueva con los splits nuevos.
- **Calibración (informativa)**: SWE-rebench publica el porcentaje resuelto por modelo en cada ventana, con su propio scaffold [Probable]. Si A1 se queda > 15 puntos por debajo de la cifra publicada del mismo modelo en las mismas tareas, se revisa el harness antes de leer resultados. No es un criterio de salida, porque el scaffold es distinto.

### 2.2 Receta de minado de PRs fusionados (F1+, piloto)

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
- **Si en F1+ se mina el piloto, una medición de elegibilidad por repo va antes de comprometer tareas.**

### Fuera del minado: síntesis

Si no hay 30 tareas válidas, ni públicas posteriores al corte ni minadas, se completa con **inyección de bugs al estilo SWE-smith** ([arXiv 2504.21798](https://arxiv.org/abs/2504.21798); [SWE-bench/SWE-smith](https://github.com/SWE-bench/SWE-smith), MIT): se reescribe una función con un bug y se usan como F2P los tests existentes que pasan a fallar. El rendimiento de validación de SWE-smith fue del 50,1 % [Probable].

Las tareas sintéticas se etiquetan `synthetic`, se reportan aparte y no cuentan para el criterio de salida de F0. Sesgo conocido: sobrerrepresentan bugs pequeños y locales.

## 3. Contaminación y corte temporal

| Vector | Riesgo en este proyecto | Control |
|---|---|---|
| El modelo vio el repo, el gold o los tests en su preentrenamiento | **Alto en F0** (tareas públicas); bajo en las del piloto (repos privados) [Probable] | **Etiqueta por comparación, no filtro** (decisión del propietario del 2026-11-01; sustituye al «corte único para todos los brazos»). F0 mide la factory: salud del arnés, verificador y efecto del ejecutor con el modelo fijo (A2 frente a A3 y A4 frente a A5), y ahí la contaminación afecta por igual a los dos brazos. Las comparaciones entre modelos distintos (A1 frente a A2, A3 frente a A4) y el pass@1 absoluto se publican con la etiqueta «posible contaminación», con las fechas: Sonnet 5.5 declara su «reliable knowledge cutoff» en junio de 2026 [Cierto, system card §1.1]; GLM-5.3 se publicó el 2026-08-25 sin corte declarado [Cierto, HF]; Qwen3.6, el 2026-04-15 [Cierto, HF]. Ninguna tarea pública es posterior a mayo de 2026 [Cierto, 2026-11-01], así que el filtro dejaba F0 sin tareas. **El modelo para F1 se elige con tareas del piloto**, que son privadas. En el piloto, el corte solo se aplica si algún repo tuvo un espejo público |
| El agente lee la solución en el historial | Alto sin control (T15) | Snapshot fresh-init (paso 8) + prueba `leak-git-history` |
| El agente la descarga de la red (T16) | Alto sin control | Red solo hacia el gateway |
| El spec delata la solución | Medio: 23 % en SWE-rebench V2 [Probable] | Pasos 9 y 10 |
| Los prompts se ajustan a las tareas del conjunto congelado (Goodhart) | Medio con M8 | Conjunto rotativo + canarias que rotan ([05](05-verification-design.md) §7) |
| Las tareas del piloto (F1+) acaban en el repo público | Alto si se mezclan | [ADR-0009](adr/0009-data-policy-per-repo.md) + hook de pre-commit |

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

**Tipos de trabajo añadidos en el rediseño** ([ADR-0012](adr/0012-stage-chain-and-profiles.md)). No son clases de tarea sueltas, sino unidades de trabajo que recorren varias etapas:

| Tipo | Descripción | Etapas | Oráculo | Evidencia externa |
|---|---|---|---|---|
| **C6 · Migración** | Cambio mecánico en muchos ficheros (librería, API, versión de framework) | E2–E6 | Suite + compilador + linters, por fichero | Google: 74,45 % de 595 cambios generados por LLM; Airbnb: 97 % de ~3 500 ficheros en 4 días [Cierto] |
| **C7 · Seguridad** | Arreglo de una vulnerabilidad detectada por un escáner | E2–E6 | Escáner que deja de detectarla + tests + fuzzing donde lo haya | CodeMender, Copilot Autofix [Cierto] |
| **C8 · Épica** | Feature grande en un producto existente | E2–E7 | Escenarios ocultos de la épica sobre lo desplegado | — |
| **C9 · Producto nuevo** | Software desde cero a partir de una spec (primer perfil: app web interna) | E2–E7 | El oráculo del perfil (§7) | Vibe Code Bench: 61,8 % de recorridos ocultos [Cierto] |

Una clase necesita **≥ 8 tareas** en el conjunto de F0 para reportarse por separado. Con menos, solo cuenta en el agregado [Suposición: con menos de 8 tareas el IC es demasiado ancho para leer nada].

## 5. Primera comparación (F0)

### Brazos

| Brazo | Ejecutor | Modelo (alias) | Repeticiones (k) | Qué aísla |
|---|---|---|---|---|
| **A1 · Baseline** | Claude Code 2.1.316 | Sonnet con la suscripción del propietario (a través del gateway si reenvía el OAuth; si no, salida directa, [04](04-executor-contract.md) §5.1) | 3 (gasta cuota del plan) | Referencia |
| **A6** | Claude Code 2.1.316 | GLM vía z.ai (`/v1/messages` de LiteLLM) | 5 | **Efecto del modelo con Claude Code fijo** (A1 frente a A6) y **efecto del ejecutor con GLM fijo** sin puente Responses (A6 frente a A3) |
| **A2** | Codex CLI 0.166.0 | GLM vía z.ai (puente Responses de LiteLLM) | 5 | Codex **más el puente** frente a A3. Codex solo admite `wire_api = "responses"`, así que el efecto del puente no se puede separar del de Codex con GLM: forma parte del brazo |
| **A3** | OpenCode 1.19.5 | GLM vía z.ai | 5 | **Efecto del ejecutor** con el modelo fijo (A2 frente a A3) |
| **A4** | OpenCode 1.19.5 | Modelo local en la 5090: **Nanbeige4.3-33B** INT4 (2026-10-28, Apache 2.0; vLLM con `--reasoning-parser qwen3 --tool-call-parser qwen3_coder`), revisión fijada en F0-03 (decisión del propietario del 2026-11-02) | 5 | **Efecto del modelo** con el ejecutor fijo (A3 frente a A4) |
| **A5** | mini-swe-agent 2.4.6 | El mismo modelo local | 5 | **Efecto del harness** con el modelo fijo (A4 frente a A5) |

- **Total**: 30 × (3 + 5 × 5) = **840 ejecuciones**. En F0 no hay coste real, porque A1 usa la suscripción y los brazos de GLM el coding plan. **El límite es la cuota**:
  - A1 son 90 ejecuciones (90–270 USD a precio de lista [Suposición]) sobre la suscripción que el propietario también usa a diario.
  - A2, A3 y A6 suman 450 ejecuciones del coding plan, que comparten con los peones. Una tarea grande de GLM (~50 min y 283 K de contexto) consumió 22 puntos de la ventana de 5 h [Cierto, medición propia con n = 1]. Si las tareas de la matriz fueran de ese tamaño, entrarían unas 4 por ventana [Probable].
  - El spike B mide el porcentaje de ventana por ejecución en los dos planes. Con ese dato se decide si los brazos de z.ai bajan a k = 3 (270 ejecuciones), si los peones pasan a otro proveedor mientras corre la matriz y si la matriz corre solo de noche ([09](09-open-questions.md) S18).
- **Las comparaciones entre brazos usan las 3 primeras repeticiones de cada brazo** (pass@1, pass^3 y M1 con el mismo k). Las repeticiones 4 y 5 de los brazos sin coste real solo sirven para estimar pass^5 y la varianza dentro de cada brazo; nunca se comparan con A1.
- **Concurrencia**: A2, A3 y A6 comparten ≤ 4 en paralelo **entre los tres**, porque z.ai devuelve 429 con más de ~6 concurrentes [Cierto, medido en otro proyecto del propietario]. A4 y A5 dependen de vLLM en una sola GPU [Suposición: ~4 secuencias concurrentes con contexto de 64k]. A1 corre de una en una, para no agotar la ventana de la suscripción en una oleada.
- **Tiempo de pared estimado**: 2–3 días de ejecución desatendida [Suposición].
- **Los brazos se limitan a los proveedores permitidos para el piloto** (5090, z.ai, Anthropic), aunque las tareas de F0 sean públicas, para que lo aprendido en F0 se aplique tal cual en F1.
- **A2′ · Codex × un modelo de OpenAI**: descartado por el propietario el 2026-11-01. OpenAI tampoco está autorizado para el piloto (D1).
- Los brazos con modelo local o de cuota usan **coste sombra**: el precio de lista de un modelo equivalente publicado por el proveedor (GLM, el precio de su API de pago; modelo local, el precio por token de un proveedor que lo sirva), configurado en el gateway y declarado en el informe.

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

- **Congelado**: las 30 tareas públicas de F0 forman el conjunto congelado v1 (M8), que se congela al terminar F0-18. **Es publicable**: el manifiesto vive en el repo y cualquiera puede reproducir la CI de la factory. No se modifican; una tarea con un defecto descubierto se retira y se registra. En F2 crece hasta ≥ 80 tareas para bajar el margen de no-inferioridad de M8 a 10 puntos ([01](01-metrics.md) §3).
- **Rotativo**: cada split mensual nuevo de los datasets públicos alimenta el conjunto rotativo y las canarias. Desde F1, también los PRs minados del piloto.
- **Caducidad del congelado**: cuando un brazo nuevo use un modelo con un corte posterior a las tareas del congelado, ese congelado deja de servir para ese brazo y se crea uno nuevo (v2) con splits posteriores.
- **Auditoría**: cada trimestre una persona revisa 10 tareas al azar (spec, F2P y gold), siguiendo la lección de la auditoría de OpenAI sobre SWE-bench Verified ([post](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/)).

## 7. Perfiles de software y sus oráculos

Un **perfil** agrupa lo que depende del tipo de software ([ADR-0012](adr/0012-stage-chain-and-profiles.md)):

| Parte | Qué define | Ejemplo en app web |
|---|---|---|
| Entorno | Cómo se construye y ejecuta | Contenedores de app + base de datos, con datos semilla |
| Oráculo | Cómo se comprueba que funciona | Escenarios ocultos que recorre un agente de navegador sobre la app desplegada |
| Despliegue | Dónde y cómo se publica | Staging en la torre; en la fase C, el del piloto tras una feature flag |

**Admisión de un perfil** (fase D de [07](07-roadmap.md)):
- su oráculo detecta ≥ 90 % de los **defectos sembrados** (variantes de software correcto con un fallo puesto a propósito);
- la concordancia con revisión humana es ≥ 85 %;
- la cota de trampa en sus canarias es ≤ 10 %.

Mientras no se cumpla, E5 de ese perfil lleva puerta humana.

**Oráculo del perfil app web (fase B)**:
1. **Escenarios**: recorridos de usuario en lenguaje natural con resultado esperado comprobable («crear un pedido con dos líneas y ver el total correcto en el listado»). Los visibles van en la spec. Los ocultos los escribe un proceso aparte a partir de la spec aprobada, sin acceso al código ni al constructor.
2. **Ejecución**: un agente de navegador recorre cada escenario sobre la app desplegada y da un veredicto por paso. Un escenario pasa si pasan todos sus pasos.
3. **Calibración**: antes de confiar en el oráculo se mide con apps de referencia correctas (no debe dar falsos fallos) y con defectos sembrados (debe detectarlos). La concordancia entre evaluadores de navegador puede ser muy baja: Vibe Code Bench informa de entre el 31,8 y el 93,6 % por paso según el evaluador [Cierto]. Por eso M10 y la auditoría humana van antes que cualquier resultado de la factory.
4. **Trampas propias del perfil**:
   - detectar el agente de navegador y servirle otra cosa;
   - datos semilla preparados para los escenarios visibles;
   - rutas que solo existen en staging.

   Se cubren con canarias de producto y con escenarios ocultos que usan datos distintos de los visibles.

**Perfiles candidatos para la fase D** y fuerza de su oráculo: API o servicio (tests de contrato y escenarios contra la API, fuerte), CLI o librería (suite y comparación con una implementación de referencia, fuerte), pipeline de datos (salidas frente a datos de referencia, fuerte si los hay), producto con IA (evaluaciones y jueces, medio), móvil o escritorio (recorridos con emulador, medio), juegos, UX y contenido (personas, débil).

## Decisiones abiertas

- Qué modelo local exacto y con qué cuantización. Depende de la memoria que deje libre el contexto de 64k en 32 GB [Suposición]. Se fija en F0-03.
- La proporción Python/TS (20/10 por defecto, aproximando el stack del piloto) y si subir n de 30 a 50. Subirlo solo cuesta más ejecuciones de A1 (~60–180 USD más) y baja el efecto mínimo detectable a ~13 puntos ([01](01-metrics.md) §3).
- La tarifa sombra exacta por modelo: hay que documentarla con fuente y fecha en la configuración del gateway.
