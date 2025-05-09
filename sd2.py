import asyncio
import json
import os
import logging
from aiohttp import web
import websockets

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

WS_HOST = "0.0.0.0"
WS_PORT = int(os.environ.get("PORT", 8000))  # Use Render.com's PORT

connected_clients = set()
image_senders = set()

async def handle_connection(ws, path):
    try:
        logger.info(f"New connection from {ws.remote_address} on path {path}")
        first = await ws.recv()
        logger.info(f"Received handshake: {first}")
        obj = json.loads(first)
        if obj.get("sender") is True:
            image_senders.add(ws)
            logger.info(f"Sender joined: {ws.remote_address}")
            await handle_image_sender(ws)
        else:
            raise ValueError("Not a sender handshake")
    except json.JSONDecodeError:
        connected_clients.add(ws)
        logger.info(f"Client joined: {ws.remote_address}")
        try:
            await ws.wait_closed()
        finally:
            connected_clients.remove(ws)
            logger.info(f"Client left: {ws.remote_address}")
    except Exception as e:
        logger.error(f"Connection error: {e}")
        await ws.close(code=1011, reason=str(e))

async def handle_image_sender(ws):
    try:
        async for msg in ws:
            try:
                data = json.loads(msg)
                logger.info(f"Broadcast JSON: {json.dumps(data)}")
                if connected_clients:
                    await asyncio.gather(*(c.send(msg) for c in connected_clients), return_exceptions=True)
                continue
            except json.JSONDecodeError:
                pass
            logger.info(f"Broadcast binary: {len(msg)} bytes")
            if connected_clients:
                await asyncio.gather(*(c.send(msg) for c in connected_clients), return_exceptions=True)
    finally:
        image_senders.remove(ws)
        logger.info(f"Sender left: {ws.remote_address}")

async def http_handler(request):
    """Handle HTTP requests (GET, HEAD) for health checks and status."""
    logger.info(f"Received {request.method} request on {request.path}")
    if request.method in ["GET", "HEAD"]:
        if request.headers.get("upgrade", "").lower() == "websocket":
            return web.WebSocketResponse()  # Hand off to WebSocket
        return web.Response(
            text="WebSocket server is running" if request.method == "GET" else "",
            status=200,
            headers={"Content-Length": "0" if request.method == "HEAD" else "25"}
        )
    return web.Response(text="Method Not Allowed", status=405)

async def websocket_handler(request):
    """Handle WebSocket connections."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await handle_connection(ws, request.path)
    return ws

async def main():
    logger.info(f"Starting server on {WS_HOST}:{WS_PORT}")
    app = web.Application()
    app.router.add_route("GET", "/{path:.*}", websocket_handler)
    app.router.add_route("HEAD", "/{path:.*}", http_handler)
    app.router.add_route("GET", "/{path:.*}", http_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WS_HOST, WS_PORT)
    await site.start()
    logger.info("Server started successfully")
    await asyncio.Future()  # Run forever

if __name__ == "__main__":
    logger.info("Initializing server")
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Main loop error: {e}")
        raise
