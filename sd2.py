import asyncio
import websockets
import json
import os
from websockets.http11 import Response
from http import HTTPStatus

WS_HOST = "0.0.0.0"
WS_PORT = int(os.environ.get("PORT", "8000"))  # Use Render.com's PORT or a safe default

connected_clients = set()
image_senders = set()

async def handle_connection(ws, path):
    try:
        first = await ws.recv()
        obj = json.loads(first)
        if obj.get("sender") is True:
            image_senders.add(ws)
            print("✅ Sender joined:", ws.remote_address)
            await handle_image_sender(ws)
        else:
            raise ValueError("not a sender handshake")
    except json.JSONDecodeError:
        connected_clients.add(ws)
        print("✅ Client joined:", ws.remote_address)
        try:
            await ws.wait_closed()
        finally:
            connected_clients.remove(ws)
            print("🛑 Client left:", ws.remote_address)
    except Exception as e:
        print("⚠️ Connection error:", e)
        await ws.close(code=1011, reason=str(e))

async def handle_image_sender(ws):
    try:
        async for msg in ws:
            try:
                data = json.loads(msg)
                print("🔗 Broadcast JSON:", json.dumps(data))
                if connected_clients:
                    await asyncio.gather(*(c.send(msg) for c in connected_clients), return_exceptions=True)
                continue
            except json.JSONDecodeError:
                pass

            print("📷 Broadcast binary:", len(msg), "bytes")
            if connected_clients:
                await asyncio.gather(*(c.send(msg) for c in connected_clients), return_exceptions=True)
    finally:
        image_senders.remove(ws)
        print("🛑 Sender left:", ws.remote_address)

async def custom_process_request(path, headers):
    """Handle non-WebSocket requests, such as HEAD requests from Render.com."""
    if headers.get("Upgrade", "").lower() != "websocket":
        # Respond to HEAD or other non-WebSocket requests
        if headers.get("method") == "HEAD":
            print("📡 Responding to HEAD request")
            return Response(
                status=HTTPStimestatus=HTTPStatus.OK,
                headers={"Content-Length": "0"}
            )
        # Optionally handle other HTTP methods (e.g., GET for health checks)
        return Response(
            status=HTTPStatus.OK,
            headers={"Content-Type": "text/plain"},
            body=b"WebSocket server is running"
        )
    return None  # Proceed with WebSocket handshake for valid requests

async def main():
    print(f"▶️ Relay listening on ws://{WS_HOST}:{WS_PORT}")
    server = await websockets.serve(
        handle_connection,
        WS_HOST,
        WS_PORT,
        process_request=custom_process_request  # Add custom request handler
    )
    await asyncio.Future()  # Run forever

if __name__ == "__main__":
    asyncio.run(main())
