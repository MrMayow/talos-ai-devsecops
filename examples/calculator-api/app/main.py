from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(
    title="Talos AI DevSecOps Demo",
    version="1.0.0",
    description="Учебное API для проверки полного CI-конвейера.",
)


class ErrorResponse(BaseModel):
    """Стандартный ответ API при ошибке."""

    detail: str


class CalculationRequest(BaseModel):
    """Входная модель калькулятора со строгой проверкой типов."""

    # Запрещает неявные преобразования наподобие false -> 0.
    model_config = ConfigDict(strict=True)

    left: float = Field(..., ge=-1_000_000, le=1_000_000)
    right: float = Field(..., ge=-1_000_000, le=1_000_000)
    operation: str = Field(..., pattern="^(add|subtract|multiply|divide)$")


@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    """Добавляет базовые заголовки безопасности для демонстрационного API."""

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Talos AI DevSecOps demo is running"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/calculate",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Невозможная математическая операция",
        },
    },
)
def calculate(request: CalculationRequest) -> dict[str, float]:
    if request.operation == "add":
        result = request.left + request.right
    elif request.operation == "subtract":
        result = request.left - request.right
    elif request.operation == "multiply":
        result = request.left * request.right
    else:
        if request.right == 0:
            raise HTTPException(
                status_code=400,
                detail="Division by zero is not allowed",
            )
        result = request.left / request.right

    return {"result": result}
