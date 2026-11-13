#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
source lab.env
export KUBECONFIG="$ROOT_DIR/generated/kubeconfig"

cat <<'TEXT'
Перед продолжением откройте Gitea:
  Site Administration -> Actions -> Runners -> Create new Runner
или для runner конкретного репозитория:
  Repository -> Settings -> Actions -> Runners

Скопируйте Registration Token.
TEXT

read -r -s -p "Вставьте Registration Token и нажмите Enter: " RUNNER_TOKEN
echo

if [ -z "$RUNNER_TOKEN" ]; then
  echo "Токен пустой. Отменено."
  exit 1
fi

kubectl create namespace ci --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic gitea-runner-registration \
  -n ci \
  --from-literal=token="$RUNNER_TOKEN" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f manifests/20-runner-identity.yaml

kubectl apply -f manifests/21-runner.yaml
unset RUNNER_TOKEN

echo "Ожидаю запуска runner..."
kubectl -n ci rollout status deployment/gitea-runner --timeout=300s
kubectl -n ci get pod -l app=gitea-runner -o wide

echo
echo "Вернитесь на страницу Runners в Gitea. Runner talos-dind-runner должен стать Active."
