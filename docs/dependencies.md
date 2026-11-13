# Зависимости и происхождение кода

Репозиторий содержит конфигурацию лаборатории, workflow, сборщики, тесты и пример приложения. Он не содержит исходный код Talos, SIM, Gitea или веса языковых моделей.

| Компонент | Источник | Использование |
|---|---|---|
| Talos Linux | [siderolabs/talos](https://github.com/siderolabs/talos) | ОС узла |
| SIM | [simstudioai/sim](https://github.com/simstudioai/sim) | Исполнение workflow и Helm chart |
| Gitea | [go-gitea/gitea](https://github.com/go-gitea/gitea) | Репозитории, Packages, Actions |
| Gitea runner | [gitea.com/gitea/act_runner](https://gitea.com/gitea/act_runner) | CI executor |
| Ollama | [ollama/ollama](https://github.com/ollama/ollama) | Локальный model server |
| Qwen | [Qwen](https://huggingface.co/Qwen) | Модели; условия зависят от выбранных весов |
| Local Path Provisioner | [rancher/local-path-provisioner](https://github.com/rancher/local-path-provisioner) | Локальные PVC |
| Semgrep | [semgrep/semgrep](https://github.com/semgrep/semgrep) | Статический анализ |
| OWASP ZAP | [zaproxy/zaproxy](https://github.com/zaproxy/zaproxy) | Динамический анализ |
| FastAPI | [fastapi/fastapi](https://github.com/fastapi/fastapi) | Пример и целевой профиль |

Лицензия MIT этого репозитория распространяется на его собственные материалы. Она не меняет лицензии перечисленных компонентов, контейнерных образов и моделей. При сборке распространяемого продукта нужно отдельно проверить фактические версии, транзитивные зависимости и условия весов.

Talos-скрипты сохраняют версии лабораторной линии: Talos 1.13.6, SIM 0.7.29, Gitea 1.26.4 и runner 2.0.1-dind. Это зафиксированная совместимость исходной лаборатории, а не рекомендация использовать старые версии на публичном сервере. Новое развёртывание с этими файлами требует проверки доступности образов и актуальных исправлений безопасности.

Документация платформ: [Talos](https://docs.siderolabs.com/), [SIM](https://docs.sim.ai/), [Gitea Actions](https://docs.gitea.com/usage/actions/overview/), [Gitea runner](https://docs.gitea.com/usage/actions/act-runner/).
