# 09 · Supuestos y preguntas abiertas

> **Resumen.** Recoge los supuestos con los que se escribió el plan, las preguntas que debe responder el propietario y los hallazgos de la revisión independiente que no se incorporaron, cada uno con su argumento. Las tres decisiones que más trabajo bloquean están en §1. **F0 no usa código del cliente**: S3, S4 y D1 solo bloquean F1. Ningún supuesto bloquea el arranque de F0-01, F0-02, F0-05, F0-06, F0-08, F0-09 ni F0-11.

## 1. Decisiones que necesita tomar el propietario

| # | Decisión | Opciones | Qué bloquea | Recomendación |
|---|---|---|---|---|
| D1 | **¿Pueden ver código del piloto OpenAI, NaN u OpenRouter?** | Ninguno (por defecto) · solo OpenAI con retención cero · otros | El brazo «Codex con modelo de OpenAI» **desde F1**. En F0 no bloquea nada: las tareas son públicas ([ADR-0009](adr/0009-data-policy-per-repo.md)) | **Decidido el 2026-11-01: NaN y OpenRouter, sí; OpenAI, no.** A2′ también queda descartado en F0 |
| D2 | **Licencia de orca-role-hook** | Pedir a Felipe Castaño Apache-2.0 o MIT · no pedir nada | Solo un eventual port de `verify_task.py` o `crosscheck.sh`. El diseño no lo necesita ([ADR-0007](adr/0007-orca-role-hook.md)) | **Decidido el 2026-11-01: se reimplementan ideas y no se espera la licencia.** Recomendación original: pedirla de todos modos para poder citar o portar sin dudas. Preguntarle además si los commits firmados con su correo de Vicomtech (3, todos en `bin/agent.sh`) tienen alguna reclamación de su empleador. Ningún otro activo candidato tiene commits de ese correo |
| D3 | **¿Aceptas que F3 dependa del volumen (≥ 150 cambios por clase) y no del calendario?** | Sí · bajar el umbral (por ejemplo, 60 cambios → cota ~5 %) | El criterio de [ADR-0008](adr/0008-gates-and-auto-merge.md) | **Decidido el 2026-11-01: sí, por volumen.** Bajar el volumen sube la cota de regresiones aceptada, y eso es una decisión de riesgo, no técnica |

## 2. Supuestos con los que se escribió el plan

| # | Supuesto | Origen | Cómo se cierra |
|---|---|---|---|
| S1 | El repo es Apache-2.0, privado durante la construcción y público al validarse, sin rastro del piloto | Respuesta del propietario (2026-10-31) | — |
| S2 | **F0 usa solo tareas públicas recientes** (SWE-rebench y SWE-bench-Live, [06](06-harness-and-tasks.md) §2.1). Los tres repos de producto del piloto entran en F1, con la regla «sin repos de clientes» levantada para ellos | Respuesta del propietario (2026-10-31) | — |
| S3 | **Uso del código del cliente como dataset de evaluación (F1+)**: la política verificada del propietario cubre qué proveedores de modelos pueden ver ese código, **no su uso como benchmark**, ni guardar tareas, holdouts y trayectorias derivadas | Hueco detectado | **Confirmado por el propietario el 2026-11-01**: el contrato lo permite. Desde F1 se pueden minar PRs del piloto |
| S4 | **El evaluador en Hetzner puede alojar código del cliente (F1+)** (mirror, tests ocultos) | Hueco detectado | **Confirmado por el propietario el 2026-11-01**, con una condición: el servidor se comparte con el gateway y con otros servicios, así que el verificador usa Docker rootless y un volumen propio ([02](02-architecture.md) §2, requisito de entrada de F1) |
| S5 | Sin tope mensual. Presupuesto por ejecución + coste sombra + alarma a los 300 USD de gasto real en Anthropic. En F0 la alarma no tiene objeto, porque no hay gasto real (A1 va con suscripción) | Respuesta del propietario | — |
| S6 | El baseline Claude Code usa **Sonnet** (versión vigente, fijada) | Juicio propio: el prompt fija el agente, no el modelo | **Confirmado por el propietario el 2026-11-01**: Sonnet. Opus no, porque gasta varias veces más cuota de la suscripción |
| S7 | Documentación en español; código e identificadores en inglés | Respuesta del propietario | — |
| S8 | **Tipo del servidor Hetzner** | **Cerrado el 2026-11-01**: Cloud, sin `/dev/kvm`, 16 vCPU y 30 GB, compartido con el gateway y con servicios de otros proyectos [Cierto] | F2 necesita otra máquina si se activa el [ADR-0003](adr/0003-sandbox.md). Falta comprobar `/dev/kvm` en la torre |
| S9 | Qué es «aitire» (proveedor del gateway mencionado por el propietario) | Desconocido | **Cerrado el 2026-11-01**: según el propietario, no se aplica a la factory. No entra en la matriz de [02](02-architecture.md) §8 |
| S10 | La instancia compartida del gateway admite equipos dedicados sin interferir con otros usos. El host también corre servicios de otros proyectos, que compiten por CPU con el verificador | Juicio propio | F0-03 y F0-21 |
| S11 | La torre tiene un kernel con nftables `fib inet`, así que el control de egress de Harbor funcionará allí | [Probable]: falla en macOS | **Cerrado el 2026-11-01**: funciona en la torre (kernel 7.0, Docker 29.7.2, Harbor 0.25.0), y la lista blanca por hostname filtra por SNI [Cierto] |
| S12 | El modelo local es **Nanbeige4.3-33B** (decisión del propietario del 2026-11-02). La versión INT4 ocupa 22,6 GB [Cierto, ficha de HF]; con 32 GB queda poco sitio para la caché KV y hay que medir si caben 64k de contexto [Probable]. Las cifras de agentes son todas del laboratorio [Cierto] | [Probable] | F0-03 |
| S13 | El minado del piloto rinde ~20 % de los PRs que tocan tests, como SWE-bench. Ya no afecta a F0: solo importa si en F1+ se mina el piloto | [Probable] por analogía | Una medición de elegibilidad en F1, si S3 lo permite |
| S16 | El split `2026_03` de SWE-rebench-leaderboard es todo Python y hay ≥ 30 tareas posteriores al corte de los modelos de los brazos. Algunos modelos no publican su corte | [Probable] | F0-05 y F0-17 |
| S17 | Las licencias de los datasets (CC-BY-4.0 y MIT) permiten usarlos para evaluar y publicar el manifiesto con atribución. Los repos de origen tienen sus propias licencias, pero no se redistribuye su código | [Probable] | Revisión de las *dataset cards* en F0-05 |
| S14 | Tipo de la cuenta de z.ai que usa el gateway | Revisión independiente | **Cerrado el 2026-11-01**: es un coding plan, y el propietario retira la regla «nunca planes de consumo en ejecuciones automáticas». La cuenta de Anthropic también es de suscripción. Queda el riesgo de cuota (S18, R21) |
| S18 | **La cuota de los dos planes basta para la matriz en un plazo razonable** (90 ejecuciones de A1 y 450 de z.ai, compartidas con los peones) | [Suposición] | **Pendiente**: se decide con el porcentaje de ventana por ejecución medido en el spike B. Opciones: k = 3 en z.ai, peones en otro proveedor mientras corre la matriz y matriz de noche. Se pregunta al propietario con ese dato |
| S15 | `/spend/logs` por key está en LiteLLM OSS y da los tokens por petición | [Probable] | F0-03 |

## 3. Evidencia nueva contra una tesis (pide validación)

- **Tesis 8, DOT compatible con Attractor**. A fecha del 2026-10-31:
  - el spec Attractor no tiene commits desde marzo;
  - Tracker marca su parser DOT como deprecado en favor de `.dip`, que no tiene licencia;
  - Kilroy está parado desde abril.

  **Cerrado el 2026-11-01**: después de investigar las alternativas, el propietario elige un **YAML propio con JSON Schema**. DOT se genera solo para los diagramas, y Serverless Workflow 1.0 queda como destino de traducción ([ADR-0002](adr/0002-orchestrator.md) §4).

- **Corte único para todos los brazos ([06](06-harness-and-tasks.md) §3)**. El 2026-11-01, al empezar F0-17, se comprueba que ninguna tarea pública es posterior a mayo de 2026. Con el corte en junio (Sonnet 5.5) o en agosto (GLM-5.3), F0 se quedaba sin tareas.

  **Cerrado el 2026-11-01**: el propietario señala que F0 mide la factory y no el nivel de los modelos. El corte pasa de filtro a etiqueta: las comparaciones con el mismo modelo valen, y las que cruzan modelos (y el pass@1 absoluto) llevan «posible contaminación». El modelo para F1 se elige con tareas del piloto.

- **El repo de una tarea real no vive en `/workspace`** (hallado el 2026-11-01 al preparar F0-17, en la imagen de una tarea de SWE-rebench) [Cierto]:
  - El `WorkingDir` es `/testbed`, con el paquete instalado en modo editable en el entorno conda de la imagen. El runner, el sandbox del verificador y `to_harbor` montaban o dejaban el código en `/workspace`, así que los tests habrían ejecutado el código de la imagen y no el del candidato.
  - `to_harbor` no copiaba el snapshot. El agente habría trabajado sobre `/testbed`, que trae el historial completo (T15).
  - Arreglo (F0-17a): un campo `repo.workdir` (por defecto `/workspace`), el montaje en ese directorio, los comandos de test del dataset, el informe JUnit en un `/logs/verifier` propio de cada ejecución y un Dockerfile que hace checkout de la base y sustituye el `.git` de la imagen por el del snapshot.
  - **Coste aceptado**: montar encima del directorio de la imagen oculta los artefactos compilados en su sitio (extensiones en C). Esas tareas dan rojo en la base y en el gold, y la revalidación las descarta (falla de forma cerrada). Se mide cuánto rendimiento se pierde en F0-17.
  - En el `ts` de MultiLang, jest necesita `jest-junit`, que no está en las imágenes y no se puede instalar sin red. En F0 entran solo pytest y vitest: 46 tareas vitest frente a 12 jest en el split [Cierto].
  - **Cerrado el 2026-11-01** (commits hasta `db4513e`). La primera ejecución real en la torre destapó tres defectos más que los tests en macOS no veían [Cierto]:
    - Los datasets de Hugging Face guardan cada split como `data/<split>-*.parquet`, no como carpeta.
    - Los ficheros que el contenedor escribe como root en el directorio montado (`__pycache__`) no se pueden borrar desde el host en Linux. Ahora se pasa `PYTHONDONTWRITEBYTECODE=1` y un contenedor corto devuelve la propiedad al usuario del host tras cada ejecución.
    - Los comandos de test de las filas ejecutan ficheros enteros que ya traen tests rotos en la base, así que el verificador rechazaba el gold (exit 1). Se resuelve con «fallos conocidos» ([05](05-verification-design.md) §4, punto 3).
  - Aceptación sobre una tarea real de SWE-rebench (F2P 2, P2P 49, 2 fallos conocidos): el gold da `accept`, el diff vacío `reject` y un cambio ajeno al issue `reject` con F2P 0/2 [Cierto].
  - **La recompensa de Harbor no es un veredicto en tareas reales.** La tarea de Harbor solo lleva los tests visibles, así que los F2P (tests nuevos del PR) no existen dentro del sandbox: el oracle y el agente vacío dan la misma recompensa, 0 [Cierto]. Es así por diseño ([06](06-harness-and-tasks.md) §1). La prueba pendiente de F0-13 (`harbor -a oracle` con recompensa 1) se sustituye por esta: el diff del agente, verificado por el verificador, da `accept`.

## 4. Correcciones al informe de investigación (verificadas en vivo el 2026-10-31)

| Dato del informe | Dato verificado |
|---|---|
| HumanLayer ACE: Apache-2.0, «fork de prompts» | **Sin licencia**: solo referencia |
| Mastra Factory: Apache-2.0 | **Sin licencia** |
| Tracker: «fork/piloto», motor DOT más completo | El parser DOT está **deprecado** (`.dip`); 2 contribuidores principales |
| Kilroy: activo | Último push del **2026-04-27** |
| `anthropic-experimental/sandbox-runtime` | Ahora es `anthropics/sandbox-runtime` |
| `e2b-dev/infra` | Redirige a `e2b-dev/runtime` |
| qodo pr-agent: conflicto MIT/AGPL | `The-PR-Agent/pr-agent`, **MIT** |
| gh-aw: «versiones retiradas» | Es un advisory, no una retirada de releases, y hay 15 advisories entre agosto y octubre |
| `claude -p --output-format json` devuelve `total_cost_usd` [Suposición en el informe] | Documentado en la página headless [Cierto] |
| Codex: proveedor propio con `wire_api` chat o responses | Solo `responses` [Cierto] |

## 5. Hallazgos de la revisión independiente no incorporados

La revisión independiente (un subagente Sonnet que solo recibió las tesis, los criterios de contenido y los documentos) dio 25 hallazgos el 2026-10-31. **Se incorporaron 20 enteros y 5 en parte.** Entre los incorporados están el canal de feedback con lista blanca (T28), el sandbox de la fase de verificación (T29), el diff calculado en el host (T30), las canarias indistinguibles con la tarea-canaria como unidad, la no-inferioridad con Δ, el arranque de M8, la provisión del verificador (F0-21), las clases C3–C5, el brazo A6, la salida de F3 por M4 y M5, y las filas de GitHub y Hetzner.

Lo que no se incorporó, o solo en parte:

| Hallazgo | Qué se hizo | Argumento |
|---|---|---|
| #14 · Añadir un brazo de un segundo proveedor | Solo S14 y R21 | A4 y A5 (modelo local) ya son un segundo proveedor en la comparación. Que los peones dependan de z.ai afecta a cómo se implementa F0, no al sistema que se mide: si z.ai cae, los peones pasan a otro modelo del gateway, siempre con código público |
| #13 · «≥ 95 % de salidas válidas» mide formato y no calidad | Se mantiene, etiquetado como salud del harness, y se añade el techo de `error_infra` | Es intencionado: F0 tiene que demostrar que el harness produce datos utilizables antes de leer la calidad. La calidad la miden los criterios de falsos `accept` y de pass@1 |
| #23 · Los ADR no tienen resumen ni «Decisiones abiertas» | Se añadió «Opciones» a los 5 que no la tenían | El encargo fija el formato de los ADR (contexto, opciones, decisión, consecuencias, cómo revertir). El criterio de resumen y «Decisiones abiertas» es de los documentos 00–09 |
| #24 · A2 frente a A3 queda confundido por el puente Responses | Se declara que el puente forma parte del brazo A2 | No se puede separar: Codex solo admite `wire_api = "responses"`. El efecto del ejecutor sin puente con GLM fijo lo da A6 frente a A3 |
| #17 · F0-02 construye el servicio de emisión aunque 02 lo condicionaba | Se quitó la condición en 02 | El revisor no pudo comprobarlo, pero el rol de *team admin* es de pago en LiteLLM (código leído en v1.86.2, `notas:conocimiento/infra/litellm-gateway-que-se-puede-hacer.md`) [Cierto], así que el servicio hace falta siempre |

- **Aislamiento de los sandboxes para F1** ([ADR-0011](adr/0011-single-host-f0.md)). En F0, agentes y verificador comparten la torre y los separan el proceso y el montaje. Antes de meter código del cliente hay que decidir entre un usuario propio para el verificador, gVisor (plataforma KVM, porque la torre tiene `/dev/kvm`), Kata o una máquina aparte. Dos datos para la decisión:
  - El modo `allowlist` de Harbor usa un sidecar con iptables, y gVisor solo soporta iptables en parte [Cierto, [compatibilidad de gVisor](https://gvisor.dev/docs/user_guide/compatibility/)]. Hay que probarlo.
  - gVisor reduce el coste de las cargas con muchos ficheros (directfs, overlay del rootfs), pero no hay datos medidos de `npm install` ni de `pytest` [Cierto, [blog de gVisor, 2023](https://gvisor.dev/blog/2023/06/27/directfs/)]. Hay que medirlo con las tareas de F0.

- **El diseño solo cubre un tramo de la factory** (2026-11-02). El propietario pregunta si el diseño recoge lo que es una software factory. La investigación (`notas:conocimiento/llm-agentes/software-factory-alcance-etapas-y-productos-completos.md`) muestra que solo cubre «tarea especificada → parche verificado → PR». Faltan [Cierto, por fuente]:
  - lo previo al código: intake, triage, spec y plan;
  - lo posterior: despliegue con puerta, monitorización, e incidentes y feedback como tareas nuevas;
  - la arquitectura como sensor;
  - migraciones y seguridad como clases;
  - los productos completos.

  **Decisión del propietario (2026-11-02): F0 se para y se rediseña la factory entera**, incluida la vía de productos completos. **Cerrado el mismo día**: el propietario aprueba la propuesta ([10](10-rediseno-propuesta.md)): una cadena de ocho etapas, perfiles de software para construir cualquier tipo de software y fases A–D ([ADR-0012](adr/0012-stage-chain-and-profiles.md), [07](07-roadmap.md)). Se conservan, por si se retoman, las 26 tareas Python ya revalidadas (almacén de la torre) y todo el código de `factory/`. El análisis de huecos está en `notas:proyectos/software-factory/analisis/huecos-de-alcance.md`.

## Decisiones abiertas

- D1, D2 y D3 están decididas (2026-11-01, §1).
- S3 y S4 están confirmados (2026-11-01). Queda la condición de S4, que es requisito de entrada de F1.
- S18 (cuota de los planes) se decide antes de F0-18, con la medición del spike B.
