#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
source lab.env
export KUBECONFIG="$ROOT_DIR/generated/kubeconfig"
umask 077
mkdir -p external generated

if [ ! -d external/sim/.git ]; then
  git clone --depth 1 --branch "$SIM_VERSION" https://github.com/simstudioai/sim.git external/sim
elif [ "$(git -C external/sim describe --tags --exact-match 2>/dev/null || true)" != "$SIM_VERSION" ]; then
  echo "external/sim не соответствует $SIM_VERSION. Проверьте локальные изменения и версию chart."
  exit 1
fi

SECRETS_FILE="$ROOT_DIR/generated/sim-secrets.env"
touch "$SECRETS_FILE"
chmod 600 "$SECRETS_FILE" 2>/dev/null || true
for name in BETTER_AUTH_SECRET ENCRYPTION_KEY INTERNAL_API_SECRET CRON_SECRET POSTGRES_PASSWORD; do
  if ! grep -q "^${name}=" "$SECRETS_FILE"; then
    printf '%s=%s\n' "$name" "$(openssl rand -hex 32)" >> "$SECRETS_FILE"
  fi
done
source "$SECRETS_FILE"

VALUES_FILE="$ROOT_DIR/generated/sim-values.yaml"
cat > "$VALUES_FILE" <<EOF
app:
  image:
    tag: "${SIM_VERSION}"
  env:
    BETTER_AUTH_SECRET: "${BETTER_AUTH_SECRET}"
    ENCRYPTION_KEY: "${ENCRYPTION_KEY}"
    INTERNAL_API_SECRET: "${INTERNAL_API_SECRET}"
    CRON_SECRET: "${CRON_SECRET}"
    NEXT_PUBLIC_APP_URL: "http://localhost:3000"
    BETTER_AUTH_URL: "http://localhost:3000"
    NEXT_PUBLIC_SOCKET_URL: "http://localhost:3002"
    EXECUTION_TIMEOUT_FREE: "1800"
    OLLAMA_URL: "http://${WINDOWS_IP}:11434"
realtime:
  image:
    tag: "${SIM_VERSION}"
  env:
    ALLOWED_ORIGINS: "http://localhost:3000"
migrations:
  image:
    tag: "${SIM_VERSION}"
postgresql:
  auth:
    password: "${POSTGRES_PASSWORD}"
EOF

# Rendered values contain credentials and stay in ignored generated/.
helm template sim external/sim/helm/sim --namespace simstudio \
  --values "$VALUES_FILE" > generated/sim-rendered.yaml
helm upgrade --install sim external/sim/helm/sim --namespace simstudio \
  --create-namespace --values "$VALUES_FILE" --wait --timeout 20m

if [ "${ENABLE_GITEA_LOOPBACK_PROXY:-false}" = true ]; then
  kubectl -n simstudio patch deployment "${SIM_APP_DEPLOYMENT:-sim-app}" \
    --type strategic --patch-file manifests/30-sim-gitea-loopback-proxy-patch.yaml
  kubectl -n simstudio rollout status deployment/"${SIM_APP_DEPLOYMENT:-sim-app}" --timeout=10m
fi

kubectl -n simstudio get deployments,services,pods,pvc
printf '\nPort-forward commands are in docs/operations.md. Check the deployment names above.\n'
