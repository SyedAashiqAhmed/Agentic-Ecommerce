import json

import requests
import websocket


class ChatSocketError(RuntimeError):
    pass


def check_chat_connection(
    room_id: str,
    role: str,
    url: str = "ws://127.0.0.1:8765",
) -> None:
    if role not in {"buyer-user", "seller-user", "buyer-human", "seller-human"}:
        raise ChatSocketError("Unsupported chat role")
    socket = None
    try:
        socket = websocket.create_connection(f"{url}/ws/{room_id}/{role}", timeout=10)
        connected = json.loads(socket.recv())
        if connected.get("type") == "error":
            raise ChatSocketError(connected["message"])
        if connected.get("type") != "connected":
            raise ChatSocketError("Chat server returned an invalid connection response.")
    except (OSError, websocket.WebSocketException, json.JSONDecodeError) as exc:
        raise ChatSocketError(f"Negotiation socket unavailable: {exc}") from exc
    finally:
        if socket is not None:
            socket.close()


def create_chat_room(
    room_id: str,
    buyer_context: dict,
    supplier_context: dict,
    agent_chat_enabled: bool = True,
    url: str = "http://127.0.0.1:8765",
) -> None:
    try:
        response = requests.post(
            f"{url}/rooms/{room_id}",
            json={
                "buyer_context": buyer_context,
                "supplier_context": supplier_context,
                "agent_chat_enabled": agent_chat_enabled,
            },
            timeout=5,
        )
        response.raise_for_status()
    except (OSError, requests.RequestException) as exc:
        raise ChatSocketError(f"Could not create negotiation room: {exc}") from exc


def set_chat_permission(room_id: str, approved: bool, url: str = "http://127.0.0.1:8765") -> None:
    try:
        response = requests.post(
            f"{url}/rooms/{room_id}/permission",
            json={"approved": approved},
            timeout=5,
        )
        response.raise_for_status()
    except (OSError, requests.RequestException) as exc:
        raise ChatSocketError(f"Could not update chat permission: {exc}") from exc


def send_seller_message(
    room_id: str,
    message: str,
    round_number: int,
    context: dict,
    url: str = "ws://127.0.0.1:8765",
    role: str = "seller-human",
) -> list[dict]:
    try:
        socket = websocket.create_connection(
            f"{url}/ws/{room_id}/{role}",
            timeout=45,
        )
        connected = json.loads(socket.recv())
        if connected.get("type") == "error":
            raise ChatSocketError(connected["message"])
        socket.send(json.dumps({
            "type": "message",
            "message": message,
            "round_number": round_number,
            "context": context,
        }))
        received: list[dict] = []
        for _ in range(2):
            received.append(json.loads(socket.recv()))
        socket.close()
        return [item for item in received if item.get("type") == "message"]
    except (OSError, websocket.WebSocketException, json.JSONDecodeError) as exc:
        raise ChatSocketError(f"Negotiation socket unavailable: {exc}") from exc


def exchange_agent_message(
    room_id: str,
    sender_role: str,
    message: str,
    round_number: int,
    url: str = "ws://127.0.0.1:8765",
) -> list[dict]:
    if sender_role not in {"buyer-agent", "supplier-agent"}:
        raise ChatSocketError("Only buyer-agent or supplier-agent may use agent exchange")
    try:
        socket = websocket.create_connection(f"{url}/ws/{room_id}/{sender_role}", timeout=60)
        connected = json.loads(socket.recv())
        if connected.get("type") == "error":
            raise ChatSocketError(connected["message"])
        socket.send(json.dumps({"type": "message", "message": message, "round_number": round_number}))
        received = [json.loads(socket.recv()), json.loads(socket.recv())]
        socket.close()
        return [item for item in received if item.get("type") == "message"]
    except (OSError, websocket.WebSocketException, json.JSONDecodeError) as exc:
        raise ChatSocketError(f"Negotiation socket unavailable: {exc}") from exc


def send_chat_message(
    room_id: str,
    role: str,
    message: str,
    round_number: int,
    context: dict | None = None,
    url: str = "ws://127.0.0.1:8765",
) -> list[dict]:
    if role not in {"buyer-user", "seller-user", "buyer-human", "seller-human"}:
        raise ChatSocketError("Unsupported chat role")
    try:
        socket = websocket.create_connection(f"{url}/ws/{room_id}/{role}", timeout=60)
        connected = json.loads(socket.recv())
        if connected.get("type") == "error":
            raise ChatSocketError(connected["message"])
        socket.send(json.dumps({
            "type": "message",
            "message": message,
            "round_number": round_number,
            "context": context or {},
        }))
        received = [json.loads(socket.recv()), json.loads(socket.recv())]
        socket.close()
        return [item for item in received if item.get("type") == "message"]
    except (OSError, websocket.WebSocketException, json.JSONDecodeError) as exc:
        raise ChatSocketError(f"Negotiation socket unavailable: {exc}") from exc
