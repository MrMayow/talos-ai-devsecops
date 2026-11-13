# Gitea CI

Скопируйте `.gitea/` и `ci/` из этого каталога в корень целевого приложения Gitea. Pipeline рассчитан на Python 3.12/FastAPI, Docker и runner с label `talos-host`.

## Порядок проверок

1. Получить и проверить текущий PR head, выполнить checkout на его SHA.
2. Собрать test image и запустить pytest.
3. Выполнить Semgrep.
4. Собрать runtime image, проверить `/health`.
5. Выполнить OWASP ZAP Baseline.
6. Сформировать и опубликовать пакет результатов.
7. Применить quality gate; при ошибке вызвать Workflow 04.

Политика хранится в `ci/policy.json`. Ошибки pytest, находки Semgrep, неуспешный runtime smoke, blocking ZAP и ошибки публикации блокируют gate. ZAP WARN сохраняются в отчёте, но не блокируют его. Fuzzing отключён.

## События

Первый запуск происходит на `pull_request: opened/reopened`. Событие `synchronized` намеренно не используется: одно исправление может состоять из нескольких файловых commit. Workflow 04 после записи всех файлов делает один `workflow_dispatch` с итоговым PR context.

Обязательные поля dispatch: `pr_number`, `context_version`, `repair_attempt`, `run_id`. SHA берётся из текущего PR через API; SHA default branch из окружения dispatch не используется как версия приложения.

После ручного изменения открытого PR проверку нужно вызвать через `workflow_dispatch` с тем же контекстом. Автоматического повторного запуска на каждый push нет.

## Настройки

Переменные и ключи перечислены в [инструкции](../docs/setup.md) и [config](../config/gitea-actions-variables.example). Для внешних образов предусмотрены `PYTHON_BASE_IMAGE`, `SEMGREP_IMAGE`, `ZAP_IMAGE` и `CURL_IMAGE`; в контролируемом окружении укажите проверенные digest. Defaults с `latest`/`stable` оставлены для лаборатории и могут меняться.

`AI_MAX_REPAIR_ATTEMPTS=5` ограничивает callback. Gitea `Attempt 1` — счётчик конкретного Actions run, а не AI-цикла. Номер repair виден в run-name, логах и `ci-summary.json`.

Pipeline выполняет код приложения в контейнере с доступными job credentials. Privileged runner подходит только для доверенной закрытой лаборатории; подробнее в [security](../docs/security.md).
