#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
source lab.env

if [ ! -f generated/controlplane.yaml ]; then
  echo "Нет generated/controlplane.yaml. Сначала выполните 01-generate-talos-config.sh"
  exit 1
fi

echo "Диски, обнаруженные Talos в maintenance mode:"
talosctl get disks --insecure --nodes "$TALOS_IP"
echo
echo "В lab.env выбран диск: $INSTALL_DISK"
echo "ВНИМАНИЕ: выбранный диск будет полностью перезаписан."
read -r -p "Введите слово INSTALL, чтобы продолжить: " answer

if [ "$answer" != "INSTALL" ]; then
  echo "Отменено."
  exit 1
fi

echo "Применяю конфигурацию к $TALOS_IP..."
talosctl apply-config \
  --insecure \
  --nodes "$TALOS_IP" \
  --file generated/controlplane.yaml

echo
echo "Команда отправлена. Talos установится на диск и перезагрузится."
echo "Теперь отключите ISO в настройках VMware: VM Settings -> CD/DVD -> снимите Connect at power on."
