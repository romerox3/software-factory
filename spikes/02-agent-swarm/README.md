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

## Cómo se ejecuta (en una máquina sin otras cargas)

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
| 5 | Sin túnel y con la telemetría apagada | Ningún proceso de túnel, `ANONYMIZED_TELEMETRY=false` en la API y los agentes, y ninguna conexión de la API fuera de las redes internas durante la prueba (muestreo de `/proc/net/tcp` del contenedor cada 5 s; en la máquina del spike no había `conntrack` sin sudo) |

Si fallan el 2 o el 3, la plataforma queda bloqueada para código `client-product`.

## Límites

- La API descarga el catálogo de modelos de `models.dev` al arrancar y cada pocas horas, sin variable para apagarlo [Cierto, `src/be/pricing-refresh.ts`; visto en la primera prueba, cuando la API aún tenía salida]. Aquí no sale porque no tiene red con ruta. En una instalación con la API expuesta habría que cortarlo en el firewall.
- El firewall de la máquina del spike descarta el tráfico de los contenedores hacia el host, de ahí el socket Unix en lugar de una IP del host.
- El worker trabaja con la imagen de Agent Swarm, no con la de la tarea: no tiene las dependencias para ejecutar los tests del repo. Comparar su pass@1 con el de la matriz no es justo; para eso haría falta un worker por imagen de tarea (los *runtime pools* de Agent Swarm, sin probar).
- `agent-fs` arranca con `EMBEDDING_PROVIDER=local` en una red sin salida. Si necesita bajarse un modelo al arrancar, fallará y habrá que darle salida o cambiar el proveedor.

## Resultados (2026-11-04, Agent Swarm v2.7.10)

Cinco tareas, dos repeticiones, un worker de Claude Code con `factory/glm-5.3-flash` y un tope de 25 min por ejecución. Los datos crudos están en el almacén privado (`spikes/02-agent-swarm/`).

| Tarea | Spike | A6 en la matriz |
|---|---|---|
| psd-tools-551 | 2/2 | 5/5 |
| loguru-1451 | 2/2 | 5/5 |
| jsonpickle-588 | 2/2 | 4/5 |
| narwhals-3480 | 0/2: una supera el tope, otra `reject` por `dg.skip-marker` | 3/5 |
| markdown-1587 | 0/2: las dos superan el tope | 2/5 |

Las tres tareas de control salen 6/6, así que la plataforma no estropea al worker [Cierto]. Las dos difíciles no se pueden comparar: la matriz daba a A6 30 min y 60 turnos, y aquí el tope era de 25 min sin límite de turnos.

| # | Criterio | Resultado |
|---|---|---|
| 1 | Mismos nodos con la misma entrada | **Cumple.** Las 7 ejecuciones que terminaron siguieron `implement → verify`. Las 3 que superaron el tope se cancelaron en `implement`, y el worker cogió la siguiente sin arrastrar la anterior. El destino lo fija el `agentId` y ningún modelo elige ruta |
| 2 | Todo pasa por el gateway con la virtual key | **Cumple.** 726 llamadas, todas con la clave del worker y a `factory/glm-5.3-flash` (38,9 M tokens). En el worker no hay más credenciales que esa clave y la `API_KEY` del swarm |
| 3 | El worker solo alcanza el gateway | **Cumple.** Llega al gateway y a la API. pypi, github, `templates.agent-swarm.dev`, una IP pública, los puertos del host y `verifier-proxy` quedan cortados |
| 4 | El verificador va aparte | **Cumple.** Todos los veredictos salen del servicio del host. El worker solo monta su directorio de trabajo y dos volúmenes del swarm; no ve `store/`. El verificador rechazó un diff que añadía un marcador de skip |
| 5 | Sin túnel ni telemetría | **Cumple con la configuración de este directorio, no con la de serie.** Con salida a internet, la API descarga el catálogo de `models.dev`. Sin redes con ruta, durante las 10 ejecuciones solo abrió conexiones a 172.31.240.0/24 |

Configuración de serie que hubo que cambiar. Para una instalación compartida, estos son requisitos:

1. La API sin ruta a internet: la descarga de `models.dev` no se puede apagar.
2. `CONTEXT_MODE_DISABLED=true` en los agentes, o el hook del plugin se cuelga sin salida.
3. Desactivar las cuatro tareas programadas que vienen activas.
4. El enunciado con el prompt base de la factory. Sin él, el worker editó los tests y el diff-guard lo rechazó.

### El lead (2026-11-05, psd-tools-551, una ejecución por variante)

- **Con la tarea asignada al lead sin más indicaciones**, no delegó. Intentó hacerla él mismo, no encontró el repositorio (solo lo monta el worker) y abortó por el canal de aborto: 16 turnos en 200 s.
- **Pidiéndole que delegue**, tardó 6 min en crear la subtarea. Reescribió el encargo y conservó las reglas de `base-v1` (tests de solo lectura, sin red), pero le quitó al worker el canal de aborto. Se dio por terminado sin esperar al worker, así que el nodo siguiente de un workflow habría verificado un directorio vacío. El worker tardó 25 min (con `agentId` fijado había tardado entre 8 y 14) y el verificador dio `accept`.
- **Gasto en el gateway**, con una clave propia para el lead: 38 llamadas y 0,8 M tokens del lead en las dos pruebas, frente a 6 M del worker en esa tarea.

Veredicto para el ADR-0013: Agent Swarm puede ser la plataforma, con el verificador de la factory como nodo y estas cuatro condiciones. Para cambios de código, workflow con `agentId` fijado: el lead no siempre delega y no espera al worker. No se han probado los *runtime pools* con la imagen de cada tarea.
