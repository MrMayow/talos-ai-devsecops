# Модели Ollama

## Strict

Установите базовые модели и создайте alias из этого каталога:

```bash
ollama pull qwen2.5:14b-instruct
ollama pull qwen2.5-coder:14b
ollama create sim-qwen25-instruct:14b -f models/Modelfile.instruct
ollama create sim-qwen25-coder:14b -f models/Modelfile.coder
```

Команды выполняются из корня репозитория. В Windows можно использовать `models/install-models.ps1`; скрипт ожидает, что базовые модели уже скачаны.

`sim-qwen25-instruct:14b` используется для требований, review и классификации ошибок. `sim-qwen25-coder:14b` — для архитектуры, генерации и исправления кода. Modelfile фиксируют контекст 30720 токенов и низкую температуру.

Контекст выбран под исходный стенд с RTX 4080 SUPER 16 GB. Это не универсальная гарантия размещения в VRAM: оно зависит от квантизации, версии runtime, параллелизма и других процессов. Начинайте с одного активного LLM-запроса.

## Demo

Demo exports используют `qwen3-coder-next:latest`. Размер этой модели существенно отличается от 14B. Проверьте доступную память, скорость и structured output до запуска всей цепочки. Замена имени модели в Agent не отменяет ограничения входного контекста и формата ответа.

## Проверка

```powershell
.\models\smoke-test.ps1 -OllamaUrl http://127.0.0.1:11434
```

Скрипт проверяет два strict alias на коротких JSON Schema-запросах. Успешный smoke test подтверждает подключение и формат короткого ответа, но не качество большой генерации.

Для доступа из VM используйте адрес хоста, достижимый из Kubernetes, и ограничьте firewall. Ключи Gitea и kubeconfig в Ollama prompts не передаются.
