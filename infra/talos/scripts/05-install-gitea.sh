#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
source lab.env
export KUBECONFIG="$ROOT_DIR/generated/kubeconfig"

mkdir -p generated
sed \
  -e "s/__TALOS_IP__/${TALOS_IP}/g" \
  -e "s/__GITEA_NODEPORT__/${GITEA_NODEPORT}/g" \
  manifests/10-gitea.yaml > generated/10-gitea.yaml

echo "Разворачиваю Gitea..."
kubectl apply -f generated/10-gitea.yaml

echo "Ожидаю запуска Gitea..."
kubectl -n gitea rollout status deployment/gitea --timeout=300s
kubectl -n gitea get pod,svc,pvc

echo
echo "Откройте в браузере: http://${TALOS_IP}:${GITEA_NODEPORT}"
echo "На странице установки выберите SQLite3 и создайте администратора."
