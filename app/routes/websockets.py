# app/routes/websockets.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.websockets.manager import manager
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive by waiting for messages
            data = await websocket.receive_text()
            # Echo back for testing (optional)
            await manager.send_personal_message(f"Message received: {data}", websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("WebSocket client disconnected")