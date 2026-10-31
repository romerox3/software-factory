# ADR-0003 · Sandbox por fase: Docker frente a E2B Embed

- **Estado**: aceptada · **Fecha**: 2026-10-31

## Contexto

El ejecutor corre código no confiable con una virtual key. Hace falta: aislamiento de ficheros, salida de red solo hacia el gateway, un snapshot sin historial y reproducibilidad. E2B Embed ofrece microVM Firecracker con firewall de egress por dominio en un solo host, pero exige `/dev/kvm` [Cierto según el informe; el repo ahora es [e2b-dev/runtime](https://github.com/e2b-dev/runtime), Apache-2.0, verificado el 2026-10-31].

## Opciones

1. Docker en todas las fases.
2. Docker en F0–F1 y E2B Embed en F2+.
3. E2B Embed desde F0.

## Decisión

**Docker en F0 y F1**:
- red dedicada `factory-egress` con regla de host en `DOCKER-USER`;
- control de egress de Harbor donde el kernel lo soporte;
- imágenes fijadas por digest;
- usuario no root.

**E2B Embed (u otra microVM) en F2+** solo si se cumple al menos una de estas condiciones:
- (a) se ejecutan en el mismo host brazos con distinta `data_class`;
- (b) best-of-n necesita fork o snapshot de memoria para que M6 sea viable;
- (c) aparece un escape de contenedor relevante.

Requisito previo: confirmar que la torre o un Hetzner dedicado exponen `/dev/kvm` ([09](../09-open-questions.md)).

## Consecuencias

- Hasta F2, el aislamiento depende del kernel compartido. Es aceptable porque el código ejecutado es de repos propios o del piloto, y los agentes son de proveedores conocidos.
- La regla de red en el host es obligatoria aunque Harbor aplique la suya (defensa en profundidad).

## Cómo revertir

El sandbox lo crea el runner. Cambiar a E2B o a otra microVM es cambiar el entorno del runner (Harbor ya trae un entorno `e2b` [Cierto, `harbor/environments/e2b.py`]) y la regla de red.
