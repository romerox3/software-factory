# 00 · Visión

> **Resumen.** La factory lleva el trabajo de software **desde la intención hasta el producto en producción y de vuelta**, para cualquier tipo de software. Es una cadena determinista de ocho etapas: entrada, spec, plan, implementar, verificar, integrar, desplegar y operar. Cada etapa tiene su forma de comprobar el resultado y su punto de decisión humana. Lo que depende del tipo de software (entorno, oráculo y despliegue) va en **perfiles** intercambiables, igual que los ejecutores. La autonomía se gana por etapa, por tipo de trabajo y por perfil, con datos. «Vanguardia y calidad» se define con umbrales medibles, no con adjetivos. Rediseño aprobado por el propietario el 2026-11-02 ([10](10-rediseno-propuesta.md), [ADR-0012](adr/0012-stage-chain-and-profiles.md)).

## 1. Problema

Los agentes de código ya generan cambios aceptables en una parte relevante de las tareas, pero nadie puede decir de forma barata y fiable *cuáles* son aceptables. En octubre de 2026 la generación es un commodity open source y el oráculo sigue sin resolver ([informe](research/software-factory-open-source.md), capa 3) [Cierto]. El cuello de botella de un equipo que adopta agentes es la verificación: la revisión humana de cada diff se come la ganancia, y quitarla sin un sustituto medido degrada el código (ver §5).

El problema no se limita al parche. Las definiciones de software factory de 2026 incluyen lo que va antes del código (intake, triage, spec y plan) y lo que va después (despliegue con puerta, monitorización e incidentes que generan trabajo nuevo) [Cierto: StrongDM, Osmani, Mastra, PostHog, LaunchDarkly y Factory; investigación del 2026-11-02 en doc-rag, `notas:conocimiento/llm-agentes/software-factory-alcance-etapas-y-productos-completos.md`]. Hoy el propietario hace esa cadena a mano con varios agentes sueltos y sin verificadores entre etapas.

## 2. Objetivo

1. **La cadena completa.** La factory cubre las ocho etapas de §3. Cada etapa entrega un artefacto que la siguiente puede comprobar; ninguna confía en la anterior sin oráculo o sin puerta humana.
2. **Cualquier tipo de software, por perfiles.** Un perfil define el entorno, el oráculo y el despliegue de un tipo de software (app web, API, CLI o librería, pipeline de datos, producto con IA…). Un perfil entra en autonomía solo cuando demuestra con datos que su oráculo detecta los defectos y las trampas ([06](06-harness-and-tasks.md) §7).
3. **Autonomía L4 por etapa, tipo de trabajo y perfil** (escala de [Shapiro](https://danshapiro.com/blog/2026/01/the-five-levels-from-spicy-autocomplete-to-the-software-factory/)). Una combinación pasa de decisión humana a automática solo cuando cumple el criterio del [ADR-0008](adr/0008-gates-and-auto-merge.md). Las demás siguen con su puerta humana.
4. **Agnóstica de agente y de modelo.** Hay un único contrato de ejecutor ([04](04-executor-contract.md)) y adaptadores finos. Cambiar Claude Code por Codex u OpenCode es un cambio de configuración.
5. **Auto-mejora bajo medición.** Todo cambio en prompts, modelos, pipeline, perfiles o verificación es un PR que pasa por el harness ([06](06-harness-and-tasks.md)) antes de entrar. La factory es su propio primer cliente: su CI es el harness.

## 3. La cadena de etapas

| Etapa | Qué entrega | Cómo se comprueba | Decisión humana por defecto |
|---|---|---|---|
| E1 · Entrada | Backlog priorizado a partir de ideas, issues, incidentes y feedback | No hay oráculo automático | Decide qué entra |
| E2 · Spec | Spec con criterios de aceptación y escenarios ejecutables. Un proceso aparte escribe escenarios **ocultos** | Los escenarios se ejecutan y fallan en el producto actual; la spec pasa una lista de completitud | Aprueba la spec |
| E3 · Plan | Tareas pequeñas con dependencias | Cada tarea tiene criterio verificable y tamaño acotado; entre todas cubren todos los escenarios | Aprueba el plan de épicas y productos |
| E4 · Implementar | Un diff por tarea, de un ejecutor en un sandbox | Lo comprueba E5 | Ninguna |
| E5 · Verificar | Veredicto | Tests y escenarios ocultos, antitrampas, SAST, mutación y reglas de arquitectura ([05](05-verification-design.md)) | Ninguna: los LLM no convierten un rojo en verde |
| E6 · Integrar | PR fusionado | Review con hallazgos verificados y CI | Merge, hasta que la combinación gane el auto-merge |
| E7 · Desplegar | Versión en staging y luego en producción, tras una feature flag | Smoke y escenarios E2E sobre lo desplegado | Paso a producción |
| E8 · Operar | Señales de producción convertidas en entradas de E1 | Métricas de producción antes y después del cambio | Prioriza en E1 |

## 4. Definición operativa de «vanguardia y calidad»

Cada umbral tiene fórmula, fuente y tamaño de muestra en [01-metrics](01-metrics.md). Aquí solo se nombran.

| Dimensión | Umbral de éxito (hipótesis) | Métrica |
|---|---|---|
| Calidad | La tasa de regresiones posteriores al merge de los cambios de la factory **no supera** la de los PRs humanos del mismo repo (cota superior del IC 95 %) | M4 |
| Integridad | La tasa de trampa en canarias imposibles tiene una cota superior al 95 % **≤ 2 %** por brazo habilitado (ejecutor × modelo × `config_sha`, [01](01-metrics.md) §1) | M5 |
| Eficiencia | **Coste por cambio aceptado** y porcentaje de PRs fusionados sin edición humana del código, por tipo de trabajo | M1, M3 |
| Mantenibilidad | La complejidad, la duplicación y el retrabajo del código tocado por la factory **no empeoran** frente al código humano comparable a 30 y 90 días | M7 |
| Vanguardia | Ningún cambio de prompt, modelo, pipeline o perfil entra sin una ejecución del harness que muestre que no empeora M1–M5 en el conjunto congelado | M8 |
| Producto | Fracción de escenarios ocultos que pasan sobre lo desplegado, y fracción de defectos sembrados que el oráculo del perfil detecta | M9, M10 ([01](01-metrics.md), pendientes de definir en la fase B) |

## 5. No-objetivos

- **Una factory sin ninguna puerta humana (nivel 5, dark factory).** Las personas deciden qué se construye, aprueban la spec y el paso a producción. La evidencia pública de factories sin revisión viene de equipos de 3 a 7 personas en greenfield o de los propios vendors ([informe](research/software-factory-open-source.md), resumen) [Cierto], y ningún caso grande publicado mide la mantenibilidad [Probable].
- **Un LLM supervisor del flujo.** El orquestador es una máquina de estados; los LLM ejecutan nodos y no deciden el siguiente paso.
- **Un equipo de roles por defecto** (Planner/Dev/Tester/Auditor). Los sistemas multiagente rinden sobre todo en tareas paralelizables ([MAST](https://arxiv.org/abs/2503.13657), [Kim et al.](https://arxiv.org/abs/2512.08296)) [Probable]. Un rol solo entra si el harness mide que mejora M1 o M3.
- **Una plataforma propia** de trazas, sandbox, gateway o serving. Se reutilizan ([03](03-reuse-inventory.md)).
- **Autonomía en clases de alto riesgo**: autenticación, facturación, infraestructura, migraciones de datos y contratos públicos pasan por la cadena, pero siempre con puerta humana (criterio de [Osmani](https://addyosmani.com/blog/software-factories/)).
- **Todos los perfiles a la vez.** No hay evidencia de una factory que funcione igual para cualquier tipo de software [Probable]; un perfil sin oráculo probado aceptaría software que no funciona.
- **Productividad del equipo** como promesa. La factory mide coste y calidad por cambio; no afirma ganancias de productividad sin un estudio que lo sostenga (§6).

**Lo que deja de ser no-objetivo (2026-11-02): los productos completos.** Pasan a ser un tipo de trabajo con su propio oráculo. El cambio lo motivan datos nuevos: hoy se puede medir la construcción de una app web desde cero contra recorridos ocultos ([Vibe Code Bench](https://arxiv.org/abs/2603.04601)) [Cierto].

## 6. Contraevidencia y respuesta del diseño

| Evidencia en contra | Qué dice | Respuesta del diseño |
|---|---|---|
| HumanLayer ([wsff.md](https://github.com/humanlayer/advanced-context-engineering-for-coding-agents/blob/main/wsff.md)) | Dejaron de leer el código en julio de 2025, tuvieron caídas y reescribieron. Tesis: «maintainability has no fast oracle» y el RL premia pasar tests, no mantener [Cierto] | La mantenibilidad es una métrica de primera clase (M7) y bloquea el auto-merge. En productos, la revisión humana de la arquitectura se mantiene. Las tareas autónomas son rodajas pequeñas ([06](06-harness-and-tasks.md) §4) |
| SpecBench ([arXiv 2605.21384](https://arxiv.org/abs/2605.21384)) | La diferencia entre tests visibles y ocultos crece 28 puntos por cada multiplicación por 10 del tamaño del código [Cierto] | Escenarios ocultos obligatorios en épicas y productos, escritos por un proceso que el constructor no ve |
| Vibe Code Bench ([arXiv 2603.04601](https://arxiv.org/abs/2603.04601)) | El mejor modelo pasa el 61,8 % de los recorridos ocultos de apps web hechas desde cero [Cierto] | Se espera que una parte relevante de los productos no pase: el oráculo de producto decide, y la puerta humana de entrega se mantiene |
| METR ([RCT](https://arxiv.org/abs/2507.09089)) | Desarrolladores expertos fueron ~19 % más lentos con IA [Probable] | Se mide el tiempo de extremo a extremo con la revisión humana incluida (M6), no el tiempo del agente. No se afirma productividad |
| Jain ([martinfowler.com](https://martinfowler.com/articles/are-harnesses-worth-the-cost.html)) | El harness no mejoró a un modelo frontier y multiplicó su coste; sí llevó a un modelo barato de 3/10 a 10/10 [Cierto, n=10] | La intensidad del harness (reintentos, best-of-n, revisor) se configura **por modelo** y se mide por coste por cambio aceptado |
| ImpossibleBench ([arXiv 2510.20270](https://arxiv.org/abs/2510.20270)) | Los modelos más capaces explotan más los tests [Probable] | Verificador aislado, tests de aceptación ocultos y salida explícita de «abortar por conflicto con el spec» ([05](05-verification-design.md)) |
| OpenAI deja SWE-bench Verified ([post](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/)) | El 59,4 % de los problemas auditados tenía defectos materiales [Cierto] | Las tareas se revalidan en nuestro entorno, con validación del gold y filtro de flaky ([06](06-harness-and-tasks.md)) |

## 7. Principios (de las tesis de diseño)

1. Construir lo que mide; reutilizar lo que ejecuta.
2. El verificador está aislado del generador por construcción: solo recibe los bytes del diff o del artefacto, y lo oculto nunca se monta en un sandbox. En F0 y la fase A el aislamiento es por proceso y montaje en la misma máquina ([ADR-0011](adr/0011-single-host-f0.md)); se revisa antes de meter código del cliente.
3. Pipeline determinista: una cadena de etapas con estados explícitos, no un agente que decide el flujo.
4. Cada etapa entrega un artefacto comprobable y tiene su puerta humana por defecto. Una puerta solo se quita con datos ([ADR-0008](adr/0008-gates-and-auto-merge.md)).
5. Lo que depende del tipo de software va en perfiles intercambiables; el resto de la cadena no sabe qué perfil corre.
6. Agnóstico de agente y de modelo; Claude Code es la baseline, con la versión fijada. Usa la suscripción del propietario a través del gateway ([04](04-executor-contract.md) §5.1; decisión del 2026-11-01).
7. La autonomía se gana por etapa, tipo de trabajo y perfil, con datos.
8. La factory es su propio primer cliente.
9. Minimalismo verificable: cada componente cita la métrica que mueve o la restricción que cumple ([02](02-architecture.md), tabla de justificación).
10. Formatos antes que plataformas: pipelines en YAML con JSON Schema, OpenSpec, JSONL crudo y OTel en ficheros versionados ([ADR-0002](adr/0002-orchestrator.md) §4).
11. **Separación de datos del piloto** ([ADR-0009](adr/0009-data-policy-per-repo.md)): nada del repo piloto entra en este repositorio. Las tareas, los escenarios ocultos y las trayectorias viven en un almacén privado aparte, y un hook de pre-commit lo comprueba.

## Decisiones abiertas

- El umbral de la canaria (≤ 2 %) y el de mantenibilidad son hipótesis. Se recalibran con los datos de las fases A y C ([09](09-open-questions.md)).
- Las métricas de producto (M9, M10) se definen en la fase B ([07](07-roadmap.md)).
- Qué perfil va después de app web ([10](10-rediseno-propuesta.md)).
- Qué app web interna concreta se usa en la fase B.
