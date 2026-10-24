import json

import websocket


class ChatSocketError(RuntimeError):
    pass


def send_seller_message(
    room_id: str,
    message: str,
    round_number: int,
    context: dict,
    url: str = "ws://127.0.0.1:8765",
) -> list[dict]:
    try:
        socket = websocket.create_connection(
            f"{url}/ws/{room_id}/seller-human",
            timeout=45,
        )
        socket.recv()
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
