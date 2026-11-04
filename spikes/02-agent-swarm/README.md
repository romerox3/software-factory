# Spike 02 · Agent Swarm con el gateway y el verificador de la factory

Prueba de corte de [ADR-0013](../../docs/adr/0013-verification-layer-over-agent-swarm.md). La pregunta es si Agent Swarm (desplega-ai, v2.7.10) puede ser la plataforma sobre la que va esta factory sin perder lo que la regla 2, la 3 y la 4 de `CLAUDE.md` exigen. No mide si Agent Swarm resuelve más o menos tareas que la matriz: el worker no trae el entorno de cada tarea (ver «Límites»).

## Montaje

- Un worker de Claude Code, sin lead. Cada nodo `agent-task` lleva el `agentId` del worker y se enruta como `human_pinned`, sin que ningún modelo elija destino [Cierto, `src/workflows/executors/agent-task.ts`].
- El modelo es un alias del gateway puesto con `ANTHROPIC_DEFAULT_*_MODEL`. Agent Swarm descarta un `MODEL_OVERRIDE` con un prefijo que no sea de Anthropic, como `factory/` [Cierto, `guides/provider-auth/model-gateways.mdx`].
- Redes (`docker-compose.yml`):
  - `swarm-int`, interna, sin salida: todos los servicios menos el proxy.
  - `egress`: solo el proxy `socat`, que reenvía TCP al gateway en el 443. El worker resuelve el host del gateway al proxy con `extra_hosts`, así que el TLS va de extremo a extremo.
  - `verifier`: solo la API. El servicio del verificador escucha en la IP de esa red en el host, de modo que el worker no lo alcanza.
- Sin `TEMPLATE_ID`: el worker se bajaría la plantilla de `templates.agent-swarm.dev` al arrancar [Cierto, `src/commands/runner.ts`].
- Telemetría apagada con `ANONYMIZED_TELEMETRY=false` en la API y en los agentes [Cierto, `reference/telemetry.mdx`]. Sin túnel: solo lo crea `install.sh`.
- El verificador no corre dentro del nodo `script`, que es un proceso en el contenedor de la API sin Docker [Cierto, `src/workflows/executors/script.ts`]. El nodo llama a `verifier_service.py` en el host, que saca el diff del directorio del worker contra el commit del snapshot y se lo pasa a `python -m factory.verifier`.

## Cómo se ejecuta (en la torre, con la matriz parada)

```bash
cd ~/factory-f0/as-spike-src           # copia de este directorio
cp .env.example .env                   # rellenar; las imágenes, por digest tras el primer pull
mkdir -p secrets && openssl rand -hex 32 > secrets/encryption_key
docker compose pull && docker compose up -d
(cd ~/factory-f0/code && .venv/bin/python ../as-spike-src/verifier_service.py \
   --store ../store --work "$SPIKE_WORK_DIR" --out ../as-spike/verifier) &
./run_spike.sh tasks.txt 2             # 4-5 tareas ya medidas en la matriz, dos repeticiones
```

`tasks.txt` lleva cinco tareas de la matriz v1. Tres las resolvió A6 (Claude Code × GLM) en 4 o 5 de 5 intentos y sirven de control: si dentro de Agent Swarm fallan, el problema es la plataforma. Las otras dos (3 y 2 de 5) son las que pueden moverse.

## Criterios de corte y cómo se comprueba cada uno

| # | Criterio | Comprobación |
|---|---|---|
| 1 | La misma entrada recorre los mismos nodos | `path` igual en las dos repeticiones de cada tarea (`results.jsonl`) |
| 2 | Los workers pasan por el gateway con su virtual key | La key del worker aparece en `/spend/logs` del gateway con el modelo esperado; no hay otra credencial en el contenedor |
| 3 | La red del worker solo alcanza el gateway | Desde el worker: el gateway responde; `pypi.org`, `github.com`, `templates.agent-swarm.dev` y `172.31.241.1:8787` no |
| 4 | El verificador corre aparte del worker | El veredicto sale del servicio del host; el worker no ve `store/hidden` ni el servicio |
| 5 | Sin túnel y con la telemetría apagada | Ningún proceso de túnel, `ANONYMIZED_TELEMETRY=false` en cada servicio y ninguna conexión saliente de la API a internet durante la prueba (conntrack en el host sobre la subred de `verifier`) |

Si fallan el 2 o el 3, la plataforma queda bloqueada para código `client-product`.

## Límites

- La red `verifier` es un bridge normal, así que la API tiene salida a internet. Si la telemetría o algún otro componente sale, se ve en conntrack (criterio 5). Para cerrarla, una regla en `DOCKER-USER` que solo deje a esa subred hablar con el host.
- El worker trabaja con la imagen de Agent Swarm, no con la de la tarea: no tiene las dependencias para ejecutar los tests del repo. Comparar su pass@1 con el de la matriz no es justo; para eso haría falta un worker por imagen de tarea (los *runtime pools* de Agent Swarm, sin probar).
- `agent-fs` arranca con `EMBEDDING_PROVIDER=local` en una red sin salida. Si necesita bajarse un modelo al arrancar, fallará y habrá que darle salida o cambiar el proveedor.

## Resultados

Pendiente.
