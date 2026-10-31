# ADR-0002 · Orquestador del pipeline

- **Estado**: aceptada · contiene **evidencia nueva contra una tesis** (sección 4), pendiente de que el propietario la valide · **Fecha**: 2026-10-31

## Contexto

La tesis 3 pide un pipeline determinista sin LLM supervisor y la tesis 8, pipelines en DOT compatibles con el spec Attractor. F0 no necesita orquestador más allá del runner del harness. F1 necesita un flujo issue → spec → ejecutor → verificador → reintentos → PR en borrador → `needs-human`.

## Opciones

1. **Fork de Tracker** (2389-research, MIT): el motor más completo, con checkpoints, `--max-cost` en céntimos, fan-out a worktrees y puertas humanas [Cierto].
2. **LangGraph (librería, MIT) con NATS**: continuidad con la plataforma del propietario.
3. **Runner propio mínimo** que interpreta un subconjunto de DOT.

## Datos verificados el 2026-10-31

- **Tracker ha marcado su parser DOT como *deprecated***: «Deprecated: Use .dip format with FromDippinIR instead» (`pipeline/parser.go`). El CHANGELOG 0.69.0 hace de `.dip` la autoridad de los ejemplos [Cierto]. El lenguaje `.dip` ([2389-research/dippin-lang](https://github.com/2389-research/dippin-lang)) **no tiene licencia** [Cierto]. Tiene 2 contribuidores humanos principales [Cierto].
- **El spec Attractor no tiene commits desde el 2026-03-17** [Cierto]. **Kilroy** (la otra implementación DOT) no tiene commits desde el 2026-04-27 [Cierto]. La implementación TypeScript `brynary/attractor` está **archivada** [Cierto].
- Que el flujo de F1 sea **lineal con un bucle de reintento** es juicio propio.

## Decisión

**Runner propio mínimo** que interpreta un **subconjunto de DOT** con la semántica de Attractor:
- formas `box` (nodo ejecutor), `diamond` (condición), `hexagon` (puerta humana) y `Msquare` (salida);
- aristas con `condition="outcome=…"`;
- checkpoint tras cada nodo.

El subconjunto se documenta y se valida con un linter. La propuesta es mantener el runner por debajo de ~400 líneas [Suposición].

- LangGraph se descarta para el pipeline: el grafo es lineal, y meter un framework no mueve ninguna métrica (tesis 7). Puede usarse **dentro** de un nodo si algún día un ejecutor lo necesita.
- Tracker queda como **referencia**: con DOT deprecado ya no sirve de plan de salida que comparta formato.

## Consecuencias

- La complejidad del runner se controla con el linter del subconjunto. Nada de LLM en las aristas.
- Las ejecuciones de pipeline son reproducibles: DOT versionado + `config_sha` + checkpoints en JSONL.

## 4. Evidencia contra la tesis 8 (para el propietario)

La tesis 8 elige DOT «compatible con el spec de Attractor» como formato portable entre runners. Con los datos de hoy:
- el spec está parado;
- el motor más completo abandona DOT por un formato sin licencia;
- la segunda implementación está parada.

**El valor de portabilidad de DOT/Attractor es hoy menor de lo que asumía la tesis** [Probable]. DOT sigue teniendo valor como formato de grafo legible, con herramientas estándar (Graphviz) y sin dependencias, así que **la decisión no cambia**. Lo que cambia es la razón: ya no es portabilidad entre motores, sino un formato simple y propio. Se pregunta en [09](../09-open-questions.md).

## Cómo revertir

El DOT es el contrato. Si el runner propio crece por encima de su límite, o si aparece un motor DOT mantenido, se ejecuta el mismo fichero con ese motor. Tracker todavía parsea DOT aunque esté deprecado [Cierto].
