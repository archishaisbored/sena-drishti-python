import asyncio
import websockets
import json
import os

# WebSocket server config
connected_clients = set()  # Clients that will receive the live feed
image_senders = set()      # Devices sending images (e.g., sd2_sender.py)
WS_HOST = "0.0.0.0"
WS_PORT = int(os.environ.get("PORT", "8765"))  # Render provides PORT env var

async def handle_connection(ws, path):
    # Determine if the connection is from an image sender or a client
    try:
        first_message = await ws.recv()
        data = json.loads(first_message)
        # Assume sender connections send JSON first
        image_senders.add(ws)
        print(f"✅ Image sender connected: {ws.remote_address}")
        await handle_image_sender(ws, data)
    except json.JSONDecodeError:
        # If the first message isn't JSON, assume it's a client
        connected_clients.add(ws)
        print(f"✅ Client connected: {ws.remote_address}")
        await handle_client(ws)
    except Exception as e:
        print(f"⚠️ Connection error: {e}")

async def handle_image_sender(ws, initial_data):
    try:
        # Process the initial message
        await broadcast_data(initial_data)
        # Continue receiving messages
        async for message in ws:
            try:
                data = json.loads(message)
                await broadcast_data(data)
                # Expect binary image data next (if a threat was detected)
                binary_data = await ws.recv()
                await broadcast_binary(binary_data)
            except json.JSONDecodeError:
                # If message is not JSON, it might be binary data (e.g., after a mode change)
                await broadcast_binary(message)
            except Exception as e:
                print(f"⚠️ Sender error: {e}")
    finally:
        image_senders.remove(ws)
        print(f"🛑 Image sender disconnected: {ws.remote_address}")

async def handle_client(ws):
    try:
        await ws.wait_closed()
    finally:
        connected_clients.remove(ws)
        print(f"🛑 Client disconnected: {ws.remote_address}")

async def broadcast_data(data: dict):
    print("🔗 Broadcast JSON:", json.dumps(data, indent=2))
    if connected_clients:
        await asyncio.gather(
            *(c.send(json.dumps(data)) for c in connected_clients),
            return_exceptions=True
        )

async def broadcast_binary(binary_data):
    print("📷 Broadcast image binary")
    if connected_clients:
        await asyncio.gather(
            *(c.send(binary_data) for c in connected_clients),
            return_exceptions=True
        )

async def main():
    server = await websockets.serve(handle_connection, WS_HOST, WS_PORT)
    print(f"✅ WebSocket server listening on ws://{WS_HOST}:{WS_PORT}")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())
