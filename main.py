"""
Telegram Parser Backend для Railway
"""

from fastapi import FastAPI, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from telethon import TelegramClient
from telethon.tl.types import User, Channel, Chat
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
import asyncio
import io
import csv
import json
import os

app = FastAPI(title="Telegram Parser API")

# CORS для фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Credentials (из твоих файлов)
API_ID = 27844448
API_HASH = 'e33633be38924a65b804cf1de0ed4da3'

# Хранилище сессий и данных
sessions = {}
parsed_data = {}

def get_session_path(phone: str) -> str:
    """Путь к файлу сессии"""
    safe_phone = phone.replace("+", "").replace("-", "")
    return f"sessions/session_{safe_phone}"

@app.get("/")
async def root():
    return {"status": "ok", "message": "Telegram Parser API"}

@app.post("/send_code")
async def send_code(phone: str = Form(...)):
    """Отправляет код подтверждения"""
    try:
        os.makedirs("sessions", exist_ok=True)
        session_path = get_session_path(phone)
        
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            sent = await client.send_code_request(phone)
            sessions[phone] = {
                "client": client,
                "phone_code_hash": sent.phone_code_hash
            }
            return {"status": "code_sent"}
        else:
            sessions[phone] = {"client": client}
            return {"status": "already_authorized"}
            
    except Exception as e:
        return {"error": str(e)}

@app.post("/confirm_code")
async def confirm_code(phone: str = Form(...), code: str = Form(...)):
    """Подтверждает код"""
    try:
        if phone not in sessions:
            raise HTTPException(400, "Сначала запросите код")
        
        session = sessions[phone]
        client = session["client"]
        
        if await client.is_user_authorized():
            return {"status": "success"}
        
        await client.sign_in(
            phone=phone,
            code=code,
            phone_code_hash=session.get("phone_code_hash")
        )
        return {"status": "success"}
        
    except PhoneCodeInvalidError:
        return {"error": "Неверный код"}
    except SessionPasswordNeededError:
        return {"error": "Требуется двухфакторная аутентификация", "need_2fa": True}
    except Exception as e:
        return {"error": str(e)}

@app.post("/confirm_2fa")
async def confirm_2fa(phone: str = Form(...), password: str = Form(...)):
    """Подтверждает 2FA пароль"""
    try:
        if phone not in sessions:
            raise HTTPException(400, "Сессия не найдена")
        
        client = sessions[phone]["client"]
        await client.sign_in(password=password)
        return {"status": "success"}
        
    except Exception as e:
        return {"error": str(e)}

@app.post("/get_chats")
async def get_chats(phone: str = Form(...)):
    """Получает список чатов пользователя"""
    try:
        if phone not in sessions:
            raise HTTPException(400, "Сначала авторизуйтесь")
        
        client = sessions[phone]["client"]
        chats = []
        
        async for dialog in client.iter_dialogs():
            chat_type = "unknown"
            is_group = False
            
            if isinstance(dialog.entity, User):
                chat_type = "user"
            elif isinstance(dialog.entity, Channel):
                if dialog.entity.megagroup:
                    chat_type = "supergroup"
                    is_group = True
                else:
                    chat_type = "channel"
                    is_group = True
            elif isinstance(dialog.entity, Chat):
                chat_type = "group"
                is_group = True
            
            chats.append({
                "id": dialog.id,
                "name": dialog.name,
                "type": chat_type,
                "is_group": is_group,
                "unread": dialog.unread_count
            })
        
        return {"chats": chats}
        
    except Exception as e:
        return {"error": str(e)}

@app.post("/parse_chat")
async def parse_chat(
    phone: str = Form(...),
    chat_id: int = Form(...),
    method: str = Form("messages"),  # messages, members, all
    limit: int = Form(None)
):
    """Парсит участников чата"""
    try:
        if phone not in sessions:
            raise HTTPException(400, "Сначала авторизуйтесь")
        
        client = sessions[phone]["client"]
        entity = await client.get_entity(chat_id)
        
        users = {}
        
        # Парсинг по сообщениям
        if method in ["messages", "all"]:
            async for message in client.iter_messages(entity, limit=limit):
                if message.sender and isinstance(message.sender, User):
                    user = message.sender
                    if user.id not in users and not user.bot:
                        users[user.id] = {
                            "id": user.id,
                            "first_name": user.first_name or "",
                            "last_name": user.last_name or "",
                            "username": f"@{user.username}" if user.username else "",
                            "phone": user.phone or "",
                            "source": "messages"
                        }
        
        # Парсинг по участникам
        if method in ["members", "all"]:
            try:
                async for user in client.iter_participants(entity):
                    if isinstance(user, User) and not user.bot:
                        if user.id not in users:
                            users[user.id] = {
                                "id": user.id,
                                "first_name": user.first_name or "",
                                "last_name": user.last_name or "",
                                "username": f"@{user.username}" if user.username else "",
                                "phone": user.phone or "",
                                "source": "members"
                            }
                        elif method == "all":
                            users[user.id]["source"] = "both"
            except Exception as e:
                if method == "members":
                    return {"error": f"Не удалось получить участников: {str(e)}"}
        
        result = list(users.values())
        parsed_data[phone] = result
        
        return {
            "status": "success",
            "count": len(result),
            "users": result[:50]  # Первые 50 для превью
        }
        
    except Exception as e:
        return {"error": str(e)}

@app.get("/download/{phone}")
async def download(phone: str, format: str = "txt"):
    """Скачивает результаты парсинга"""
    if phone not in parsed_data:
        raise HTTPException(404, "Данные не найдены")
    
    users = parsed_data[phone]
    
    if format == "txt":
        content = ""
        for user in users:
            line = f"{user['first_name']} {user['last_name']}".strip()
            if user['username']:
                line += f" | {user['username']}"
            line += f" | ID: {user['id']}"
            if user['phone']:
                line += f" | Tel: {user['phone']}"
            content += line + "\n"
        
        return StreamingResponse(
            io.BytesIO(content.encode('utf-8')),
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=users.txt"}
        )
    
    elif format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["id", "first_name", "last_name", "username", "phone", "source"])
        writer.writeheader()
        writer.writerows(users)
        
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=users.csv"}
        )
    
    elif format == "json":
        return StreamingResponse(
            io.BytesIO(json.dumps(users, ensure_ascii=False, indent=2).encode('utf-8')),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=users.json"}
        )

@app.post("/logout")
async def logout(phone: str = Form(...)):
    """Выход из аккаунта"""
    if phone in sessions:
        try:
            await sessions[phone]["client"].disconnect()
        except:
            pass
        del sessions[phone]
    if phone in parsed_data:
        del parsed_data[phone]
    return {"status": "logged_out"}
