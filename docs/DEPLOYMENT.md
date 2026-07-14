# Deploying muLLM

`pip install` installs muLLM but never starts it automatically. For a desktop first run:

```bash
python -m pip install https://github.com/mybrainrunslinux/mullm/releases/download/v0.9.1/mullm-0.9.1-py3-none-any.whl
mullm-server
# Open http://127.0.0.1:6856/setup
```

Set `MULLM_OPEN_BROWSER=1` if server startup should open the setup page automatically.

## Persistent local service

The CLI can create a current-user service for Linux, a LaunchAgent for macOS, or startup instructions for Windows:

```bash
mullm --install-service
mullm --status
```

On Linux it writes `~/.config/systemd/user/mullm.service`:

```bash
systemctl --user status mullm
journalctl --user -u mullm -f
systemctl --user restart mullm
```

For a manually supervised bare-metal process:

```bash
export MULLM_STATE_DIR=/var/lib/mullm
export MULLM_DEV_MODE=false
export MULLM_API_KEY='replace-with-a-long-random-token'
exec mullm-server
```

## Rootless Podman

Build the included image and keep mutable state outside the container:

```bash
podman build -t localhost/mullm:0.9.1 .
podman volume create mullm-data
podman run --name mullm --replace --detach \
  --publish 127.0.0.1:6856:6856 \
  --volume mullm-data:/data:Z \
  --env MULLM_REMOTE_ACCESS=true \
  --env MULLM_DEV_MODE=false \
  --env MULLM_API_KEY="$MULLM_API_KEY" \
  localhost/mullm:0.9.1
podman healthcheck run mullm
```

The image points Ollama at `host.containers.internal:11434` by default. Override `MULLM_OLLAMA_BASE_URL` when the compatible inference backend runs elsewhere. Keep the published port on `127.0.0.1` unless a firewall or authenticated reverse proxy protects it.

## Kubernetes

Build and push the image to a registry your cluster can pull from, then substitute that image below. Start with one replica because budgets, the A2A registry, and some request/session state are process-local.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: mullm-secrets
type: Opaque
stringData:
  MULLM_API_KEY: replace-with-a-long-random-token
  # ANTHROPIC_API_KEY: optional
  # OPENAI_API_KEY: optional
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: mullm-state
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 10Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mullm
spec:
  replicas: 1
  selector:
    matchLabels: {app: mullm}
  template:
    metadata:
      labels: {app: mullm}
    spec:
      containers:
        - name: mullm
          image: registry.example.com/mullm:0.9.1
          ports:
            - {name: http, containerPort: 6856}
          env:
            - {name: MULLM_REMOTE_ACCESS, value: "true"}
            - {name: MULLM_DEV_MODE, value: "false"}
            - {name: MULLM_STATE_DIR, value: /data}
            - {name: MULLM_OLLAMA_BASE_URL, value: "http://ollama.default.svc.cluster.local:11434"}
          envFrom:
            - secretRef: {name: mullm-secrets}
          volumeMounts:
            - {name: state, mountPath: /data}
          readinessProbe:
            httpGet: {path: /health, port: http}
            initialDelaySeconds: 5
          livenessProbe:
            httpGet: {path: /health, port: http}
            initialDelaySeconds: 20
            periodSeconds: 30
          resources:
            requests: {cpu: "250m", memory: 512Mi}
            limits: {memory: 2Gi}
      volumes:
        - name: state
          persistentVolumeClaim: {claimName: mullm-state}
---
apiVersion: v1
kind: Service
metadata:
  name: mullm
spec:
  selector: {app: mullm}
  ports:
    - {name: http, port: 6856, targetPort: http}
```

Apply and verify it:

```bash
kubectl apply -f mullm.yaml
kubectl rollout status deployment/mullm
kubectl port-forward service/mullm 6856:6856
curl -H "Authorization: Bearer $MULLM_API_KEY" http://127.0.0.1:6856/health
```

Terminate TLS at an Ingress or gateway. Do not expose `/setup`, MCP, A2A, or the OpenAI-compatible API publicly without authentication and normal network controls.

## Multiple replicas and clustered backends

muLLM can sit behind a load balancer, but 0.9.1 is not a fully shared-state control plane. Before increasing `replicas`:

- keep the model server external and shared, or schedule one model backend per GPU node;
- use sticky sessions for streaming and session-oriented requests;
- give each replica its own writable state volume unless its storage backend explicitly supports concurrent writers;
- expect per-process A2A registration, cancellation, and in-flight request state;
- enforce the cloud-spend ceiling outside muLLM too—a per-process budget multiplied across replicas is not a cluster-wide cap;
- aggregate logs and metrics at the platform layer.

For high availability today, an active/passive pair with one active writer is safer than active replicas sharing a SQLite/cache directory. A shared cache, agent registry, and distributed budget ledger require additional architecture rather than merely increasing the Kubernetes replica count.
