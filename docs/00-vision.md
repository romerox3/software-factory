# 00 · Visión

> **Resumen.** La factory es un sistema que convierte tareas especificadas en cambios de código verificados, con un pipeline determinista y ejecutores intercambiables. Su objetivo es el nivel 4 de autonomía *por clase de tarea*: los humanos revisan resultados, no código, y solo en las clases donde los datos lo justifiquen. «Vanguardia y calidad» se define con cuatro umbrales medibles (regresiones, trampas, coste y mantenibilidad), no con adjetivos. El primer producto no es la factory, sino el instrumento que la mide: harness, verificador aislado y tareas minadas del historial real. Lo que no se mide no se construye.

## 1. Problema

Los agentes de código ya generan cambios aceptables en una parte relevante de las tareas, pero nadie puede decir de forma barata y fiable *cuáles* son aceptables. En octubre de 2026 la generación es un commodity open source y el oráculo sigue sin resolver ([informe](research/software-factory-open-source.md), capa 3) [Cierto]. El cuello de botella de un equipo que adopta agentes es la verificación: la revisión humana de cada diff se come la ganancia, y quitarla sin un sustituto medido degrada el código (ver §5).

## 2. Objetivo

1. **Autonomía L4 por clase de tarea** (escala de [Shapiro](https://danshapiro.com/blog/2026/01/the-five-levels-from-spicy-autocomplete-to-the-software-factory/)). Una clase de tarea (por ejemplo, «bugfix localizado con test de reproducción») pasa de *merge humano* a *auto-merge* solo cuando cumple el criterio del [ADR-0008](adr/0008-gates-and-auto-merge.md). Las demás clases siguen con revisión humana.
2. **Agnóstica de agente y de modelo.** Hay un único contrato de ejecutor ([04](04-executor-contract.md)) y adaptadores finos. Cambiar Claude Code por Codex u OpenCode es un cambio de configuración.
3. **Auto-mejora bajo medición.** Todo cambio en prompts, modelos, pipeline o verificación es un PR que pasa por el harness ([06](06-harness-and-tasks.md)) antes de entrar. La factory es su propio primer cliente: su CI es el harness.

## 3. Definición operativa de «vanguardia y calidad»

Cada umbral tiene fórmula, fuente y tamaño de muestra en [01-metrics](01-metrics.md). Aquí solo se nombran.

| Dimensión | Umbral de éxito (hipótesis) | Métrica |
|---|---|---|
| Calidad | La tasa de regresiones posteriores al merge de los cambios de la factory **no supera** la de los PRs humanos del mismo repo (cota superior del IC 95 %) | M4 |
| Integridad | La tasa de trampa en canarias imposibles tiene una cota superior al 95 % **≤ 2 %** por combinación ejecutor×modelo habilitada | M5 |
| Eficiencia | **Coste por cambio aceptado** y porcentaje de PRs mergeados sin edición humana del código, por clase de tarea | M1, M3 |
| Mantenibilidad | La complejidad, la duplicación y el retrabajo del código tocado por la factory **no empeoran** frente al código humano comparable a 30 y 90 días | M7 |
| Vanguardia | Ningún cambio de prompt, modelo o pipeline entra sin una ejecución del harness que muestre que no empeora M1–M5 en el conjunto congelado | M8 |

## 4. No-objetivos

- **Nivel 5 (dark factory).** La evidencia pública viene de equipos de 3 a 7 personas en greenfield o de los propios vendors ([informe](research/software-factory-open-source.md), resumen) [Cierto]. No hay estudios controlados de una factory L4/L5 [Probable].
- **Un LLM supervisor del flujo.** El orquestador es una máquina de estados; los LLM ejecutan nodos y no deciden el siguiente paso.
- **Un equipo de roles por defecto** (Planner/Dev/Tester/Auditor). Los sistemas multiagente rinden sobre todo en tareas paralelizables ([MAST](https://arxiv.org/abs/2503.13657), [Kim et al.](https://arxiv.org/abs/2512.08296)) [Probable]. Un rol solo entra si el harness mide que mejora M1 o M3.
- **Una plataforma propia** de trazas, sandbox, gateway o serving. Se reutilizan ([03](03-reuse-inventory.md)).
- **Clases de alto riesgo**: autenticación, facturación, infraestructura, migraciones de datos y contratos públicos quedan fuera de la autonomía en todas las fases (criterio de [Osmani](https://addyosmani.com/blog/software-factories/)).
- **Productividad del equipo** como promesa. La factory mide coste y calidad por cambio; no afirma ganancias de productividad sin un estudio que lo sostenga (§5).

## 5. Contraevidencia y respuesta del diseño

| Evidencia en contra | Qué dice | Respuesta del diseño |
|---|---|---|
| HumanLayer ([wsff.md](https://github.com/humanlayer/advanced-context-engineering-for-coding-agents/blob/main/wsff.md)) | Dejaron de leer el código en julio de 2025, tuvieron caídas y reescribieron. Tesis: «maintainability has no fast oracle» y el RL premia pasar tests, no mantener [Cierto] | La mantenibilidad es una métrica de primera clase (M7) y bloquea el paso a F3. El merge humano es el valor por defecto. Las tareas autónomas son rodajas pequeñas (≤ 200 líneas cambiadas en C1/C2, [06](06-harness-and-tasks.md)) |
| METR ([RCT](https://arxiv.org/abs/2507.09089)) | Desarrolladores expertos fueron ~19 % más lentos con IA [Probable] | Se mide el tiempo de extremo a extremo con la revisión humana incluida (M6), no el tiempo del agente. No se afirma productividad |
| Jain ([martinfowler.com](https://martinfowler.com/articles/are-harnesses-worth-the-cost.html)) | El harness no mejoró a un modelo frontier y multiplicó su coste; sí llevó a un modelo barato de 3/10 a 10/10 [Cierto, n=10] | La intensidad del harness (reintentos, best-of-n, revisor) se configura **por modelo** y se mide por coste por cambio aceptado, no por coste por token (F2) |
| ImpossibleBench ([arXiv 2510.20270](https://arxiv.org/abs/2510.20270)) | Los modelos más capaces explotan más los tests [Probable] | El verificador está aislado por construcción, los tests de aceptación están ocultos y hay una salida explícita de «abortar por conflicto con el spec» ([05](05-verification-design.md)) |
| OpenAI deja SWE-bench Verified ([post](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/)) | El 59,4 % de los problemas auditados tenía defectos materiales [Cierto] | Las tareas se minan del historial propio, con validación del gold y filtro de flaky ([06](06-harness-and-tasks.md)) |

## 6. Principios (de las tesis de diseño)

1. Construir lo que mide; reutilizar lo que ejecuta.
2. El evaluador está aislado del generador por construcción: otras credenciales, otra máquina, holdouts ilegibles y checkout limpio que solo recibe el diff.
3. Pipeline determinista.
4. Agnóstico de agente y de modelo; Claude Code es la baseline con API key a través del gateway y la versión fijada. Nunca con suscripción en ejecuciones automáticas.
5. La autonomía se gana por clase de tarea, con datos.
6. La factory es su propio primer cliente.
7. Minimalismo verificable: cada componente cita la métrica que mueve o la restricción que cumple ([02](02-architecture.md), tabla de justificación).
8. Formatos antes que plataformas: DOT, OpenSpec, JSONL crudo y OTel en ficheros versionados.
9. **Separación de datos del piloto** (añadido, [ADR-0009](adr/0009-data-policy-per-repo.md)): nada del repo piloto entra en este repositorio. Las tareas, los holdouts y las trayectorias viven en un almacén privado aparte, y un hook de pre-commit lo comprueba.

## Decisiones abiertas

- El umbral de la canaria (≤ 2 %) y el de mantenibilidad son hipótesis. Se recalibran con los datos de F0 y F1 ([09](09-open-questions.md)).
- Qué clase de tarea es la primera candidata a L4 se decide con los resultados de F0 ([07](07-roadmap.md)).
