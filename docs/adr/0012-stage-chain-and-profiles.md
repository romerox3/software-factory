# ADR-0012 · La factory como cadena de etapas con perfiles de software

- **Estado**: aceptada · **Fecha**: 2026-11-02 · **Sustituye**: el alcance «tarea especificada → parche verificado → PR» de 00 y 07 (versión del 2026-10-31)

## Contexto

El diseño original solo cubría el tramo de implementar y verificar. El propietario señaló que una software factory hace más y que tiene que servir para construir cualquier tipo de software, también productos completos. La investigación del 2026-11-02 lo confirma [Cierto, por fuente]:
- Las definiciones actuales (StrongDM, Osmani, Mastra, PostHog, LaunchDarkly, Factory) incluyen intake, spec, plan, review, despliegue y la vuelta desde producción.
- La construcción de productos completos ya se mide: Vibe Code Bench recorre una app web desplegada con workflows ocultos, y el mejor modelo pasa el 61,8 %.
- La trampa contra tests visibles crece con el tamaño del código (SpecBench: +28 puntos por cada ×10).

## Opciones

1. Mantener el alcance y añadir solo productos completos.
2. Cadena de etapas genérica, con lo específico de cada tipo de software en perfiles intercambiables.
3. Un diseño por tipo de software.

## Decisión

**Opción 2.**
- **Ocho etapas**: entrada, spec, plan, implementar, verificar, integrar, desplegar y operar ([00](../00-vision.md) §3). Cada una entrega un artefacto comprobable y tiene una puerta humana por defecto.
- **Perfil de software**: tres piezas.
  - El **entorno**: cómo se construye y ejecuta.
  - El **oráculo**: cómo se comprueba que funciona.
  - El **despliegue**: dónde y cómo se publica.

  El resto de la cadena no sabe qué perfil corre.
- **Admisión de un perfil**: su oráculo tiene que detectar, con datos, los defectos sembrados y las trampas de las canarias ([06](../06-harness-and-tasks.md) §7).
- **Orden**: núcleo (fase A) → app web interna desde cero (fase B) → cadena completa en el piloto (fase C) → más perfiles (fase D) ([07](../07-roadmap.md)).
- **Lo que no cambia**:
  - el orquestador determinista;
  - el contrato de ejecutor;
  - el gateway con fusible de gasto;
  - el verificador antitrampas;
  - la política de datos;
  - el criterio de auto-merge, que ahora se aplica por etapa, tipo de trabajo y perfil.

## Consecuencias

- Lo construido en F0 pasa a ser el núcleo de E4 y E5. No se descarta nada.
- Hay dos piezas nuevas que diseñar. La primera es el **escritor de escenarios ocultos**: un proceso que el constructor no ve. La segunda es el **ejecutor de escenarios** del perfil app web: un agente de navegador sobre la app desplegada.
- El oráculo de producto es parcialmente blando: un agente de navegador interpreta los pasos. Su fiabilidad se mide con defectos sembrados y con la concordancia con revisión humana antes de confiar en él. Vibe Code Bench informa de una concordancia entre evaluadores muy variable, entre el 31,8 y el 93,6 % por paso [Cierto].
- Las clases de alto riesgo recorren la cadena, pero siempre con puerta humana.

## Cómo revertir

Volver al alcance del 2026-10-31 es quedarse en las etapas E4–E6 con el perfil por defecto. El código de esas etapas no depende de las demás.
