#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f lab.env ] || [ ! -f generated/kubeconfig ]; then
  echo "Не найдены lab.env или generated/kubeconfig."
  exit 1
fi

source lab.env
export KUBECONFIG="$ROOT_DIR/generated/kubeconfig"

section() {
  printf '\n============================================================\n%s\n============================================================\n' "$1"
}

section "Talos"
talosctl --talosconfig generated/talosconfig --nodes "$TALOS_IP" version || true
talosctl --talosconfig generated/talosconfig --nodes "$TALOS_IP" get volumestatus || true

section "Kubernetes nodes"
kubectl get nodes -o wide || true

section "Storage"
kubectl get storageclass || true
kubectl get pvc -A || true

section "Gitea"
kubectl get pod,svc,pvc -n gitea || true

section "CI runner"
kubectl get pod,pvc -n ci || true

section "Sim"
kubectl get pod,pvc -n simstudio || true

section "Доступные URL"
echo "Gitea:   http://${TALOS_IP}:${GITEA_NODEPORT}"
echo "Ollama:  http://${WINDOWS_IP}:11434"
echo "Sim:     http://localhost:3000 после kubectl port-forward"
