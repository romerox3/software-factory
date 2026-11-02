# infra/verifier

`isolation-check.sh` es el comando de aceptación de F0-21 ([07](../../docs/07-roadmap.md)). Comprueba en la máquina única de F0 ([ADR-0011](../../docs/adr/0011-single-host-f0.md)) que el generador no llega al verificador:

| # | Comprobación | Cómo |
|---|---|---|
| 1 | El almacén de tareas tiene permisos 700 y es del usuario de la factory | `stat` |
| 2 | Ningún contenedor en marcha ni ninguna carpeta de tareas o jobs de Harbor llega al almacén | `docker inspect` de los montajes y `find` de enlaces simbólicos |
| 3 | Un sandbox de agente solo llega al gateway | Tarea Harbor con `network_mode = "allowlist"` y el agente `oracle`: el gateway responde; example.com y api.github.com no |
| 4 | El contenedor del verificador no tiene red | `factory.verifier.sandbox.DockerSandbox` intenta abrir una conexión TCP al gateway |
| 5 | Una key de agente no puede emitir keys del equipo verificador | `POST /key/generate` con la key de agente y el equipo verificador: 401 o 403 |

Termina con exit 0 solo si pasan las cinco.

## Configuración

Los valores no viven en el repo. El script lee un fichero de entorno (por defecto `~/factory-f0/isolation.env`, o el que indique `FACTORY_ISOLATION_ENV`) con:

| Variable | Qué es |
|---|---|
| `FACTORY_GATEWAY_URL` | URL pública del gateway, la misma que usan los sandboxes |
| `FACTORY_STORE` | Carpeta del almacén de tareas |
| `FACTORY_AGENT_KEY` | Una virtual key del equipo de generación, con presupuesto mínimo |
| `FACTORY_VERIFIER_TEAM` | `team_id` del equipo verificador |
| `FACTORY_HARBOR_DIRS` | Carpetas de tareas y jobs de Harbor, separadas por espacios |
| `FACTORY_HARBOR` (opcional) | Comando de Harbor; por defecto `uvx --from harbor==0.25.0 harbor` |
| `FACTORY_PROBE_IMAGE` (opcional) | Imagen de la sonda; por defecto `python:3.12-slim` |

Se ejecuta en la máquina de F0, desde la copia del código:

```bash
bash infra/verifier/isolation-check.sh
```

Si la comprobación 5 falla porque se llegó a crear una key, el script lo avisa. Esa key caduca a los 5 minutos y hay que revocarla con la master key.

## Qué no cubre

- Escapes del contenedor: la capa gVisor o Kata queda para antes de F1 ([ADR-0011](../../docs/adr/0011-single-host-f0.md)).
- El DNS hacia el resolvedor sigue abierto en el sandbox de agente (riesgo residual de [02](../../docs/02-architecture.md) §6).
- La comprobación 2 mira lo que está en marcha cuando se ejecuta. Los montajes de Harbor los define Harbor (carpetas del job), y por eso se comprueba que esas carpetas quedan fuera del almacén.
