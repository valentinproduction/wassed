from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

import main

# TestClient без `with` НЕ запускає startup/shutdown, тому реальне підключення до БД не створюється
client = TestClient(main.app)

PRODUCT_URL = main.PRODUCT_SERVICE_URL


@pytest.fixture
def db(monkeypatch):
    """Підміняє виклики до БД на AsyncMock."""
    execute = AsyncMock()
    fetch_all = AsyncMock()
    monkeypatch.setattr(main.database, "execute", execute)
    monkeypatch.setattr(main.database, "fetch_all", fetch_all)
    return SimpleNamespace(execute=execute, fetch_all=fetch_all)


# ---------- POST /orders ----------

def test_create_order_success(respx_mock, db):
    respx_mock.get(f"{PRODUCT_URL}/1").respond(json={"id": 1, "name": "Laptop", "price": 1200.50})
    respx_mock.get(f"{PRODUCT_URL}/2").respond(json={"id": 2, "name": "Phone", "price": 800.00})

    # 1-й execute -> id замовлення, 2-й -> вставка позицій
    db.execute.side_effect = [1, None]
    db.fetch_all.return_value = [
        {"id": 1, "order_id": 1, "product_id": 1, "quantity": 1},
        {"id": 2, "order_id": 1, "product_id": 2, "quantity": 2},
    ]

    payload = [
        {"product_id": 1, "quantity": 1},
        {"product_id": 2, "quantity": 2},
    ]
    response = client.post("/orders", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["id"] == 1
    assert data["total_amount"] == 2800.50
    assert [i["product_id"] for i in data["items"]] == [1, 2]
    assert db.execute.await_count == 2

    # перший запит — вставка замовлення з правильною сумою
    first_query = db.execute.await_args_list[0].args[0]
    assert first_query.compile().params["total_amount"] == 2800.50


def test_create_order_product_not_found(respx_mock, db):
    respx_mock.get(f"{PRODUCT_URL}/99").respond(status_code=404)

    response = client.post("/orders", json=[{"product_id": 99, "quantity": 1}])

    assert response.status_code == 400
    assert "Product with id 99 not found" in response.json()["detail"]
    db.execute.assert_not_awaited()


def test_create_order_product_service_unavailable(respx_mock, db):
    respx_mock.get(f"{PRODUCT_URL}/1").mock(side_effect=httpx.ConnectError("refused"))

    response = client.post("/orders", json=[{"product_id": 1, "quantity": 1}])

    assert response.status_code == 503
    assert "Cannot connect to Product service" in response.json()["detail"]
    db.execute.assert_not_awaited()


def test_create_order_product_service_timeout(respx_mock, db):
    respx_mock.get(f"{PRODUCT_URL}/1").mock(side_effect=httpx.ConnectTimeout("timeout"))

    response = client.post("/orders", json=[{"product_id": 1, "quantity": 1}])

    assert response.status_code == 503
    db.execute.assert_not_awaited()


def test_create_order_one_missing_product_rejects_whole_order(respx_mock, db):
    respx_mock.get(f"{PRODUCT_URL}/1").respond(json={"id": 1, "name": "Laptop", "price": 1200.50})
    respx_mock.get(f"{PRODUCT_URL}/99").respond(status_code=404)

    response = client.post(
        "/orders",
        json=[{"product_id": 1, "quantity": 1}, {"product_id": 99, "quantity": 1}],
    )

    assert response.status_code == 400
    db.execute.assert_not_awaited()


def test_create_order_invalid_payload_returns_422(db):
    response = client.post("/orders", json=[{"product_id": "abc", "quantity": 1}])

    assert response.status_code == 422
    db.execute.assert_not_awaited()


# ---------- GET /orders ----------

def test_get_all_orders_empty(db):
    db.fetch_all.return_value = []

    response = client.get("/orders")

    assert response.status_code == 200
    assert response.json() == []


def test_get_all_orders_returns_created_order(db):
    order = SimpleNamespace(id=1, total_amount=300.0)
    items = [{"id": 1, "order_id": 1, "product_id": 1, "quantity": 3}]
    # 1-й fetch_all -> список замовлень, 2-й -> позиції замовлення
    db.fetch_all.side_effect = [[order], items]

    response = client.get("/orders")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == 1
    assert data[0]["total_amount"] == 300.0
    assert data[0]["items"][0]["quantity"] == 3


def test_get_all_orders_multiple(db):
    orders = [
        SimpleNamespace(id=1, total_amount=100.0),
        SimpleNamespace(id=2, total_amount=250.0),
    ]
    db.fetch_all.side_effect = [
        orders,
        [{"id": 1, "order_id": 1, "product_id": 5, "quantity": 1}],
        [{"id": 2, "order_id": 2, "product_id": 6, "quantity": 2}],
    ]

    response = client.get("/orders")

    assert response.status_code == 200
    assert [o["id"] for o in response.json()] == [1, 2]