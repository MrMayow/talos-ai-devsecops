# Эксплуатация лаборатории

Команды Talos выполняются в Bash из `infra/talos`. Перед работой загрузите окружение:

```bash
source lab.env
export KUBECONFIG="$PWD/generated/kubeconfig"
export TALOSCONFIG="$PWD/generated/talosconfig"
```

## Запуск

1. Запустите Ollama на машине с GPU.
2. Включите существующую Talos VM и дождитесь готовности узла.
3. Выполните `bash scripts/08-status.sh`.
4. Посмотрите фактические имена deployment в SIM namespace:

   ```bash
   kubectl -n simstudio get deployments,services
   ```

5. В двух отдельных окнах Bash поднимите port-forward, указав свои имена:

   ```bash
   kubectl -n simstudio port-forward deployment/sim-app 3000:3000
   ```

   ```bash
   kubectl -n simstudio port-forward deployment/sim-realtime 3002:3002
   ```

6. Откройте `http://localhost:3000`. В Gitea проверьте, что runner находится в состоянии online/idle.

Ранняя конфигурация chart может создавать `sim-sim-app` вместо `sim-app`. Для port-forward используется имя из вывода `kubectl`, а не предположение из инструкции.

## Остановка

Дождитесь завершения CI и workflow, сохраните изменения в SIM. Остановите оба port-forward через Ctrl+C. Затем:

```bash
talosctl --talosconfig "$TALOSCONFIG" --endpoints "$TALOS_IP" \
  --nodes "$TALOS_IP" shutdown --wait=false
```

Дождитесь выключения VM, затем закройте Ollama. Повторный запуск установочных скриптов при обычном включении не нужен.

## Диагностика

| Симптом | Что проверить |
|---|---|
| kubectl обращается к localhost:8080 | Указан ли `KUBECONFIG` в текущем терминале |
| SIM показывает Reconnecting | Realtime deployment и port-forward 3002 |
| Нет ответа модели | Ollama `/api/tags` с хоста и доступность URL из SIM |
| Gitea job ждёт runner | Online-статус, область регистрации, `runs-on: talos-host` |
| Packages возвращает 401/403 | PAT, scopes и владелец пакета |
| development contract возвращает 404 | `AI_CONTEXT_OWNER` совпадает с `artifact_owner` |
| Ноль файлов после генерации | Structured output, JSON Schema и `finishReason` модели |
| Каждое исправление называется Attempt 1 | Это счётчик Actions run; AI repair вынесен в run-name |
| После ручного commit не начался CI | Вызвать dispatch: pipeline не подписан на synchronized |

Не публикуйте полные execution exports: в старых версиях SIM в них могут оказаться разрешённые значения заголовков Authorization. Для issue достаточно имени блока, статуса, обезличенного traceback и схемы входа.

## Резервирование

До изменения инфраструктуры сохраните экспорты SIM и резервные копии Gitea/PostgreSQL. Для локального VMware-стенда можно сделать холодную копию всей VM. При наличии snapshot нужны базовый диск и вся цепочка delta-дисков, а не только последний VMDK.

Периодически проверяйте восстановление копии в отдельной VM. Существование snapshot само по себе не подтверждает возможность восстановления базы.
