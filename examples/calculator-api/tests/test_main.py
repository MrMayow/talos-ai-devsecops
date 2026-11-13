from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_addition() -> None:
    response = client.post(
        "/calculate",
        json={
            "left": 2,
            "right": 3,
            "operation": "add",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"result": 5.0}


def test_division_by_zero_is_rejected() -> None:
    response = client.post(
        "/calculate",
        json={
            "left": 5,
            "right": 0,
            "operation": "divide",
        },
    )

    assert response.status_code == 400


def test_boolean_is_not_accepted_as_number() -> None:
    response = client.post(
        "/calculate",
        json={
            "left": 0.0,
            "right": False,
            "operation": "add",
        },
    )

    assert response.status_code == 422


def test_bad_request_is_documented_in_openapi() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200

    schema = response.json()
    responses = schema["paths"]["/calculate"]["post"]["responses"]

    assert "400" in responses
    assert "422" in responses


def test_security_headers() -> None:
    response = client.get("/")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["cache-control"] == "no-store"
