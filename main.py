import httpx
from fastapi import FastAPI, HTTPException, status
from typing import List
from pydantic import BaseModel
import sqlalchemy
from database import database, orders, order_items

# --- Моделі Pydantic (контракт API) ---
class OrderItemPayload(BaseModel):
    product_id: int
    quantity: int

class OrderItemResponse(OrderItemPayload):
    id: int
    order_id: int

class OrderResponse(BaseModel):
    id: int
    total_amount: float
    items: List[OrderItemResponse]

app = FastAPI()

@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

PRODUCT_SERVICE_URL = "http://localhost:8080/products"

@app.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(order_items_payload: List[OrderItemPayload]):
    total_amount = 0.0

    # Використовуємо асинхронний клієнт httpx замість requests
    async with httpx.AsyncClient() as client:
        for item in order_items_payload:
            try:
                response = await client.get(f"{PRODUCT_SERVICE_URL}/{item.product_id}")
                if response.status_code == 200:
                    product_data = response.json()
                    total_amount += product_data['price'] * item.quantity
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Product with id {item.product_id} not found."
                    )
            except httpx.RequestError:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Cannot connect to Product service."
                )

    query = orders.insert().values(total_amount=total_amount)
    last_record_id = await database.execute(query)

    items_to_insert = [
        {
            "order_id": last_record_id,
            "product_id": item.product_id,
            "quantity": item.quantity
        }
        for item in order_items_payload
    ]

    query = order_items.insert().values(items_to_insert)
    await database.execute(query)

    # Отримуємо щойно створені items для відповіді
    query = order_items.select().where(order_items.c.order_id == last_record_id)
    created_items = await database.fetch_all(query)

    return {
        "id": last_record_id,
        "total_amount": total_amount,
        "items": created_items
    }

@app.get("/orders", response_model=List[OrderResponse])
async def get_all_orders():
    query = orders.select()
    all_orders = await database.fetch_all(query)

    results = []  # Виправлено синтаксичну помилку
    for order in all_orders:
        query = order_items.select().where(order_items.c.order_id == order.id)
        items = await database.fetch_all(query)
        results.append({
            "id": order.id,
            "total_amount": order.total_amount,
            "items": items
        })
    return results