"""
FastAPI Backend для Telegram Parser
С Server-Sent Events для прогресс-бара и неограниченным парсингом
"""

from fastapi import FastAPI, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat, User
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
import os
import json
import asyncio

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_ID = int(os.getenv("API_ID", "27844448"))
API_HASH = os.getenv("API_HASH", "e33633be38924a65b804cf1de0ed4da3")

clients: dict[str, TelegramClient] = {}
phone_codes: dict[str, str] = {}


async def get_client(phone: str) -> TelegramClient:
    """Получение или создание клиента"""
    if phone not in clients:
        clients[phone] = TelegramClient(StringSession(), API_ID, API_HASH)
    if not clients[phone].is_connected():
        await clients[phone].connect()
    return clients[phone]


@app.post("/send_code")
async def send_code(phone: str = Form(...)):
    """Отправка кода авторизации"""
    try:
        client = await get_client(phone)
        result = await client.send_code_request(phone)
        phone_codes[phone] = result.phone_code_hash
        return {"success": True, "message": "Код отправлен"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/verify_code")
async def verify_code(phone: str = Form(...), code: str = Form(...)):
    """Проверка кода авторизации"""
    try:
        client = await get_client(phone)
        phone_code_hash = phone_codes.get(phone)
        
        if not phone_code_hash:
            raise HTTPException(status_code=400, detail="Сначала запросите код")
        
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        return {"success": True, "message": "Авторизация успешна"}
        
    except SessionPasswordNeededError:
        return {"success": False, "need_2fa": True, "message": "Требуется 2FA пароль"}
    except PhoneCodeInvalidError:
        raise HTTPException(status_code=400, detail="Неверный код")
    except Exception as e:
        error_msg = str(e).lower()
        if "two-steps" in error_msg or "2fa" in error_msg or "password" in error_msg:
            return {"success": False, "need_2fa": True, "message": "Требуется 2FA пароль"}
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/verify_2fa")
async def verify_2fa(phone: str = Form(...), password: str = Form(...)):
    """Проверка 2FA пароля"""
    try:
        client = await get_client(phone)
        await client.sign_in(password=password)
        return {"success": True, "message": "Авторизация успешна"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка 2FA: {str(e)}")


@app.post("/get_chats")
async def get_chats(phone: str = Form(...)):
    """Получение списка чатов"""
    try:
        client = await get_client(phone)
        
        if not await client.is_user_authorized():
            raise HTTPException(status_code=401, detail="Не авторизован")
        
        dialogs = await client.get_dialogs()
        chats = []
        
        for dialog in dialogs:
            entity = dialog.entity
            chat_type = "personal"
            is_group = False
            
            if isinstance(entity, Channel):
                if entity.megagroup:
                    chat_type = "supergroup"
                    is_group = True
                else:
                    chat_type = "channel"
                    is_group = True
            elif isinstance(entity, Chat):
                chat_type = "group"
                is_group = True
            elif isinstance(entity, User):
                chat_type = "personal"
                is_group = False
            
            chats.append({
                "id": dialog.id,
                "name": dialog.name or "Без названия",
                "type": chat_type,
                "is_group": is_group
            })
        
        return {"success": True, "chats": chats}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/parse_stream")
async def parse_stream(phone: str, chat_id: int, method: str = "members"):
    """Парсинг с потоковой передачей прогресса (SSE)"""
    
    async def event_generator():
        try:
            client = await get_client(phone)
            
            if not await client.is_user_authorized():
                yield f"data: {json.dumps({'error': 'Не авторизован'})}\n\n"
                return
            
            users = []
            seen_ids = set()
            
            entity = await client.get_entity(chat_id)
            
            # Парсинг участников (БЕЗ ЛИМИТА)
            if method in ["members", "both"]:
                try:
                    yield f"data: {json.dumps({'status': 'parsing_members', 'message': 'Парсинг участников...'})}\n\n"
                    
                    count = 0
                    async for user in client.iter_participants(entity):
                        if user.id not in seen_ids:
                            seen_ids.add(user.id)
                            users.append({
                                "name": f"{user.first_name or ''} {user.last_name or ''}".strip() or "Нет имени",
                                "username": f"@{user.username}" if user.username else "",
                                "phone": user.phone or ""
                            })
                            count += 1
                            
                            # Отправляем прогресс каждые 50 пользователей
                            if count % 50 == 0:
                                yield f"data: {json.dumps({'status': 'progress', 'type': 'members', 'count': count})}\n\n"
                    
                    yield f"data: {json.dumps({'status': 'members_done', 'count': count})}\n\n"
                    
                except Exception as e:
                    yield f"data: {json.dumps({'error': f'Ошибка парсинга участников: {str(e)}'})}\n\n"
            
            # Парсинг по сообщениям (БЕЗ ЛИМИТА)
            if method in ["messages", "both"]:
                try:
                    yield f"data: {json.dumps({'status': 'parsing_messages', 'message': 'Парсинг сообщений...'})}\n\n"
                    
                    count = 0
                    processed = 0
                    
                    async for message in client.iter_messages(entity):
                        processed += 1
                        
                        if message.sender_id and message.sender_id not in seen_ids:
                            try:
                                sender = await message.get_sender()
                                if sender and isinstance(sender, User):
                                    seen_ids.add(sender.id)
                                    users.append({
                                        "name": f"{sender.first_name or ''} {sender.last_name or ''}".strip() or "Нет имени",
                                        "username": f"@{sender.username}" if sender.username else "",
                                        "phone": sender.phone or ""
                                    })
                                    count += 1
                            except Exception:
                                pass
                        
                        # Отправляем прогресс каждые 100 сообщений
                        if processed % 100 == 0:
                            yield f"data: {json.dumps({'status': 'progress', 'type': 'messages', 'processed': processed, 'found': count})}\n\n"
                    
                    yield f"data: {json.dumps({'status': 'messages_done', 'processed': processed, 'found': count})}\n\n"
                    
                except Exception as e:
                    yield f"data: {json.dumps({'error': f'Ошибка парсинга сообщений: {str(e)}'})}\n\n"
            
            # Отправляем финальный результат
            yield f"data: {json.dumps({'status': 'complete', 'users': users, 'total': len(users)})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/disconnect")
async def disconnect(phone: str = Form(...)):
    """Отключение сессии"""
    try:
        if phone in clients:
            await clients[phone].log_out()
            del clients[phone]
        if phone in phone_codes:
            del phone_codes[phone]
        return {"success": True, "message": "Отключено"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/")
async def root():
    """Проверка статуса API"""
    return {"status": "online", "service": "Telegram Parser API"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=int(os.getenv("PORT", 8000)),
        timeout_keep_alive=0  # Без таймаута для длинных операций
    )
