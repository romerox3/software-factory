# Informe de la fase A · Núcleo: implementar y verificar

> **Resumen.** Sobre 33 tareas públicas de SWE-rebench (`tasks/public-v2.manifest.json`) y 594 ejecuciones, los cuatro brazos medidos producen salidas de contrato válidas en el 100 % de los casos, y el verificador pasa la auditoría: 1 falso `accept` de 30 y 10 de 10 rechazos concordantes. pass@1: Claude Code × Sonnet 87,9 %, Claude Code × GLM 83,8 %, Codex × GLM 78,8 % y OpenCode × GLM 65,7 %. Solo OpenCode queda claramente por debajo de la referencia. Se cumplen todos los criterios de salida de la fase A y no salta ningún criterio de abandono. La recomendación es pasar a la fase B, con tres condiciones que se explican en §6.

Fecha: 2026-11-06. Fuente de las cifras: `factory.metrics.report` sobre el conjunto `public-v2`. De los 594 veredictos, 576 son del verificador 0.1.0 y 18 (toqito-1484) del 0.2.0. La M8 mostró que los dos dan el mismo veredicto fuera de esa tarea (58 de 58 en la muestra de control). Las trayectorias y los veredictos están en el almacén privado, no en este repo.

## 1. Criterios de salida y de abandono

Cada línea lleva la clave que comprueba `python -m factory.metrics.report --check reports/a-baseline.md --phase A`.

| Clave | Valor | Criterio ([07](../docs/07-roadmap.md) §1 A) | Resultado |
|---|---|---|---|
| `valid_tasks` | 33 | ≥ 15 tareas válidas | Cumple [Cierto] |
| `contract_valid_rate` | 100 % (594 de 594 en el conjunto; 735 de 735 de todas las ejecuciones lanzadas) | ≥ 95 % de salidas de contrato válidas | Cumple [Cierto] |
| `error_infra_rate` | 0 % en el conjunto (0 de 594). De las 735 lanzadas, 12 (1,6 %) acabaron en error del arnés, todas de pydap-624 por el defecto H1, y se repitieron | ≤ 5 % | Cumple [Cierto] |
| `verifier_reproducibility` | 100 % (100 de 100 con el mismo diff, veredicto y motivo) | ≥ 99 % | Cumple [Cierto] |
| `false_accepts` | 1 de 30 `accept` auditados a ciegas | ≤ 1 de 30 (abandono si ≥ 4) | Cumple [Cierto] |
| `reject_concordance` | 10 de 10 | ≥ 9 de 10 | Cumple [Cierto] |
| `best_arm_pass_at_1` | 87,9 % (A1) | Abandono si < 15 % | No salta [Cierto] |

Las TS no entran: tras el tope de un día ninguna funcionó en el sandbox del verificador, así que **la etapa solo está medida en Python** ([07](../docs/07-roadmap.md) §1 A).

## 2. Resultados por brazo

Primeras 3 repeticiones de cada tarea (A1 tiene 3 por la cuota de la suscripción; A2, A3 y A6, 5). Coste en USD por cambio aceptado, con el precio sombra de lista para los planes de suscripción. El verificador corre en local y su coste es 0, así que M1.total = M1.gen.

| Brazo | Ejecutor × modelo | pass@1 | pass^3 | M1 (USD) | M7a | M7b | M7c |
|---|---|---|---|---|---|---|---|
| A1 | Claude Code 2.1.316 × Sonnet 5.5 | 87,9 % | 81,8 % | 0,150 | 0 | 0 | 0,75 |
| A6 | Claude Code 2.1.316 × GLM-5.3 Flash | 83,8 % | 72,7 % | 0,025 | 0 | 0 | 1,89 |
| A2 | Codex CLI 0.166.0 × GLM-5.3 Flash | 78,8 % | 60,6 % | 0,044 | 0 | 0 | 1,00 |
| A3 | OpenCode 1.19.5 × GLM-5.3 Flash | 65,7 % | 45,5 % | 0,050 | 0 | 0 | 1,00 |

[Cierto, `factory.metrics.report`]. M7a es la Δ de CCN máxima de las funciones tocadas, menos la del gold. M7b son los bloques duplicados nuevos menos los del gold, con lizard y su umbral de 70 tokens. M7c es el tamaño del diff frente al gold. Las tres son medianas por tarea ([01](../docs/01-metrics.md) M7).

**Comparación pareada con A1** (bootstrap pareado por tarea, 10 000 remuestreos, IC al 95 %) [Cierto]:

| Brazo | Diferencia de pass@1 | IC 95 % |
|---|---|---|
| A6 | −4,0 puntos | [−17,2; +9,1] |
| A2 | −9,1 puntos | [−24,2; +5,1] |
| A3 | −22,2 puntos | [−35,4; −9,1] |

Entre los brazos de GLM, A3 queda por debajo de A6, −18,2 [−30,3; −5,1], y de A2, −13,1 [−26,3; 0,0], este último en el límite. A2 frente a A6 es −5,1 [−16,2; +5,1] [Cierto].

## 3. Lectura

- **El ejecutor pesa más que el modelo en estas tareas.** Con Claude Code fijo, cambiar Sonnet por GLM cuesta −4 puntos y no es significativo. Con GLM fijo, OpenCode pierde 18 puntos frente a Claude Code [Cierto]. Con n = 33, el diseño solo detecta diferencias de unos 15 puntos o más ([01](../docs/01-metrics.md) §3), así que «no significativo» no quiere decir «igual» [Cierto].
- **Por qué pierde OpenCode.** De sus 60 rechazos en las 5 repeticiones, 45 son diffs vacíos, y 25 ejecuciones agotan el tope de 30 minutos [Cierto]. El problema es no llegar a producir un cambio, no que el código que produce sea malo: cuando deja diff, los tests ocultos lo rechazan en 8 casos de 165.
- **Coste.** A6 es el brazo más barato por cambio aceptado: 0,025 USD de precio sombra, 6 veces menos que A1 [Cierto]. Con la suscripción y el coding plan el gasto real es 0, pero el precio sombra es lo que permite comparar brazos.
- **Tamaño de los cambios.** A6 escribe diffs casi el doble de grandes que el gold (M7c = 1,89), por encima del objetivo de 1,5 [Cierto]. A1 hace cambios más pequeños que el gold (0,75). M7a y M7b dan una mediana de 0 en todos los brazos. En M7a, la diferencia con el gold es distinta de 0 en dos tercios de las ejecuciones aceptadas y va de −7 a +12, pero se reparte a los dos lados. En M7b solo se mueve en 2–5 ejecuciones por brazo [Cierto]. Ningún brazo empeora la mantenibilidad de forma sistemática en estas tareas, que son cambios pequeños.
- **Posible contaminación.** Las tareas son de enero a marzo de 2026, y los modelos pueden haberlas visto ([06](../docs/06-harness-and-tasks.md) §3). Las comparaciones entre modelos distintos (A1 frente a A6) llevan esa etiqueta. La comparación entre ejecutores con el mismo modelo no se ve afectada [Probable].

## 4. Sensibilidad

| Conjunto | Tareas | A1 | A6 | A2 | A3 | A3 frente a A1 |
|---|---|---|---|---|---|---|
| `public-v2` (principal) | 33 | 87,9 % | 83,8 % | 78,8 % | 65,7 % | −22,2 [−35,4; −9,1] |
| Las 26 de v1 que se quedan | 26 | 85,9 % | 83,3 % | 80,8 % | 60,3 % | −25,6 [−42,3; −10,3] |
| Las 32 de v1, con el arnés corregido | 32 | 75,0 % | 75,0 % | 69,8 % | 54,2 % | −20,8 [−35,4; −7,3] |

[Cierto]. La conclusión no cambia con el conjunto. La decisión de reponer tareas se tomó después de ver los resultados de la matriz y por eso se declara ([07](../docs/07-roadmap.md), F0-19).

## 5. Lo que salió al medir

La auditoría F0-19 y la matriz de reposición destaparon cinco fallos del sistema de medida, ya corregidos. Sin corregirlos, las cifras de arriba estarían sesgadas [Cierto]:

1. **El diff se perdía si los tests visibles tardaban más de 120 s**: Harbor cortaba la ejecución. El `test.sh` de Harbor ya solo exporta el diff, y su recompensa es una constante 0. La comprobación de la recompensa de F0-04 queda como dato histórico.
2. **La matriz no leía el canal de aborto.** 16 abortos contaban como rechazos del diff-guard. Esto también inflaba la tasa de trampas cazadas por el juez LLM del [spike 03](../spikes/03-llm-judge/README.md), que se ha recalculado.
3. **La caché de tareas de Harbor no se invalidaba** cuando cambiaba el conversor. Ahora se reconvierte y se compara por digest.
4. **Falso rechazo por construcción en el verificador** (toqito-1484, 0 de 18). Si el enunciado pide añadir tests, el agente crea el mismo fichero que trae el test oculto. Con el verificador 0.2.0, el oculto sustituye al del agente. La M8 dio 18 cambios a `accept` y ninguno en la muestra de control de 58.
5. **Las métricas perdían los CRLF de los diffs** al leerlos, y los cambios sobre ficheros CRLF no se podían volver a aplicar para M7. Ahora se leen byte a byte.

Además, la auditoría descartó seis tareas mal construidas, en las que el enunciado y los tests ocultos no cuadran, y se repusieron siete auditadas antes de importar. La lección para el importador está en [07](../docs/07-roadmap.md).

**Hallazgos de comportamiento de los agentes**, que no son fallos del arnés:
- En pydap-624, Claude Code reescribe un fichero CRLF entero con LF: unas 2 140 líneas, que superan el tope de líneas del verificador. A1 sale 0 de 3 en esa tarea. La regla del tope se mantiene [Cierto].
- En briefcase-2651, el enunciado pide editar un test que ya existe, y las reglas lo prohíben. Sonnet respeta las reglas en 3 de 3. Los brazos de GLM editan el test en 11 de 15 ejecuciones y el diff-guard los rechaza [Cierto].

## 6. Decisión sobre la fase B

**Recomendación: pasar a la fase B.** El núcleo mide de forma reproducible y el verificador tiene la tasa de falsos `accept` dentro del criterio. Condiciones:

1. **Ejecutor por defecto: Claude Code**, con GLM para el volumen y Sonnet como referencia. OpenCode no, mientras no se entienda por qué deja diffs vacíos. Es coherente con [ADR-0013](../docs/adr/0013-verification-layer-over-agent-swarm.md), donde el worker de Agent Swarm ya es Claude Code × GLM. El precio: A6 es el único brazo por encima del objetivo de tamaño (M7c = 1,89 frente a ≤ 1,5). Lo acepto en la fase B porque M7a y M7b no empeoran, pero M7c de A6 se vigila. Si en las apps de la fase B sigue por encima de 1,5, se prueba Sonnet o un prompt que pida cambios mínimos.
2. **La puerta sigue siendo el verificador con tests ocultos.** Un juez LLM solo sirve como filtro previo ([spike 03](../spikes/03-llm-judge/README.md)).
3. **La baseline de M4 se calibra en el repo del piloto al empezar la fase C** ([01](../docs/01-metrics.md) M4), porque la precisión del SZZ básico cambia mucho de un repo a otro.

**Lo que queda abierto de la fase A:**
- A4 y A5, con el modelo local, sin medir. El propietario los descartó el 2026-11-06: el modelo para datos del cliente vendrá del gateway del CPD en la fase C ([07](../docs/07-roadmap.md)).
- M5 (canarias): no se ha medido en esta matriz. Pasa a ser la primera tarea de la fase B.
- El residual T29 del verificador, aceptado en F0 ([08](../docs/08-risks.md)).
