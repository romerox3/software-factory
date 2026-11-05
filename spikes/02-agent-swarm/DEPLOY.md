# Llevar el spike a una máquina compartida

Qué cambia cuando el compose de este directorio pasa de la máquina del spike a una del equipo con nginx y un certificado HTTPS. Los nombres de host, las claves y la URL de inferencia van en el `.env` de esa máquina, nunca aquí.

## Lo que se queda igual

- Las redes: ningún servicio de Agent Swarm en una red con salida, y relés `socat` para el gateway, el puerto de la API y el verificador ([README](README.md), «Montaje»).
- Las cuatro condiciones del resultado:
  1. La API sin ruta a internet.
  2. `CONTEXT_MODE_DISABLED=true`.
  3. Las tareas programadas de serie desactivadas.
  4. El enunciado envuelto en `prompts/base-v1.md`.
- Una virtual key del gateway por agente, con `max_budget`, como pide la regla 2.

## Lo que cambia

| Pieza | En el spike | En la máquina compartida |
|---|---|---|
| Panel | Ninguno: la prueba iba por la API | Imagen `ghcr.io/desplega-ai/agent-swarm-ui` con la misma versión que la API, fijada por digest, detrás de nginx. No el panel alojado en `app.agent-swarm.dev`, que carga la analítica de Plausible [Cierto, `ui/index.mdx`] |
| Acceso a la API | `127.0.0.1:3013` a través de `api-port` | nginx en HTTPS hacia `api-port`. En la API: `CORS_ALLOWED_ORIGINS`, `APP_URL` y `PUBLIC_MCP_BASE_URL` con el origen público |
| Personas | Una `API_KEY` de operador | `RBAC_ENABLED=true` (ya está) y un token `aswt_` por persona desde People → Tokens. La `API_KEY` de operador no se reparte: el panel guarda las claves en el almacenamiento del navegador |
| Feedback del panel | No aplica | El botón de feedback envía a `proxy.desplega.sh` [Cierto, `apps/ui/src/api/hooks/use-feedback.ts`]. Hay que poner la config global `feedback_endpoint` en una URL local que no responda |
| Modelo | El gateway de la factory, compatible con `/v1/messages` | La URL de inferencia del equipo. Claude Code necesita un endpoint compatible con la API de Anthropic. Si solo es compatible con OpenAI, el worker tiene que ser OpenCode o Codex, y entonces pesa la matriz: OpenCode quedó entre 0,15 y 0,23 de pass@1 por debajo de los otros tres brazos |
| Verificador | Servicio en el host por socket Unix, con las tareas en `store/` | Igual, pero con su propio almacén de tareas. Para trabajo real, el diff sale del repo que toca el worker y no de un snapshot |
| Egress | El firewall de la máquina del spike ya corta el tráfico de los contenedores al host | Con root se puede cerrar además con una regla en `DOCKER-USER` |

## nginx: dos orígenes

Es el despliegue más sencillo que admite Agent Swarm: el panel en un subdominio y la API en otro [Cierto, `ui/index.mdx`, «Self-hosting»]. Las páginas que generan los agentes (`/p/*`) ejecutan scripts, así que nunca deben servirse desde el origen del panel.

```nginx
# panel: estático, sin estado
server {
    listen 443 ssl;
    server_name <panel>;
    location / { proxy_pass http://127.0.0.1:8080; }
}
# API, también para el WebSocket de /api/realtime
server {
    listen 443 ssl;
    server_name <api>;
    location / {
        proxy_pass http://127.0.0.1:3013;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
    }
}
```

## Preguntas para cerrar con el equipo

1. ¿La URL de inferencia es compatible con la API de Anthropic (`/v1/messages`)? Si no lo es, se decide qué harness usa el worker.
2. ¿El certificado cubre dos subdominios, o es de un solo nombre? Con un solo nombre hace falta el despliegue de origen único, en el que el visor de páginas no funciona.
3. ¿Quién guarda la clave de operador y quién reparte los tokens por persona?
4. ¿El verificador corre en esa máquina, con Docker para las imágenes de tests, o en otra?
5. ¿Qué entradas se conectan primero (Jira, GitHub, Slack)? Cada integración que se active abre una salida a internet desde la API.
