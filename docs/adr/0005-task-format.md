# ADR-0005 · Formato de tarea: OpenSpec

- **Estado**: aceptada · **Fecha**: 2026-10-31

## Contexto

La tarea es la entrada del contrato de ejecutor y la unidad del harness. La tesis 8 pide formatos en ficheros versionados. Hay que separar lo que ve el agente de lo que solo ve el verificador.

## Opciones

1. **OpenSpec** ([Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec), MIT, verificado el 2026-10-31): `openspec/changes/<id>/` con `proposal.md`, `design.md`, `tasks.md` y `specs/`.
2. **GitHub Spec Kit** (MIT): plantillas más pesadas, con hooks de ciclo de vida.
3. **Formato propio** (YAML).
4. **El formato de tarea de Harbor** directamente.

## Decisión

**OpenSpec para la parte visible**, más una **extensión propia para la parte oculta**, que nunca vive en el árbol OpenSpec:

```
task-store/                     (privado si data_class != public)
  visible/<task_id>/            → se replica a la torre
    openspec/changes/<task_id>/{proposal.md, design.md?, tasks.md?, specs/…}
    factory.task.json           (class, visible_tests, base commit, image, budget)
  hidden/<task_id>/             → solo existe en el verificador
    test.patch  gold.patch  f2p.json  p2p.json  holdouts/  verifier.json (test command, allowlist, mutation config)
```

El formato de Harbor es un **derivado** generado desde `visible/` ([ADR-0001](0001-harness-runner.md)), no la fuente.

## Consecuencias

- Hay que escribir dos esquemas pequeños: `factory.task.json` y `verifier.json` (backlog de F0).
- El hash de la tarea (`task.sha256` del contrato) se calcula sobre `visible/`. El verificador comprueba que el run se hizo con esa versión (T13).
- OpenSpec es Markdown: leerlo no depende de su CLI.

## Cómo revertir

Un conversor de `visible/` a otro formato (Spec Kit o YAML propio). La parte oculta no cambia.
