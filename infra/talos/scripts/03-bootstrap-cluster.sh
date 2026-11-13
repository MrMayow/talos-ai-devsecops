#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
source lab.env

if [ ! -f generated/talosconfig ]; then
  echo "Нет generated/talosconfig. Сначала выполните предыдущие шаги."
  exit 1
fi

echo "Настраиваю endpoint talosctl..."
talosctl --talosconfig generated/talosconfig config endpoints "$TALOS_IP"

echo
echo "Проверяю связь с Talos API..."
talosctl --talosconfig generated/talosconfig --nodes "$TALOS_IP" version

echo
echo "Bootstrap etcd выполняется только один раз для нового кластера."
read -r -p "Введите BOOTSTRAP, если кластер еще не bootstrap-нут: " answer

if [ "$answer" = "BOOTSTRAP" ]; then
  talosctl --talosconfig generated/talosconfig \
    bootstrap \
    --nodes "$TALOS_IP"
else
  echo "Bootstrap пропущен."
fi

echo
echo "Получаю kubeconfig..."
talosctl --talosconfig generated/talosconfig \
  kubeconfig generated/kubeconfig \
  --nodes "$TALOS_IP" \
  --force

echo
echo "Проверяю здоровье Talos..."
talosctl --talosconfig generated/talosconfig \
  health \
  --nodes "$TALOS_IP" || true

echo
echo "Проверяю Kubernetes..."
KUBECONFIG=generated/kubeconfig kubectl get nodes -o wide
KUBECONFIG=generated/kubeconfig kubectl get pods -A

echo
echo "Для следующих команд используйте:"
echo "  export KUBECONFIG=\"$ROOT_DIR/generated/kubeconfig\""
