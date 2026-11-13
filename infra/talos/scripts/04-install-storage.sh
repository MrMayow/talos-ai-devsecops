#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

export KUBECONFIG="$ROOT_DIR/generated/kubeconfig"

if [ ! -f "$KUBECONFIG" ]; then
  echo "Нет generated/kubeconfig. Сначала завершите bootstrap."
  exit 1
fi

source lab.env

echo "Проверяю пользовательский том Talos..."
talosctl --talosconfig generated/talosconfig --nodes "$TALOS_IP" get volumestatus u-local-path-provisioner || true

echo "Устанавливаю Rancher Local Path Provisioner v0.0.36..."
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.36/deploy/local-path-storage.yaml

echo "Разрешаю privileged helper-pods только в namespace local-path-storage..."
kubectl label namespace local-path-storage \
  pod-security.kubernetes.io/enforce=privileged \
  pod-security.kubernetes.io/audit=privileged \
  pod-security.kubernetes.io/warn=privileged \
  --overwrite

echo "Меняю путь хранения с /opt на Talos user volume..."
kubectl -n local-path-storage patch configmap local-path-config --type merge -p \
  '{"data":{"config.json":"{\n  \"nodePathMap\": [\n    {\n      \"node\": \"DEFAULT_PATH_FOR_NON_LISTED_NODES\",\n      \"paths\": [\"/var/mnt/local-path-provisioner\"]\n    }\n  ]\n}"}}'

kubectl -n local-path-storage rollout restart deployment/local-path-provisioner

echo "Ожидаю запуска provisioner..."
kubectl -n local-path-storage rollout status deployment/local-path-provisioner --timeout=180s

echo "Назначаю StorageClass local-path классом по умолчанию..."
kubectl patch storageclass local-path \
  -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'

echo "Запускаю проверочный PVC и Pod..."
kubectl apply -f manifests/00-storage-test.yaml

for i in $(seq 1 60); do
  phase="$(kubectl get pod storage-test -n storage-test -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  if [ "$phase" = "Running" ]; then
    break
  fi
  sleep 2
done

kubectl get storageclass
kubectl get pvc,pod -n storage-test

echo "Проверяю запись в постоянный том..."
kubectl exec -n storage-test storage-test -- sh -c 'echo storage-ok > /data/check.txt && cat /data/check.txt'

echo
echo "Хранилище работает. Проверочный namespace можно удалить позже:"
echo "  kubectl delete namespace storage-test"
