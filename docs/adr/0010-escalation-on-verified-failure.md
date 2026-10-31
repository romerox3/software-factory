# ADR-0010 · Escalado de modelo tras un fallo verificado (variante de F2)

- **Estado**: propuesta para F2 · **Fecha**: 2026-10-31
- **Origen**: activo de orca-role-hook (`bin/round.sh`, escalado por rol) que la arquitectura inicial no preveía. Se reimplementa a partir de la idea ([ADR-0007](0007-orca-role-hook.md)).

## Contexto

F2 compara intensidades de harness por modelo, porque el experimento de Jain mostró que el harness ayuda al modelo barato y encarece al frontier [Cierto, n=10]. El plan inicial solo tenía **best-of-n**, que multiplica el coste por n en cada tarea. orca-role-hook implementa otra estrategia: empezar con un modelo barato y **subir a uno más fuerte solo tras un fallo verificado**, volviendo al barato al aceptar. Su README afirma que predecir de antemano qué pasos son difíciles funcionó mal y que escalar tras un fallo verificado funcionó mejor [Probable: afirmación sin cita primaria en el README].

## Decisión

F2 mide **tres variantes** contra el baseline de un solo intento, sobre ≥ 50 tareas:

1. Best-of-n con selección por tests y juez.
2. **Cascada**: el modelo barato intenta; si el verificador rechaza, reintenta el modelo fuerte con el motivo del rechazo como contexto.
3. Reintento con el mismo modelo y el motivo del rechazo.

Se elige la que minimiza `M1.total` con M2 no inferior en más de 5 puntos frente a la mejor.

## Consecuencias

- La cascada necesita que el contrato admita `attempt > 1` con el contexto del veredicto (sin holdouts). El esquema ya tiene `attempt`; el texto del motivo se pasa en el prompt.
- El coste de la cascada depende de la tasa de fallo del modelo barato: mide justo lo que dice Jain.

## Cómo revertir

Es una variante de configuración del brazo (`config_sha`). Si no gana, no se usa.
