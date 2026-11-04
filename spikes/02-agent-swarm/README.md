# Spike 02 · Agent Swarm con el gateway y el verificador de la factory

Prueba de corte de [ADR-0013](../../docs/adr/0013-verification-layer-over-agent-swarm.md). La pregunta es si Agent Swarm (desplega-ai, v2.7.10) puede ser la plataforma sobre la que va esta factory sin perder lo que la regla 2, la 3 y la 4 de `CLAUDE.md` exigen. No mide si Agent Swarm resuelve más o menos tareas que la matriz: el worker no trae el entorno de cada tarea (ver «Límites»).

## Montaje

- Un worker de Claude Code, sin lead. Cada nodo `agent-task` lleva el `agentId` del worker y se enruta como `human_pinned`, sin que ningún modelo elija destino [Cierto, `src/workflows/executors/agent-task.ts`].
- El modelo es un alias del gateway puesto con `ANTHROPIC_DEFAULT_*_MODEL`. Agent Swarm descarta un `MODEL_OVERRIDE` con un prefijo que no sea de Anthropic, como `factory/` [Cierto, `guides/provider-auth/model-gateways.mdx`].
- Redes (`docker-compose.yml`). Ningún servicio de Agent Swarm está en una red con salida; solo los relés `socat`:
  - `swarm-int`, interna: todos los servicios de Agent Swarm.
  - `egress`: solo `egress-proxy`, que reenvía TCP al gateway en el 443. El worker resuelve el host del gateway al proxy con `extra_hosts`, así que el TLS va de extremo a extremo.
  - `verifier`, interna: la API y `verifier-proxy`. Este relé reenvía al servicio del verificador por un socket Unix montado desde el host (`VERIFIER_SOCKET_DIR`), así que no necesita ruta al host. El worker no está en esta red.
  - `host-port`: solo `api-port`, que publica la API en `127.0.0.1:3013`. Docker no publica puertos de un servicio que solo está en redes internas.
- `CONTEXT_MODE_DISABLED=true` en los agentes. El plugin context-mode de la imagen del worker ejecuta `npm install better-sqlite3` en el hook de antes de cada herramienta; sin salida, cada llamada se queda colgada [Cierto, visto en la prueba del 2026-11-04].
- `run_spike.sh` desactiva al empezar todas las tareas programadas y workflows que trae la instalación. Una base de datos nueva arranca con cuatro activas: `dreaming-daily`, `daily-swarm-update-check`, `daily-status-report` y `daily-blocker-digest` [Cierto, `GET /api/schedules` en la v2.7.10]. Las tres de agente le darían trabajo al worker cada noche con su clave.
- Sin `TEMPLATE_ID`: el worker se bajaría la plantilla de `templates.agent-swarm.dev` al arrancar [Cierto, `src/commands/runner.ts`].
- Telemetría apagada con `ANONYMIZED_TELEMETRY=false` en la API y en los agentes [Cierto, `reference/telemetry.mdx`]. Sin túnel: solo lo crea `install.sh`.
- El verificador no corre dentro del nodo `script`, que es un proceso en el contenedor de la API sin Docker [Cierto, `src/workflows/executors/script.ts`]. El nodo llama a `verifier_service.py` en el host a través del relé; el servicio saca el diff del directorio del worker contra el commit del snapshot y se lo pasa a `python -m factory.verifier`.

## Cómo se ejecuta (en la torre, con la matriz parada)

```bash
cd ~/factory-f0/as-spike-src           # copia de este directorio
cp .env.example .env                   # rellenar; las imágenes, por digest tras el primer pull
mkdir -p secrets && openssl rand -hex 32 > secrets/encryption_key
docker compose pull && docker compose up -d
(cd ~/factory-f0/code && .venv/bin/python ../as-spike-src/verifier_service.py \
   --store ../store --work "$SPIKE_WORK_DIR" --out ../as-spike/verifier \
   --socket "$VERIFIER_SOCKET_DIR/verifier.sock") &
./run_spike.sh tasks.txt 2             # 4-5 tareas ya medidas en la matriz, dos repeticiones
```

`tasks.txt` lleva cinco tareas de la matriz v1. Tres las resolvió A6 (Claude Code × GLM) en 4 o 5 de 5 intentos y sirven de control: si dentro de Agent Swarm fallan, el problema es la plataforma. Las otras dos (3 y 2 de 5) son las que pueden moverse.

## Criterios de corte y cómo se comprueba cada uno

| # | Criterio | Comprobación |
|---|---|---|
| 1 | La misma entrada recorre los mismos nodos | `path` igual en las dos repeticiones de cada tarea (`results.jsonl`) |
| 2 | Los workers pasan por el gateway con su virtual key | La key del worker aparece en `/spend/logs` del gateway con el modelo esperado; no hay otra credencial en el contenedor |
| 3 | La red del worker solo alcanza el gateway | Desde el worker: el gateway y la API responden; `pypi.org`, `github.com`, `templates.agent-swarm.dev`, una IP pública, los puertos del host y `verifier-proxy` no |
| 4 | El verificador corre aparte del worker | El veredicto sale del servicio del host; el worker no ve `store/hidden` ni el servicio |
| 5 | Sin túnel y con la telemetría apagada | Ningún proceso de túnel, `ANONYMIZED_TELEMETRY=false` en la API y los agentes, y ninguna conexión de la API fuera de las redes internas durante la prueba (muestreo de `/proc/net/tcp` del contenedor cada 5 s; en la torre no hay `conntrack` sin sudo) |

Si fallan el 2 o el 3, la plataforma queda bloqueada para código `client-product`.

## Límites

- La API descarga el catálogo de modelos de `models.dev` al arrancar y cada pocas horas, sin variable para apagarlo [Cierto, `src/be/pricing-refresh.ts`; visto en la primera prueba, cuando la API aún tenía salida]. Aquí no sale porque no tiene red con ruta. En una instalación con la API expuesta habría que cortarlo en el firewall.
- El firewall de la torre descarta el tráfico de los contenedores hacia el host, de ahí el socket Unix en lugar de una IP del host.
- El worker trabaja con la imagen de Agent Swarm, no con la de la tarea: no tiene las dependencias para ejecutar los tests del repo. Comparar su pass@1 con el de la matriz no es justo; para eso haría falta un worker por imagen de tarea (los *runtime pools* de Agent Swarm, sin probar).
- `agent-fs` arranca con `EMBEDDING_PROVIDER=local` en una red sin salida. Si necesita bajarse un modelo al arrancar, fallará y habrá que darle salida o cambiar el proveedor.

## Resultados

Pendiente.
