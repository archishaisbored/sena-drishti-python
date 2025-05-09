import asyncio
import json
import os
import logging
from aiohttp import web, WSMsgType

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
        first = await ws.receive()
        if first.type != WSMsgType.TEXT:
            raise ValueError("Expected text handshake")
        logger.info(f"Received handshake: {first.data}")
        obj = json.loads(first.data)
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
            async for msg in ws:
                pass  # Keep connection open for clients
        finally:
            connected_clients.remove(ws)
            logger.info(f"Client left: {ws.remote_address}")
    except Exception as e:
        logger.error(f"Connection error: {e}")
        if not ws.closed:
            await ws.close(code=1011, message=str(e))

async def handle_image_sender(ws):
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    logger.info(f"Broadcast JSON: {json.dumps(data)}")
                    if connected_clients:
                        await asyncio.gather(*(c.send_json(data) for c in connected_clients), return_exceptions=True)
                    continue
                except json.JSONDecodeError:
                    pass
            elif msg.type == WSMsgType.BINARY:
                logger.info(f"Broadcast binary: {len(msg.data)} bytes")
                if connected_clients:
                    await asyncio.gather(*(c.send_bytes(msg.data) for c in connected_clients), return_exceptions=True)
    finally:
        image_senders.remove(ws)
        logger.info(f"Sender left: {ws.remote_address}")

async def main_handler(request):
    """Handle HTTP and WebSocket requests."""
    logger.info(f"Received {request.method} request on {request.path}")
    
    # Handle HEAD and GET for health checks
    if request.method in ["HEAD", "GET"] and request.headers.get("upgrade", "").lower() != "websocket":
        return web.Response(
            text="WebSocket server is running" if request.method == "GET" else "",
            status=200,
            headers={"Content-Length": "0" if request.method == "HEAD" else "25"}
        )
    
    # Handle WebSocket connections
    if request.headers.get("upgrade", "").lower() == "websocket":
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await handle_connection(ws, request.path)
        return ws
    
    # Reject unsupported methods
    logger.warning(f"Unsupported method {request.method}")
    return web.Response(text="Method Not Allowed", status=405)

async def main():
    logger.info(f"Starting server on {WS_HOST}:{WS_PORT}")
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", main_handler)  # Single route for all methods
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
