#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

printf '\nПроверка программ, необходимых на Windows...\n\n'

failed=0
for tool in talosctl kubectl helm git curl openssl; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf '[OK] %-10s -> %s\n' "$tool" "$(command -v "$tool")"
  else
    printf '[НЕТ] %-10s не найден в PATH\n' "$tool"
    failed=1
  fi
done

printf '\nВерсии:\n'
talosctl version --client 2>/dev/null || true
kubectl version --client 2>/dev/null || true
helm version --short 2>/dev/null || true
git --version 2>/dev/null || true

if [ ! -f lab.env ]; then
  printf '\n[ВНИМАНИЕ] Файл lab.env не найден.\n'
  printf 'Скопируйте lab.env.example в lab.env и заполните значения.\n'
  failed=1
fi

if [ "$failed" -ne 0 ]; then
  printf '\nПроверка завершилась с замечаниями. Сначала исправьте их.\n'
  exit 1
fi

printf '\nВсе базовые инструменты найдены.\n'
