from __future__ import annotations

from typing import Any
from uuid import uuid4

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agents.buyer_agent import BuyerAgent
from agents.seller_agent import SellerAgent
from business.negotiation import NegotiationEngine
from data import demo_sellers
from llm.ollama_client import OllamaClient


class PurchaseInput(BaseModel):
    text: str = Field(min_length=3)


app = FastAPI(title="CommerceOS API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OllamaClient()
transactions: dict[str, dict[str, Any]] = {}


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "model": client.model, "ollama": client.is_available()}


@app.post("/api/purchases")
def create_purchase(payload: PurchaseInput) -> dict[str, Any]:
    buyer = BuyerAgent(llm=client if client.is_available() else None)
    request = buyer.parse_request(payload.text)
    sellers = [SellerAgent(profile, llm=client if client.is_available() else None) for profile in demo_sellers()]
    products = {product.product_id: product for seller in sellers for product in seller.profile.products}
    result = NegotiationEngine(buyer).run(request, sellers, products)
    if result.selected_offer:
        result.chat_room_id = result.selected_offer.offer_id
        result.direct_chat_room_id = f"{result.chat_room_id}-direct"
        profile = next(profile for profile in demo_sellers() if profile.seller_id == result.selected_offer.seller_id)
        chat_payload = {
            "buyer_context": {"role": "buyer procurement agent", "request": request.model_dump()},
            "supplier_context": {
                "role": "supplier agent",
                "supplier_id": profile.seller_id,
                "product": products[result.selected_offer.product_id].model_dump(),
                "private_policies": profile.policies[result.selected_offer.product_id].model_dump(),
            },
            "agent_chat_enabled": True,
        }
        try:
            requests.post(
                f"http://127.0.0.1:8765/rooms/{result.chat_room_id}",
                json=chat_payload,
                timeout=8,
            ).raise_for_status()
            requests.post(
                f"http://127.0.0.1:8765/rooms/{result.direct_chat_room_id}",
                json={**chat_payload, "agent_chat_enabled": False},
                timeout=8,
            ).raise_for_status()
        except requests.RequestException:
            pass
    transaction_id = str(uuid4())
    record = {
        "id": transaction_id,
        "request": request.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
        "buyer_source": buyer.last_parse_source,
        "buyer_error": buyer.last_error,
    }
    transactions[transaction_id] = record
    return record


@app.get("/api/purchases")
def list_purchases() -> list[dict[str, Any]]:
    return list(transactions.values())


@app.get("/api/purchases/{transaction_id}")
def get_purchase(transaction_id: str) -> dict[str, Any]:
    record = transactions.get(transaction_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return record


@app.post("/api/purchases/{transaction_id}/chat-request")
def request_direct_chat(transaction_id: str) -> dict[str, Any]:
    record = transactions.get(transaction_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    result = record["result"]
    offer = result.get("selected_offer")
    if not offer:
        raise HTTPException(status_code=409, detail="No selected offer")
    result["supplier_chat_status"] = "pending"
    result["supplier_chat_request"] = (
        "The Supplier Agent requests direct contact to clarify delivery, warranty, "
        "or commercial terms before final approval."
    )
    result["chat_room_id"] = offer["offer_id"]
    result["direct_chat_room_id"] = f"{offer['offer_id']}-direct"
    return record


@app.post("/api/purchases/{transaction_id}/chat-permission")
def set_chat_permission(transaction_id: str, approved: bool) -> dict[str, Any]:
    record = transactions.get(transaction_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    result = record["result"]
    if not result.get("direct_chat_room_id"):
        raise HTTPException(status_code=409, detail="No direct-chat request exists")
    result["supplier_chat_status"] = "approved" if approved else "rejected"
    try:
        requests.post(
            f"http://127.0.0.1:8765/rooms/{result['direct_chat_room_id']}/permission",
            json={"approved": approved},
            timeout=8,
        ).raise_for_status()
    except requests.RequestException:
        pass
    return record


@app.post("/api/purchases/{transaction_id}/seller-approval")
def seller_approval(transaction_id: str, approved: bool) -> dict[str, Any]:
    record = transactions.get(transaction_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    offer = record["result"].get("selected_offer")
    if not offer:
        raise HTTPException(status_code=409, detail="No selected offer")
    offer["seller_approval_status"] = "approved" if approved else "rejected"
    offer["status"] = "proposed" if approved else "rejected"
    return record
