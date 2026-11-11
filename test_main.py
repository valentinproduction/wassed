from datetime import date, timedelta

import pytest
import requests
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

PRODUCT_URL = "http://localhost:8080/products"


@pytest.fixture(autouse=True)
def reset_state():
    """Ізоляція тестів: кожен тест починає з порожнього «сховища» замовлень."""
    main.orders.clear()
    main.order_id_counter = 0
    yield
    main.orders.clear()
    main.order_id_counter = 0


# ---------- POST /orders (create_order) ----------

def test_create_order_success(requests_mock):
    requests_mock.get(f"{PRODUCT_URL}/1", json={"id": 1, "name": "Laptop", "price": 1200.50})
    requests_mock.get(f"{PRODUCT_URL}/2", json={"id": 2, "name": "Smartphone", "price": 800.00})

    payload = [
        {"product_id": 1, "quantity": 1},
        {"product_id": 2, "quantity": 2},
    ]
    response = client.post("/orders", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["id"] == 1
    assert data["items"][0]["product_id"] == 1
    assert data["items"][1]["product_id"] == 2
    assert data["total_amount"] == 2800.50
    assert data["deliveryDate"] == (date.today() + timedelta(days=5)).isoformat()


def test_create_order_product_not_found(requests_mock):
    requests_mock.get(f"{PRODUCT_URL}/99", status_code=404)

    response = client.post("/orders", json=[{"product_id": 99, "quantity": 1}])

    assert response.status_code == 400
    assert "Product with id 99 not found" in response.json()["detail"]
    assert main.orders == {}


def test_create_order_product_service_unavailable(requests_mock):
    requests_mock.get(f"{PRODUCT_URL}/1", exc=requests.exceptions.ConnectionError)

    response = client.post("/orders", json=[{"product_id": 1, "quantity": 1}])

    assert response.status_code == 503
    assert "Cannot connect to Product service" in response.json()["detail"]
    assert main.orders == {}


def test_create_order_product_service_timeout(requests_mock):
    requests_mock.get(f"{PRODUCT_URL}/1", exc=requests.exceptions.ConnectTimeout)

    response = client.post("/orders", json=[{"product_id": 1, "quantity": 1}])

    assert response.status_code == 503


def test_create_order_product_service_returns_500(requests_mock):
    requests_mock.get(f"{PRODUCT_URL}/1", status_code=500)

    response = client.post("/orders", json=[{"product_id": 1, "quantity": 1}])

    assert response.status_code == 503
    assert "Product service is unavailable" in response.json()["detail"]


def test_create_order_one_missing_product_rejects_whole_order(requests_mock):
    requests_mock.get(f"{PRODUCT_URL}/1", json={"id": 1, "name": "Laptop", "price": 1200.50})
    requests_mock.get(f"{PRODUCT_URL}/99", status_code=404)

    response = client.post(
        "/orders",
        json=[{"product_id": 1, "quantity": 1}, {"product_id": 99, "quantity": 1}],
    )

    assert response.status_code == 400
    assert main.orders == {}


def test_create_order_invalid_payload_returns_422():
    response = client.post("/orders", json=[{"product_id": "abc", "quantity": 1}])

    assert response.status_code == 422


# ---------- GET /orders, GET /orders/{id} ----------

def test_get_all_orders_empty():
    response = client.get("/orders")

    assert response.status_code == 200
    assert response.json() == []


def test_get_all_orders_returns_created_order(requests_mock):
    requests_mock.get(f"{PRODUCT_URL}/1", json={"id": 1, "name": "Laptop", "price": 100.0})
    client.post("/orders", json=[{"product_id": 1, "quantity": 3}])

    response = client.get("/orders")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["total_amount"] == 300.0


def test_get_order_by_id_success(requests_mock):
    requests_mock.get(f"{PRODUCT_URL}/1", json={"id": 1, "name": "Laptop", "price": 100.0})
    client.post("/orders", json=[{"product_id": 1, "quantity": 2}])

    response = client.get("/orders/1")

    assert response.status_code == 200
    assert response.json()["total_amount"] == 200.0


def test_get_order_by_id_not_found():
    response = client.get("/orders/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Order not found"
