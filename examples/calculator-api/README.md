# Calculator API

Небольшое приложение для проверки инструментов и CI-профиля. Оно работает без SIM, Ollama, Gitea и Kubernetes. Код взят из ранней демонстрационной линии стенда и оставлен как проверяемый пример.

Из корня репозитория после установки `requirements-dev.txt`:

```bash
cd examples/calculator-api
python -m pytest -q
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Пример запроса:

```bash
curl http://127.0.0.1:8000/calculate \
  -H 'Content-Type: application/json' \
  -d '{"left":2,"right":3,"operation":"add"}'
```

Ожидаемый ответ: `{"result":5.0}`. `/health` возвращает `{"status":"ok"}`. OpenAPI доступен по `/openapi.json`, интерактивная документация — по `/docs`.

Поддерживаются add, subtract, multiply и divide. Входная модель не преобразует boolean в число, ограничивает диапазон операндов и отклоняет неизвестные операции. Деление на ноль возвращает 400.

Dockerfile содержит отдельные test и runtime targets:

```bash
docker build --target test -t calculator-tests .
docker run --rm calculator-tests
docker build --target runtime -t calculator-api .
docker run --rm -p 127.0.0.1:8000:8000 calculator-api
```

Контейнер запускается от непривилегированного пользователя. Образ Python не закреплён digest в примере; для фиксированного окружения используйте `--build-arg PYTHON_BASE_IMAGE=...`.
