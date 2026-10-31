# ADR-0008 · Política de puertas y criterio de auto-merge

- **Estado**: aceptada (los umbrales son hipótesis que se recalibran con los datos de F1) · **Fecha**: 2026-10-31

## Contexto

La tesis 5 dice que la autonomía se gana por clase de tarea, con datos, y que el merge es humano por defecto. Hace falta un criterio explícito y medible para que una clase pase a auto-merge, y otro para que lo pierda.

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
| 2 | Regresiones | Cota superior del IC 95 % de M4 (90 días) ≤ la tasa puntual de los PRs humanos de los mismos repos. Con 0 regresiones en 150, la cota es ~2 % (regla del tres) [Cierto] | M4 |
| 3 | Trampas | Cota superior del IC 95 % de M5 ≤ 2 % en el brazo habilitado, con ≥ 150 canarias | M5 |
| 4 | Sin edición humana | M3 ≥ 80 % en los últimos 50 PRs de C | M3 |
| 5 | Mantenibilidad | M7d y M7e dentro del IC de los PRs humanos; M7a sin empeoramiento significativo | M7 |
| 6 | Tiempo | ≥ 8 semanas desde el primer PR de C, para que la ventana de 90 días de M4 cubra al menos la primera mitad del volumen | — |

**El volumen domina sobre el tiempo.** Con pocas decenas de PRs por mes [Suposición], la condición 1 puede tardar varios trimestres.

### Auto-merge con red de seguridad

- Solo en el brazo (ejecutor × modelo × `config_sha`) que cumplió el criterio. **Cambiar de modelo o de prompt reinicia el contador** de la condición 1, aunque la condición 4 puede arrancar con los datos de M8 del conjunto congelado.
- Un 5 % de los auto-merges se muestrea para revisión humana a posteriori.
- **Salida automática del modo**: una regresión atribuible confirmada, una canaria con trampa o una caída de M3 por debajo del 60 % devuelven la clase a merge humano hasta que se cumpla de nuevo el criterio.

### Clases que nunca entran

Autenticación, facturación, infraestructura, migraciones de datos y contratos públicos ([00](../00-vision.md) §4).

## Consecuencias

- F3 depende del volumen de la clase C1 en los repos piloto. Si el volumen no llega, F3 no ocurre: el criterio no se relaja por calendario.
- Hay que medir M4 sobre los PRs humanos desde F0, para tener baseline.

## Cómo revertir

Desactivar el auto-merge es un cambio de configuración del publicador (por clase). El criterio está en este ADR, así que endurecerlo o relajarlo es un ADR nuevo con datos.
