# 08 · Riesgos

> **Resumen.** Hay 17 riesgos, cada uno con probabilidad, impacto, señal temprana y mitigación. Los tres más serios:
> 1. Que el verificador no detecte una trampa nueva y M5 dé una falsa sensación de seguridad.
> 2. Que el piloto no rinda 30 tareas válidas, o que no tenga volumen suficiente para F3.
> 3. Que se filtre código del cliente, ya sea al repo público o a un proveedor no autorizado.
>
> Probabilidad e impacto se califican A/M/B (alto, medio, bajo) por juicio propio [Suposición] salvo donde se cita un dato.

| # | Riesgo | Prob. | Impacto | Señal temprana | Mitigación |
|---|---|---|---|---|---|
| R1 | **Trampa no modelada**: un agente encuentra una ruta que ninguna capa dura cubre, y M5 y M2 quedan inflados | M | A | Una auditoría humana encuentra un `accept` incorrecto. Clusters raros en las trayectorias. Un salto de pass@1 al subir de versión de modelo | Auditoría trimestral de veredictos. Canarias que rotan. Revisión de trayectorias de canarias (Docent como piloto en F1). Toda trampa nueva se añade a la tabla de [05](05-verification-design.md) con su fixture |
| R2 | **El piloto rinde menos de 30 tareas válidas** | M | A | F0-05 da < 150 PRs candidatos con tests | Criterio de abandono de F0 (cambiar de fuente). Completar con SWE-smith marcado `synthetic` (no cuenta para salir) |
| R3 | **Volumen insuficiente para F3**: < 150 cambios de una clase en 6 meses | A | M | Ritmo de issues `factory:C1` en F1 | Criterio de abandono de F3. Asumirlo: la factory vale como generadora de borradores aunque no llegue a L4 |
| R4 | **Código del cliente en el repo público** | M | A | El hook de pre-commit bloquea algo. Aparece un nombre del cliente en una revisión | Separación física ([ADR-0009](adr/0009-data-policy-per-repo.md)) + hook que falla de forma cerrada + escaneo de todo el historial antes de publicar. El hook bloqueó una mención el 2026-10-31 [Cierto] |
| R5 | **Código del cliente a un proveedor no autorizado** | B | A | Un alias nuevo en el gateway sin clasificar | La lista de modelos permitidos por equipo se aplica en el gateway. Las keys son efímeras. La configuración del gateway se revisa en cada cambio |
| R6 | **Cambio de formato de eventos de un CLI** (nadie garantiza semver [Probable]) | A | M | Sube el contador de «eventos no mapeados» del normalizador | Se archiva el crudo. Versiones fijadas. Actualizar una versión es un brazo nuevo con M8 |
| R7 | **Cambio de política o de precio de un proveedor** (precedente: el cambio de OAuth de Anthropic de abril de 2026 que rompió una integración del propietario) | M | M | Avisos del proveedor. Errores 401 o 403 | Ningún componente depende de un único proveedor (tesis 4). El baseline va por API key, nunca por suscripción |
| R8 | **Supply chain del gateway**: LiteLLM tuvo paquetes PyPI comprometidos (1.82.7 y 1.82.8) y advisories críticos en 2026 [Cierto] | M | A | Advisories nuevos en el repo de LiteLLM | Imagen fijada por digest, actualizaciones revisadas, sin `pip install` sin hash. Bifrost como plan B ([ADR-0004](adr/0004-gateway.md)) |
| R9 | **Bus factor de dependencias pequeñas**: Harbor (activo, pero joven), Tracker (2 personas, DOT deprecado) | M | M | Sin releases en 3 meses | Formatos propios (OpenSpec, DOT, JSONL). Inspect como plan B de Harbor. El runner DOT es propio |
| R10 | **Las tool calls de Codex no sobreviven al puente Responses→chat con GLM** | M | B | Falla B3 del spike 1 | Brazo A2 → Codex × OpenAI (si se autoriza) u OpenHands SDK × GLM |
| R11 | **El aislamiento de red no se aplica en la torre** (Harbor necesita nftables `fib inet` en el kernel; en macOS falla) [Cierto, spike 1] | B | A | `network-probe` falla en la torre | Regla de host en `DOCKER-USER` como defensa en profundidad. Harbor falla de forma cerrada si no puede aplicar la política |
| R12 | **Degradación de la mantenibilidad del código** (tesis de HumanLayer) | M | A | M7d y M7e empeoran frente a los humanos. Revisores que se quejan de la legibilidad | M7 bloquea F3. Merge humano por defecto. Tamaño máximo de parche por clase |
| R13 | **Goodhart sobre el conjunto congelado o las canarias**: los prompts se ajustan a las tareas conocidas | M | M | M8 mejora en el congelado pero no en el rotativo | M8 evalúa también el conjunto rotativo. Rotación mensual de canarias |
| R14 | **Varianza que oculta las diferencias reales** con 30 tareas (solo se detectan ~17 puntos [Probable, simulación]) | A | M | IC solapados entre brazos | k = 3 o 5. Pruebas pareadas. No afirmar diferencias no detectables. F2 con ≥ 50 tareas |
| R15 | **Cuotas y concurrencia** (z.ai devuelve 429 con más de ~6 concurrentes [Cierto, medición del propietario]; una sola GPU para los brazos locales) | A | B | La tasa de `error` por 429 sube | Concurrencia limitada por proveedor. Un `error` de infraestructura no cuenta como fallo del brazo |
| R16 | **Licencia de orca-role-hook sin resolver** | A | B | — | No se copia nada ([ADR-0007](adr/0007-orca-role-hook.md)). El diseño no depende de portar |
| R17 | **La revisión humana no da abasto en F1** (saturación de PRs, una lección que repiten varios equipos que montaron factories [Suposición, fuentes secundarias]) | M | M | PRs en borrador sin revisar más de 3 días | Limitar los PRs abiertos de la factory (por ejemplo, ≤ 5). M6 incluye la cola humana |

## Decisiones abiertas

- Si R3 (volumen) hace que F3 sea irrelevante en el horizonte de un año: en ese caso, el valor de la factory se mide hasta F2.
