import asyncio
import websockets
import json
import os

WS_HOST = "0.0.0.0"
WS_PORT = int(os.environ.get("PORT", "8765"))

connected_clients = set()
image_senders     = set()

async def handle_connection(ws, path):
    try:
        first = await ws.recv()
        obj   = json.loads(first)
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

async def main():
    print(f"▶️ Relay listening on ws://{WS_HOST}:{WS_PORT}")
    await websockets.serve(handle_connection, WS_HOST, WS_PORT)
    await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
