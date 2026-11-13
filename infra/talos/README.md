# Одноузловой стенд Talos

Этот каталог содержит установочные файлы лаборатории Talos/Kubernetes с Gitea, runner и SIM. Скрипты выполняются вручную и по порядку; общего unattended installer нет.

Исходная конфигурация VM: 12 vCPU, 36 GB RAM, диск 300 GB, EFI, сеть NAT. Ollama работает на хосте с GPU. Для нескольких проектов или недоверенного CI этот одноузловой вариант не рассчитан.

## Подготовка

Установите `talosctl`, `kubectl`, Helm, Git, curl и OpenSSL. Версию `talosctl` согласуйте с Talos. Загрузите VMware-совместимый installer из [Talos Image Factory](https://factory.talos.dev/) и создайте VM с пустым диском.

Из этого каталога:

```bash
cp lab.env.example lab.env
```

Заполните IP Talos, адрес хоста с Ollama, installer image и целевой диск. `lab.env` и всё содержимое `generated/` остаются локальными. Сгенерированные конфигурации содержат ключи доступа к кластеру.

## Установка

| Скрипт | Действие |
|---|---|
| `00-check-tools.sh` | Проверка инструментов и окружения |
| `01-generate-talos-config.sh` | Создание конфигурации и разметки томов |
| `02-apply-talos-config.sh` | Установка на выбранный диск; требуется ввод `INSTALL` |
| `03-bootstrap-cluster.sh` | Однократный etcd bootstrap и получение kubeconfig |
| `04-install-storage.sh` | Local Path Provisioner и тестовый PVC |
| `05-install-gitea.sh` | Gitea и постоянное хранилище |
| `06-install-runner.sh` | Регистрация runner для доверенного репозитория |
| `07-install-sim.sh` | SIM из выбранного upstream Helm chart |
| `08-status.sh` | Чтение состояния компонентов |

Вызывайте выбранный шаг как `bash scripts/00-check-tools.sh`. Шаг 02 перезаписывает выбранный диск; это установка новой VM, а не способ включения существующего стенда. Шаг 01 отказывается перезаписывать существующие ключи и machine config.

После установки Gitea создайте административную учётную запись в её UI, затем отдельные технические аккаунты и репозиторий приложения. Registration token runner вводится скрыто. Runner не получает RoleBinding на namespace приложений и не монтирует Kubernetes service-account token; DinD остаётся привилегированным.

Скрипт установки SIM хранит Helm values с секретами в локальном `generated/`, не передаёт их через аргументы процесса и не выводит rendered manifest в терминал. Он не сбрасывает локальный checkout upstream через force checkout. Патч loopback proxy применяется только при явном включении.

Имена deployment/Service зависят от версии chart. Проверьте их через `kubectl -n simstudio get deployments,services` и укажите `SIM_APP_DEPLOYMENT`/`SIM_REALTIME_DEPLOYMENT` в lab.env. В [эксплуатации](../../docs/operations.md) описаны port-forward и штатное выключение.

## После инфраструктуры

Следуйте [настройке workflow](../../docs/setup.md). Скрипты инфраструктуры сами не импортируют JSON, не создают PAT, не изменяют GitHub-репозиторий и не выполняют merge приложения.

При обновлении старой лаборатории проверьте существующие RoleBinding и сохраните резервную копию данных. Новые manifests не удаляют автоматически ранее созданные объекты. Ограничения privileged runner описаны в [security](../../docs/security.md).
