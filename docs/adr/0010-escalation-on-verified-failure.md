# ADR-0010 · Escalado de modelo tras un fallo verificado (variante de F2)

- **Estado**: propuesta para F2 · **Fecha**: 2026-10-31
- **Origen**: activo de orca-role-hook (`bin/round.sh`, escalado por rol) que la arquitectura inicial no preveía. Se reimplementa a partir de la idea ([ADR-0007](0007-orca-role-hook.md)).

## Contexto

F2 compara intensidades de harness por modelo, porque el experimento de Jain mostró que el harness ayuda al modelo barato y encarece al frontier [Cierto, n=10]. El plan inicial solo tenía **best-of-n**, que multiplica el coste por n en cada tarea. orca-role-hook implementa otra estrategia: empezar con un modelo barato y **subir a uno más fuerte solo tras un fallo verificado**, volviendo al barato al aceptar. Su README afirma que predecir de antemano qué pasos son difíciles funcionó mal y que escalar tras un fallo verificado funcionó mejor [Probable: afirmación sin cita primaria en el README].

## Opciones

1. Solo best-of-n (el plan inicial): coste × n en cada tarea.
2. Cascada barato → fuerte tras un fallo verificado.
3. Reintento con el mismo modelo.
4. Predecir la dificultad de antemano y asignar modelo: el README de orca-role-hook dice que funcionó mal [Probable].

Se miden 1–3 y se descarta 4 sin medir.

## Decisión

F2 mide **tres variantes** contra el baseline de un solo intento, sobre ≥ 50 tareas:

1. Best-of-n con selección por tests y juez.
2. **Cascada**: el modelo barato intenta; si el verificador rechaza, reintenta el modelo fuerte con la **categoría** del rechazo como contexto.
3. Reintento con el mismo modelo y la categoría del rechazo.

Se elige la que minimiza `M1.total` con la regla única de coste de [01](../01-metrics.md) M1: `M1.total` ≤ 50 % del intento único y M2 no inferior con Δ = 10 puntos (≥ 50 tareas × k = 5 o ≥ 80 × 3).

## Consecuencias

- La cascada necesita que el contrato admita `attempt > 1` con contexto del veredicto. El esquema ya tiene `attempt`. **El contexto se limita a la lista blanca de [05](../05-verification-design.md) principio 7**: categoría, id de regla del diff-guard y salida de tests **visibles**. Nunca nombres, valores ni trazas de F2P, holdouts o mutantes, que serían un oráculo de los tests ocultos (T28).
- La fuga se mide: en los lotes de canarias se compara la tasa de trampa del intento 1 con la de los intentos 2+. Si sube con el número de intento, la lista blanca filtra demasiado.
- El coste de la cascada depende de la tasa de fallo del modelo barato: mide justo lo que dice Jain.

## Cómo revertir

Es una variante de configuración del brazo (`config_sha`). Si no gana, no se usa.
