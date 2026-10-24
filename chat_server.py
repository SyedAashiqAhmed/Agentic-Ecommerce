import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass, field

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
room_state: dict[str, "ChatRoom"] = {}
client = OllamaClient()


@dataclass
class ChatRoom:
    buyer_context: dict
    supplier_context: dict
    approved: bool = False
    agent_chat_enabled: bool = True
    history: list[dict] = field(default_factory=list)


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


def agent_reply(room: ChatRoom, message: str, sender_role: str) -> tuple[str, dict | None]:
    identity = room.buyer_context if sender_role == "seller-human" else room.supplier_context
    other = room.supplier_context if sender_role == "seller-human" else room.buyer_context
    role_name = "Buyer Agent" if sender_role == "seller-human" else "Supplier Agent"
    history = "\n".join(
        f"{item['sender_role']}: {item['message']}" for item in room.history[-12:]
    )
    fallback = "I cannot reach the local model right now. The conversation remains open, but no commercial term is authorized."
    try:
        result = client.generate_json(
            (
                f"You are {role_name}. Return only JSON with fields reply and proposal. "
                "proposal must be null for ordinary discussion, or an object with only explicitly proposed "
                "unit_price_inr, quantity, delivery_days, and warranty. "
                f"Your private identity and objectives are: {json.dumps(identity)}. "
                f"The other party's shared context is: {json.dumps(other)}. "
                "Use the conversation history, answer the latest message naturally, and do not pretend "
                "that a proposal is accepted. Never authorize payment or bypass policy."
            ),
            (
                f"Conversation history:\n{history}\nLatest message from {sender_role}: {message}"
            ),
        )
        reply = result.get("reply")
        proposal = result.get("proposal")
        return (
            reply.strip() if isinstance(reply, str) and reply.strip() else fallback,
            proposal if isinstance(proposal, dict) else None,
        )
    except (OllamaError, ValueError, TypeError):
        return fallback, None


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "model": OLLAMA_MODEL}


@app.post("/rooms/{room_id}")
async def create_room(room_id: str, payload: dict) -> dict:
    room_state[room_id] = ChatRoom(
        buyer_context=dict(payload.get("buyer_context", {})),
        supplier_context=dict(payload.get("supplier_context", {})),
        agent_chat_enabled=payload.get("agent_chat_enabled", True),
    )
    return {"room_id": room_id, "approved": False}


@app.post("/rooms/{room_id}/permission")
async def set_room_permission(room_id: str, payload: dict) -> dict:
    room = room_state.get(room_id)
    if room is None:
        return {"approved": False, "error": "room_not_found"}
    room.approved = payload.get("approved") is True
    return {"room_id": room_id, "approved": room.approved}


@app.websocket("/ws/{room_id}/{role}")
async def negotiation_socket(websocket: WebSocket, room_id: str, role: str) -> None:
    await websocket.accept()
    room = room_state.get(room_id)
    is_human_direct_chat = role in {"seller-human", "buyer-human"}
    if room is None or (is_human_direct_chat and not room.approved) or (
        not is_human_direct_chat and not room.agent_chat_enabled
    ):
        await websocket.send_json({"type": "error", "message": "Buyer permission is required before this chat opens."})
        await websocket.close(code=1008)
        return
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
            room.history.append({
                "sender_id": role,
                "sender_role": role,
                "message": message,
            })
            if role in {"seller-human", "buyer-human", "seller-user", "buyer-user"}:
                await asyncio.sleep(0)
                reply_role = "buyer-agent" if role in {"seller-human", "seller-user"} else "supplier-agent"
                try:
                    reply, proposal = await asyncio.wait_for(
                        asyncio.to_thread(agent_reply, room, message, role),
                        timeout=client.timeout_seconds + 5,
                    )
                except asyncio.TimeoutError:
                    reply, proposal = (
                        "The local Buyer/Supplier Agent timed out. No commercial term was accepted.",
                        None,
                    )
                room.history.append({
                    "sender_id": reply_role,
                    "sender_role": reply_role,
                    "message": reply,
                })
                await broadcast(room_id, {
                    "type": "message",
                    "sender_id": reply_role,
                    "sender_role": reply_role,
                    "message": reply,
                    "round_number": payload.get("round_number", 1),
                    "proposal": proposal,
                })
    except WebSocketDisconnect:
        rooms[room_id].discard(websocket)


if __name__ == "__main__":
    uvicorn.run("chat_server:app", host="127.0.0.1", port=8765, reload=False)
