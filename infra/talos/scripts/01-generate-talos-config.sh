#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f lab.env ]; then
  echo "Нет файла lab.env. Скопируйте lab.env.example в lab.env и заполните его."
  exit 1
fi

# shellcheck disable=SC1091
source lab.env

if [[ "$INSTALLER_IMAGE" == PASTE_* ]]; then
  echo "В lab.env не заполнена переменная INSTALLER_IMAGE."
  echo "Скопируйте полную строку installer image из Talos Image Factory."
  exit 1
fi

mkdir -p generated

if [ -e generated/controlplane.yaml ] || [ -e generated/talosconfig ]; then
  echo "Конфигурация уже существует. Для нового кластера используйте отдельный каталог."
  exit 1
fi

umask 077

cat > generated/controlplane-patch.yaml <<EOF_PATCH
cluster:
  allowSchedulingOnControlPlanes: true
EOF_PATCH

echo "Создаю конфигурацию Talos..."
echo "Кластер:      $CLUSTER_NAME"
echo "Talos IP:     $TALOS_IP"
echo "Диск:         $INSTALL_DISK"
echo "Версия:       $TALOS_VERSION"
echo "Installer:    $INSTALLER_IMAGE"
echo

talosctl gen config \
  "$CLUSTER_NAME" \
  "https://${TALOS_IP}:6443" \
  --talos-version "$TALOS_VERSION" \
  --install-disk "$INSTALL_DISK" \
  --install-image "$INSTALLER_IMAGE" \
  --config-patch-control-plane @generated/controlplane-patch.yaml \
  --output-dir generated

cat >> generated/controlplane.yaml <<EOF_VOLUMES
---
apiVersion: v1alpha1
kind: VolumeConfig
name: EPHEMERAL
provisioning:
  diskSelector:
    match: system_disk
  minSize: 20GiB
  maxSize: ${EPHEMERAL_MAX_SIZE}
  grow: false
---
apiVersion: v1alpha1
kind: UserVolumeConfig
name: local-path-provisioner
provisioning:
  diskSelector:
    match: system_disk
  minSize: ${LOCAL_STORAGE_MIN_SIZE}
  maxSize: ${LOCAL_STORAGE_MAX_SIZE}
EOF_VOLUMES

echo
echo "Созданы файлы:"
echo "  generated/controlplane.yaml"
echo "  generated/worker.yaml"
echo "  generated/talosconfig"
echo "  В controlplane.yaml также добавлены EPHEMERAL и UserVolumeConfig для постоянного хранилища."
echo
echo "Проверьте installer image в controlplane.yaml:"
grep -A 4 -n "install:" generated/controlplane.yaml | head -n 8 || true
