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

async def handle_connection(ws, path, client_ip):
    logger.info(f"New connection on path {path} from {client_ip}")
    
    # Try to receive a handshake message (timeout after 2 seconds)
    try:
        first = await asyncio.wait_for(ws.receive(), timeout=2.0)
        if first.type != WSMsgType.TEXT:
            raise ValueError("Expected text handshake")
        logger.info(f"Received handshake: {first.data}")
        obj = json.loads(first.data)
        if obj.get("sender") is True:
            image_senders.add(ws)
            logger.info(f"Sender joined: {client_ip}")
            await handle_image_sender(ws, client_ip)
            return
    except (asyncio.TimeoutError, ValueError, json.JSONDecodeError) as e:
        # No valid handshake received; treat as a client
        logger.info(f"No sender handshake from {client_ip} on {path}, treating as client: {e}")
    
    # Add to connected clients
    connected_clients.add(ws)
    logger.info(f"Client joined: {client_ip} on {path}")
    try:
        async for msg in ws:
            logger.info(f"Received message from client {client_ip} on {path}: {msg.data}")
            # Optionally handle messages from clients (e.g., pings)
    except Exception as e:
        logger.error(f"Error with client {client_ip} on {path}: {e}")
    finally:
        connected_clients.remove(ws)
        logger.info(f"Client left: {client_ip} on {path}")

async def handle_image_sender(ws, client_ip):
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    logger.info(f"Broadcast JSON from {client_ip}: {json.dumps(data)}")
                    if connected_clients:
                        logger.info(f"Broadcasting to {len(connected_clients)} clients")
                        await asyncio.gather(*(c.send_json(data) for c in connected_clients), return_exceptions=True)
                    continue
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON from sender {client_ip}: {msg.data}")
                    pass
            elif msg.type == WSMsgType.BINARY:
                logger.info(f"Broadcast binary from {client_ip}: {len(msg.data)} bytes")
                if connected_clients:
                    logger.info(f"Broadcasting to {len(connected_clients)} clients")
                    await asyncio.gather(*(c.send_bytes(msg.data) for c in connected_clients), return_exceptions=True)
    except Exception as e:
        logger.error(f"Error broadcasting from {client_ip}: {e}")
    finally:
        image_senders.remove(ws)
        logger.info(f"Sender left: {client_ip}")

async def main_handler(request):
    """Handle HTTP and WebSocket requests."""
    client_ip = request.remote or "unknown"
    logger.info(f"Received {request.method} request on {request.path} from {client_ip}")
    
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
        await handle_connection(ws, request.path, client_ip)
        return ws
    
    # Reject unsupported methods
    logger.warning(f"Unsupported method {request.method} from {client_ip}")
    return web.Response(text="Method Not Allowed", status=405)

async def main():
    logger.info(f"Starting server on {WS_HOST}:{WS_PORT}")
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", main_handler)
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
