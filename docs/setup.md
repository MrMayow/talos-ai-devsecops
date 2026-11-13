# Настройка

Инструкция предполагает работающие SIM, Ollama, Gitea и Gitea Actions runner с Docker. Вариант установки на Talos описан в [infra/talos](../infra/talos/README.md). Сначала стоит выполнить локальную проверку из README.

## 1 Целевой репозиторий

Создайте в Gitea отдельный репозиторий с веткой `main`, например `labadmin/demo-fastapi`. Включите Actions. Настройте защиту `main`: запрет прямой записи техническим пользователям, обязательный PR и проверка CI перед merge.

Runner должен иметь label `talos-host`. Если используется другое имя, измените `runs-on` в `platform/.gitea/workflows/pipeline.yml`. Этот pipeline рассчитан на Alpine-based DinD runner: первый шаг устанавливает Bash, Git, curl и jq через `apk`.

Скопируйте `.gitea` и `ci` из `platform/` в корень **целевого приложения**, затем сделайте начальный commit. Эти файлы обслуживаются отдельно от генерируемого кода.

## 2 Модели

Для `strict` подготовьте alias по [models/README.md](../models/README.md). Для `demo` подключите `qwen3-coder-next:latest` к Ollama provider SIM и проверьте короткий structured-output запрос. Требования к памяти зависят от весов, квантизации и контекста; модель demo не является заменой 14B с теми же требованиями.

У агента должны быть отключены thinking/reasoning, память и внешние инструменты. JSON Schema в экспортах задаёт формат ответа; лимит output tokens не равен размеру context window.

## 3 Экспорты SIM

Из корня проекта:

```bash
python scripts/export_workflows.py --profile demo --owner labadmin --repo demo-fastapi
```

Импортируйте четыре JSON из `build/imports/demo`, начиная с 04 и заканчивая 01. Для строгого варианта укажите `--profile strict`. Подключение к модели после импорта нужно выбрать в интерфейсе SIM; ключи не включаются в JSON.

Запишите ID workflow из URL редактора. Для внутренней цепочки нужны ID 02 и 03; strict также использует ID 01 для повторной обработки требований. ID 04 будет нужен Gitea runner. После настройки разверните все workflow.

## 4 Подключения и секреты

Создайте отдельные Gitea PAT для оркестратора и CI. У оркестратора — доступ к целевому репозиторию, ветке/PR и публикации его контекста. У CI — чтение репозитория/PR и публикация CI Packages. Область токенов ограничьте средствами используемой версии Gitea; не используйте административный токен.

Значения для SIM перечислены в [config/sim.env.example](../config/sim.env.example):

| Имя | Назначение |
|---|---|
| `GITEA_URL` | Base URL Gitea без `/api/v1` |
| `GITEA_TOKEN` | PAT оркестратора |
| `SIM_INTERNAL_URL` | URL SIM, доступный background worker |
| `SIM_WORKFLOW01_ID` | Повторный запуск требований в strict |
| `SIM_WORKFLOW02_ID`, `SIM_WORKFLOW03_ID` | Автоматические переходы |
| `SIM_WORKFLOW_API_KEY` | Ключ вызова развёрнутых workflow |

Храните ключи в поддерживаемом вашей версией SIM хранилище Secrets. В экспортах используются ссылки `{{GITEA_TOKEN}}` и подобные. Проверьте на одноразовом тестовом ключе, что execution export не раскрывает его значение. Старые сборки могут раскрывать подставленные переменные процесса; в этом случае нельзя считать маскирование обеспеченным.

Gitea Variables: [пример](../config/gitea-actions-variables.example). Gitea Secrets: [имена](../config/gitea-actions-secrets.example). Основные настройки:

| Настройка | Значение |
|---|---|
| `AI_GITEA_URL` | Адрес Gitea, доступный runner |
| `AI_GITEA_USER` | Технический пользователь CI |
| `AI_ARTIFACT_OWNER`, `AI_CONTEXT_OWNER` | Владелец соответствующих Generic Packages |
| `AI_ARTIFACT_PACKAGE` | `ci-artifacts` |
| `AI_CONTEXT_PACKAGE` | `development-contracts` |
| `AI_REVISE_ENABLED` | `true` для callback при красном CI |
| `AI_REVISE_DRY_RUN` | Сначала `true`, после проверки — `false` |
| `AI_REVISE_CALLBACK_REQUIRED` | `true` |
| `AI_MAX_REPAIR_ATTEMPTS` | `5` |
| `SIM_INTERNAL_URL`, `SIM_WORKFLOW04_ID` | Доступный runner endpoint исправления |

В Gitea Actions создаются Secrets `AI_GITEA_TOKEN` и `SIM_WORKFLOW_API_KEY`. Пользовательские Gitea Variables имеют префикс `AI_`; внутренний префикс `CI_` в pipeline используется уже после их чтения.

`AI_CONTEXT_OWNER` должен совпадать с `artifact_owner`, который передаётся в Workflow 01. Имя владельца репозитория и имя владельца Packages могут отличаться — проверяйте оба.

## 5 Адреса и доступ

`localhost` относится к текущему контейнеру. URL, открывающийся в браузере Windows, не обязательно доступен из SIM worker или DinD. Проверьте по отдельности SIM → Ollama, SIM → Gitea, runner → Gitea и runner → SIM.

Если legacy SIM блокирует приватный адрес Gitea, в Talos-каталоге есть ограниченный loopback proxy. Это отдельная настройка совместимости, описанная в [безопасности](security.md); по умолчанию она выключена.

## 6 Первый запуск

В Workflow 01 задайте owner, repo и artifact owner, соответствующие экспорту. Используйте запрос из [проверочного сценария](demo.md). Сначала проверьте согласования и dry-run исправления, затем разрешите запись в тестовую AI-ветку. Результаты сохраняйте для одного конкретного SHA.
