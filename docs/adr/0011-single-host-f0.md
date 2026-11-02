# ADR-0011 · En F0 la factory corre en la torre; el host del gateway solo da el gateway

- **Estado**: aceptada · **Fecha**: 2026-11-02 · **Sustituye en F0**: la ubicación del verificador de [02](../02-architecture.md) §3 y la tarea F0-21 de [07](../07-roadmap.md)

## Contexto

El diseño ponía el verificador, el minero y el almacén oculto en el host del gateway (Hetzner) para separar por máquina al generador del verificador (tesis 2). Al ejecutar F0-17 y F0-21 aparecieron dos hechos:

- El host del gateway es **aarch64** (Neoverse-N1, vServer) y no tiene `/dev/kvm` [Cierto, comprobado el 2026-11-02]. Las imágenes de las tareas públicas son solo x86_64 (`sweb.eval.x86_64.*`) [Cierto]. Allí solo se podrían ejecutar emulando con qemu-user, que es lento y no siempre funciona [Probable].
- La torre es x86_64 con `/dev/kvm` [Cierto]. El propietario la quería solo para inferencia, pero decide que corra también las tareas y el verificador.

El propietario pidió además que la factory no se reparta entre máquinas sin necesidad.

## Opciones

1. Servidor x86 nuevo para verificador y sandboxes.
2. Torre para todo menos el gateway.
3. Emulación x86 en el host del gateway.

## Decisión

**Opción 2.** En F0, la torre ejecuta los sandboxes de los agentes, el minero y la revalidación, el verificador y vLLM. El host del gateway solo sirve el gateway que ya existía; no se instala nada más en él.

La separación entre generador y verificador, en la torre:
- El almacén de tareas (visible y oculto) vive en una carpeta del usuario de la factory con permisos 700 que **nunca se monta** en un sandbox. El agente solo ve su copia del repo, construida a partir del snapshot sin historial.
- El verificador corre en contenedores efímeros sin red, a los que solo llegan los bytes del diff (regla 3 de `CLAUDE.md`).
- La capa extra contra escapes del contenedor (gVisor con la plataforma KVM, o microVMs con Kata) queda fuera de F0. La torre tiene `/dev/kvm`, así que se puede añadir sin cambiar nada más [Cierto]. Harbor respeta `DOCKER_HOST` y se puede apuntar a un daemon con otro runtime [Cierto, `harbor/environments/docker/docker.py`].

## Consecuencias

- Con datos públicos, la tesis 2 se mantiene por proceso y por montaje, no por máquina. Un escape del contenedor del agente llegaría al almacén oculto. Es un riesgo aceptado en F0, porque las tareas y sus tests son públicos.
- Desaparecen el pull de artefactos entre zonas y el mirror en Hetzner. El usuario y el Docker rootless que se montaron en el host del gateway el 2026-11-01 se borran.
- Los sandboxes compiten con vLLM por RAM (30 GB) y disco. La concurrencia de F0-18 se limita a 2–3 sandboxes, con el tope de memoria por contenedor de la tarea.
- **Antes de F1** (código del cliente) se revisa esta decisión: usuario propio para el verificador, gVisor o Kata para los sandboxes, o una máquina aparte. Queda como pregunta abierta en [09](../09-open-questions.md).

## Cómo revertir

Mover el almacén oculto y el verificador a otra máquina x86 y restaurar el pull de artefactos de [02](../02-architecture.md). El código no depende de la máquina: el verificador recibe rutas y una imagen por digest.
