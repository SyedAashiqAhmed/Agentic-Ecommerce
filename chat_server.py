import asyncio
import json
from collections import defaultdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import OLLAMA_HOST, OLLAMA_MODEL
from llm.ollama_client import OllamaClient, OllamaError

app = FastAPI(title="CommerceOS Negotiation Socket")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

rooms: dict[str, set[WebSocket]] = defaultdict(set)
client = OllamaClient()


async def broadcast(room_id: str, payload: dict) -> None:
    disconnected: list[WebSocket] = []
    message = json.dumps(payload, ensure_ascii=False)
    for socket in rooms[room_id]:
        try:
            await socket.send_text(message)
        except Exception:
            disconnected.append(socket)
    for socket in disconnected:
        rooms[room_id].discard(socket)


def buyer_reply(message: str, context: dict) -> str:
    fallback = (
        f"I received your message: '{message}'. I can discuss price, delivery, and warranty, "
        "but I cannot relax mandatory buyer constraints or authorize payment."
    )
    try:
        result = client.generate_json(
            "You are the Buyer Agent in a procurement negotiation. Return only JSON with a string field named reply. "
            "Do not authorize payment, do not relax hard constraints, and be concise.",
            (
                f"Current offer: {context.get('unit_price_inr')} INR/unit; "
                f"delivery: {context.get('delivery_days')} days; "
                f"buyer budget: {context.get('budget_inr')} INR. "
                f"Seller message: {message}"
            ),
        )
        reply = result.get("reply")
        return reply.strip() if isinstance(reply, str) and reply.strip() else fallback
    except (OllamaError, ValueError, TypeError):
        return fallback


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "model": OLLAMA_MODEL, "ollama": client.is_available()}


@app.websocket("/ws/{room_id}/{role}")
async def negotiation_socket(websocket: WebSocket, room_id: str, role: str) -> None:
    await websocket.accept()
    rooms[room_id].add(websocket)
    await websocket.send_json({"type": "connected", "room_id": room_id, "role": role})
    try:
        while True:
            payload = await websocket.receive_json()
            if payload.get("type") != "message":
                continue
            message = str(payload.get("message", "")).strip()
            if not message:
                continue
            await broadcast(room_id, {
                "type": "message",
                "sender_id": role,
                "sender_role": role,
                "message": message,
                "round_number": payload.get("round_number", 1),
            })
            if role == "seller-human":
                await asyncio.sleep(0)
                reply = await asyncio.to_thread(buyer_reply, message, payload.get("context", {}))
                await broadcast(room_id, {
                    "type": "message",
                    "sender_id": "buyer-agent",
                    "sender_role": "buyer-agent",
                    "message": reply,
                    "round_number": payload.get("round_number", 1),
                })
    except WebSocketDisconnect:
        rooms[room_id].discard(websocket)


if __name__ == "__main__":
    uvicorn.run("chat_server:app", host="127.0.0.1", port=8765, reload=False)
