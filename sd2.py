import asyncio
import websockets
import json
import os
from websockets.http11 import Response
from http import HTTPStatus
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

WS_HOST = "0.0.0.0"
WS_PORT = int(os.environ.get("PORT", "8000"))  # Use Render.com's PORT or safe default

connected_clients = set()
image_senders = set()

async def handle_connection(ws, path):
    try:
        logger.info(f"New connection attempt from {ws.remote_address} on path {path}")
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

async def custom_process_request(path, headers):
    """Handle non-WebSocket requests, such as HEAD and GET requests from Render.com."""
    method = headers.get("method", "UNKNOWN")
    logger.info(f"Received {method} request on path {path} with headers: {dict(headers)}")
    
    # Handle all non-WebSocket requests
    if headers.get("upgrade", "").lower() != "websocket":
        if method in ["HEAD", "GET"]:
            logger.info(f"Responding to {method} request with HTTP 200")
            return Response(
                status=HTTPStatus.OK,
                headers={"Content-Length": "0" if method == "HEAD" else str(len(b"WebSocket server is running"))},
                body=None if method == "HEAD" else b"WebSocket server is running"
            )
        logger.warning(f"Unsupported method {method}, returning HTTP 405")
        return Response(
            status=HTTPStatus.METHOD_NOT_ALLOWED,
            headers={"Content-Type": "text/plain"},
            body=b"Method Not Allowed"
        )
    
    logger.info("Processing WebSocket handshake")
    return None  # Proceed with WebSocket handshake

async def main():
    logger.info(f"Starting relay server on ws://{WS_HOST}:{WS_PORT}")
    try:
        server = await websockets.serve(
            handle_connection,
            WS_HOST,
            WS_PORT,
            process_request=custom_process_request,
            ping_interval=None,  # Disable pings to simplify
            ping_timeout=None
        )
        logger.info("Server started successfully")
        await asyncio.Future()  # Run forever
    except Exception as e:
        logger.error(f"Server startup failed: {e}")
        raise

if __name__ == "__main__":
    logger.info("Initializing WebSocket server")
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Main loop error: {e}")
        raise
