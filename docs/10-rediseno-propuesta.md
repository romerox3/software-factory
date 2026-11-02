# 10 · Propuesta de rediseño: la factory completa

> **Estado**: **aprobada** por el propietario el 2026-11-02 ([ADR-0012](adr/0012-stage-chain-and-profiles.md)). Ya está aplicada en 00, 01, 02, 06 y 07. Lo que cambia y por qué está en [09](09-open-questions.md), «El diseño solo cubre un tramo de la factory».

## 1. Qué es la factory, en un párrafo

Un sistema que lleva el trabajo de software **desde la intención hasta el producto en producción y de vuelta**. Recibe ideas, issues e incidentes. Los convierte en una spec con criterios comprobables, la parte en tareas, las implementa con agentes, comprueba cada resultado con verificadores que el agente no controla, lo despliega y vigila qué pasa en producción para generar el trabajo siguiente. Cada etapa tiene **su forma de comprobar el resultado** y **su punto de decisión humana**. La autonomía se gana etapa a etapa y tipo de trabajo a tipo de trabajo, con datos.

Gran parte de esta cadena ya la hace hoy el propietario a mano con sus agentes del piloto: uno de PM decide qué toca, un orquestador convierte la tarea en spec y la reparte a peones, un revisor revisa los PRs y un analista mira producción y propone qué arreglar. La factory es **la versión formal y medida de ese flujo**, con verificadores entre etapas.

## 2. La cadena de etapas

| Etapa | Qué hace | Cómo se comprueba | Decisión humana | Qué existe ya |
|---|---|---|---|---|
| **E1 · Entrada** | Ideas, issues, incidentes y feedback → backlog priorizado | Sin oráculo automático: lo decide una persona | **Decide qué entra** | Agente de PM del piloto (a mano) |
| **E2 · Spec** | Intención → spec con criterios de aceptación y **escenarios** (recorridos de usuario) | Los escenarios se pueden ejecutar y fallan en el producto actual. Un proceso aparte, que el agente constructor no ve, escribe además escenarios ocultos | **Aprueba la spec** | Formato OpenSpec (ADR-0005) |
| **E3 · Plan** | Spec → tareas pequeñas con dependencias | Cada tarea tiene criterio verificable y tamaño acotado, y entre todas cubren todos los escenarios | Aprueba el plan en épicas y productos; automático en tareas sueltas | Orquestador de peones del piloto (a mano) |
| **E4 · Implementar** | Agentes en sandboxes resuelven cada tarea | — (lo comprueba E5) | Ninguna | **F0**: adaptadores, Harbor, gateway, prompts |
| **E5 · Verificar** | Tests ocultos, antitrampas, SAST, mutación y **reglas de arquitectura** | Es el oráculo | Ninguna (los LLM no convierten rojo en verde) | **F0**: verificador con 30 trampas fijadas |
| **E6 · Integrar** | Review agéntica + PR + merge | Review con hallazgos verificados; CI | **Merge** hasta que una clase gane el auto-merge (ADR-0008) | Revisor de PRs del piloto (a mano) |
| **E7 · Desplegar** | Feature flag, despliegue gradual | Smoke y escenarios E2E en staging | **Paso a producción** | — |
| **E8 · Operar y aprender** | Errores, latencias e incidentes → tareas nuevas en E1 | Métricas de producción antes y después | Prioriza en E1 | Analista de producción del piloto (a mano) |

## 3. Tipos de trabajo que recorren la cadena

Cada tipo usa las etapas que necesita y gana su autonomía por separado:

| Tipo | Ejemplo | Oráculo principal | Novedad |
|---|---|---|---|
| Bugfix, feature pequeña | Un issue | Tests ocultos del PR | Ya en F0 |
| Tests | Subir cobertura | Mutantes que genera el verificador | Ya prevista |
| Refactor, dependencias | Limpiar un módulo, subir versiones | Suite amplia, build | Ya prevista |
| **Migración** | Cambiar de librería en todo el repo | Suite + compilador + linters, por fichero | **Nueva**: es lo que tiene más evidencia industrial (Google: 74 % de 595 cambios generados; Airbnb: 97 % de ~3 500 ficheros en 4 días) [Cierto] |
| **Seguridad** | Arreglar una vulnerabilidad | Escáner, fuzzing y tests | **Nueva** (CodeMender, Copilot Autofix) [Cierto] |
| **Épica** | Feature grande en un producto existente | Escenarios ocultos de la épica | **Nueva**: recorre E2–E7 |
| **Producto nuevo** | **App web interna** (login, formularios, listados, flujos) | **Recorridos de usuario ocultos que ejecuta un agente de navegador sobre la app desplegada** | **Nueva** |

## 3 bis. Cualquier tipo de software: perfiles

La factory tiene que servir para construir **cualquier tipo de software** (requisito del propietario, 2026-11-02). La cadena de etapas es la misma para todos. Lo que cambia según el tipo se agrupa en un **perfil de software**, una pieza intercambiable igual que los ejecutores:

| Pieza del perfil | Qué define |
|---|---|
| Entorno | Cómo se construye y ejecuta: imagen, dependencias, servicios auxiliares |
| Oráculo | Cómo se comprueba que funciona: tests, escenarios, comparación con una referencia, evaluaciones |
| Despliegue | Dónde y cómo se publica, y cómo se vigila después |

| Perfil | Oráculo natural | Fuerza del oráculo |
|---|---|---|
| App web | Recorridos de usuario ocultos con agente de navegador | Fuerte para la funcionalidad, débil para el diseño visual y la UX |
| API o servicio | Tests de contrato y escenarios contra la API | Fuerte |
| CLI o librería | Suite de tests y comparación con una implementación de referencia | Fuerte |
| Pipeline de datos | Comparación de salidas con datos de referencia | Fuerte si hay datos de referencia |
| Producto con IA | Evaluaciones con conjuntos de prueba y jueces | Medio: no es determinista |
| Móvil o escritorio | Recorridos con emulador | Medio: entornos caros |
| Juegos, UX, contenido | Personas | Débil: la puerta humana pesa más |

Un perfil solo entra en autonomía cuando demuestra con datos que su oráculo detecta los fallos y las trampas (canarias, como en F0). Se empieza por **app web**, que tiene oráculo fuerte y benchmark público, y se añaden perfiles uno a uno. No hay evidencia de una factory que funcione para todo tipo de software a la vez [Probable], y un perfil sin oráculo probado acabaría aceptando software que no funciona.

## 4. Producto completo: cómo se haría y qué dice la evidencia

- **Flujo**: una persona aprueba la spec con sus escenarios (E2). Un proceso aparte escribe los escenarios ocultos. La factory planifica, construye y verifica tarea a tarea (E3–E5), despliega en staging, y un agente de navegador recorre los escenarios ocultos (E7). Una persona decide la entrega.
- **Se puede medir**: Vibe Code Bench hace exactamente esto. El mejor modelo pasa el 61,8 % de los recorridos ocultos de apps web hechas desde cero [Cierto, [arXiv 2603.04601](https://arxiv.org/abs/2603.04601)].
- **Los escenarios ocultos son obligatorios**: la diferencia entre tests visibles y ocultos (las «trampas») crece 28 puntos por cada multiplicación por 10 del tamaño del código [Cierto, [SpecBench](https://arxiv.org/abs/2605.21384)]. Cuanto más grande el producto, más engaña un test que el agente puede ver.
- **El riesgo que no se mide solo**: ningún caso grande publicado mide la mantenibilidad [Probable]. HumanLayer tuvo que reescribir tras dejar de leer el código [Cierto]. Por eso M7 sigue siendo puerta, y la revisión humana de arquitectura se mantiene en los productos.

## 5. No-objetivos revisados

- **Sale de los no-objetivos**: «productos completos». Pasa a ser un tipo de trabajo con su propio oráculo. El cambio lo motivan datos nuevos (Vibe Code Bench y SpecBench), no la presión.
- **Se mantiene**: nada de una factory sin ninguna puerta humana (L5). Las personas deciden qué se construye, aprueban la spec y el paso a producción.
- **Se mantiene**: auth, facturación, infraestructura y migraciones de datos quedan fuera de la autonomía.

## 6. Qué se conserva de lo hecho

Todo lo construido en F0 es el núcleo de E4 y E5: el contrato de ejecutor, los adaptadores, el gateway con fusible de gasto, el verificador antitrampas, el normalizador, las métricas y las 26 tareas Python ya validadas. Nada se tira.

## 7. Orden propuesto

1. **Fase A · Núcleo (E4–E5)**: cerrar la medición de implementar y verificar con las 26 tareas Python y las TS que salgan. Es lo de F0, recortado. Sale cuando hay datos de coste y de trampas por brazo.
2. **Fase B · De la spec al producto, primer perfil (E2–E5 + E7 en staging)**: construir una **app web interna desde cero** a partir de una spec aprobada, con escenarios ocultos y agente de navegador. No usa código del cliente, así que puede empezar sin tocar el piloto. El perfil se diseña como pieza intercambiable desde el primer día.
3. **Fase C · Cadena completa en el piloto (E1–E8)**: épicas y migraciones en los repos reales, despliegue con flags y la vuelta desde producción.
4. **Fase D · Más perfiles**: API o servicio, CLI o librería, pipeline de datos y producto con IA, uno a uno, cada uno con su oráculo probado.

Cada fase tendrá criterio de salida y de abandono medibles, como ahora.

## Decisiones abiertas

- ¿Este es el alcance correcto de la factory (cualquier software, por perfiles)?
- ¿Qué perfil va después de app web?
- ¿El orden A → B → C?
- ¿Qué app web interna concreta se usa en la fase B?
