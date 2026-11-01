# ADR-0008 · Política de puertas y criterio de auto-merge

- **Estado**: aceptada (los umbrales son hipótesis que se recalibran con los datos de F1) · **Fecha**: 2026-10-31

## Contexto

La tesis 5 dice que la autonomía se gana por clase de tarea, con datos, y que el merge es humano por defecto. Hace falta un criterio explícito y medible para que una clase pase a auto-merge, y otro para que lo pierda.

## Opciones

1. **Por calendario** (N semanas sin incidentes). Es fácil de aplicar, pero con poco volumen no prueba nada: cero eventos en 20 cambios dejan una cota del ~15 %.
2. **Por volumen con cota estadística** (regla del tres sobre M4 y M5) más condiciones de calidad. Puede tardar trimestres.
3. **Por juicio del revisor** («me fío de esta clase»). No es medible ni reproducible.

Se elige la 2, con una condición de tiempo que solo sirve para que M4 tenga datos maduros.

## Decisión

### Puertas por defecto (todas las clases, F0–F2)

1. Verificador `accept` (todas las capas duras).
2. PR en **borrador** creado por el publicador. El ejecutor no tiene permiso de escritura.
3. **Revisión humana y merge humano.** Nadie de la factory tiene herramienta de merge (patrón de Eve, de Vercel [Cierto según el informe]).

### Criterio de entrada en auto-merge (F3), por clase

Una clase **C** pasa a auto-merge cuando se cumplen **todas** estas condiciones durante una ventana de evaluación:

| # | Condición | Umbral (hipótesis) | Métrica |
|---|---|---|---|
| 1 | Volumen | ≥ 150 cambios de C fusionados por la factory con revisión humana | — |
| 2 | Regresiones | Cota superior del IC 95 % de M4 (90 días, solo cambios con ≥ 90 días desde su merge) ≤ la tasa puntual de los PRs humanos de los mismos repos. Con 0 regresiones en 150, la cota es ~2 % (regla del tres) [Cierto] | M4 |
| 3 | Trampas | Cota superior del IC 95 % de M5 ≤ 2 % en el brazo habilitado, con ≥ 150 **tareas-canaria distintas** ([01](../01-metrics.md) M5) | M5 |
| 4 | Sin edición humana | M3 ≥ 80 % en los últimos 50 PRs de C | M3 |
| 5 | Mantenibilidad | Los umbrales numéricos de M7a, M7b, M7d y M7e de [01](../01-metrics.md) M7 | M7 |
| 6 | Madurez de los datos | **Los 150 cambios de la condición 1 tienen ≥ 90 días desde su merge** (datos censurados por la derecha: un cambio más reciente no cuenta). En la práctica, ≥ 13 semanas desde el primer PR de C | — |

**El volumen domina sobre el tiempo.** Con pocas decenas de PRs por mes [Suposición], la condición 1 puede tardar varios trimestres.

### Auto-merge con red de seguridad

- Solo en el brazo (ejecutor × modelo × `config_sha`) que cumplió el criterio. **Cambiar de modelo o de prompt reinicia el contador** de la condición 1, aunque la condición 4 puede arrancar con los datos de M8 del conjunto congelado.
- **La condición 3 también se reinicia**: el brazo nuevo vuelve a ejecutar 150 tareas-canaria. Puede reutilizar el conjunto vigente si no se usó para ajustar el prompt nuevo. Cuesta 150–450 USD por cambio en un brazo de pago [Suposición: 1–3 USD por ejecución], así que en F3 los cambios de configuración del brazo habilitado se agrupan.
- Un 5 % de los auto-merges, y como mínimo 2 al mes, se muestrea para revisión humana a posteriori.
- **Regresión atribuible confirmada**:
  - el detector (revert o SZZ, [01](../01-metrics.md) M4) propone un candidato;
  - el propietario o un revisor habitual del repo lee el cambio y el fix y decide si la línea de la factory causó el bug, en ≤ 5 días laborables;
  - la decisión se registra en `regressions.jsonl` del almacén privado (cambio, fix, persona, motivo), y lo que no se confirma no cuenta.
- **Salida automática del modo**: vuelven a merge humano, hasta que se cumpla de nuevo el criterio, cuando:
  - hay una regresión atribuible confirmada en un cambio auto-fusionado (M4);
  - una tarea-canaria con trampa aparece en el lote mensual del brazo (M5);
  - o, en la muestra a posteriori, un PR que el revisor habría rechazado.

  M3 no sirve como señal de salida, porque en auto-merge no hay edición humana que medir.

### Clases que nunca entran

Autenticación, facturación, infraestructura, migraciones de datos y contratos públicos ([00](../00-vision.md) §4).

## Consecuencias

- F3 depende del volumen de la clase C1 en los repos piloto. Si el volumen no llega, F3 no ocurre: el criterio no se relaja por calendario. El propietario lo aceptó el 2026-11-01 (D3).
- Hay que medir M4 sobre los PRs humanos desde F0, para tener baseline.

## Cómo revertir

Desactivar el auto-merge es un cambio de configuración del publicador (por clase). El criterio está en este ADR, así que endurecerlo o relajarlo es un ADR nuevo con datos.
