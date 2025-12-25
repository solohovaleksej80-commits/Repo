"""
FastAPI Backend для Telegram Parser
Деплой на Railway
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telethon import TelegramClient
from telethon.tl.types import User, Channel, Chat
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, ChatAdminRequiredError
import asyncio
import os
from typing import Optional, List

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Конфигурация
API_ID = int(os.getenv("API_ID", "27844448"))
API_HASH = os.getenv("API_HASH", "e33633be38924a65b804cf1de0ed4da3")

# Хранилище сессий
sessions = {}


# Модели данных
class PhoneRequest(BaseModel):
    phone: str

class CodeRequest(BaseModel):
    phone: str
    code: str

class ParseRequest(BaseModel):
    phone: str
    chat_id: int
    method: str  # "messages", "members", "both"


# Эндпоинты
@app.post("/send_code")
async def send_code(request: PhoneRequest):
    """Отправка кода авторизации"""
    try:
        client = TelegramClient(f'session_{request.phone}', API_ID, API_HASH)
        await client.connect()
        
        result = await client.send_code_request(request.phone)
        sessions[request.phone] = {
            'client': client,
            'phone_code_hash': result.phone_code_hash
        }
        
        return {"success": True, "message": "Код отправлен"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/verify_code")
async def verify_code(request: CodeRequest):
    """Проверка кода и авторизация"""
    try:
        if request.phone not in sessions:
            raise HTTPException(status_code=400, detail="Сначала запросите код")
        
        session = sessions[request.phone]
        client = session['client']
        
        await client.sign_in(
            request.phone,
            request.code,
            phone_code_hash=session['phone_code_hash']
        )
        
        return {"success": True, "message": "Авторизация успешна"}
    except PhoneCodeInvalidError:
        raise HTTPException(status_code=400, detail="Неверный код")
    except SessionPasswordNeededError:
        raise HTTPException(status_code=400, detail="Требуется 2FA пароль")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/get_chats")
async def get_chats(request: PhoneRequest):
    """Получение списка чатов"""
    try:
        if request.phone not in sessions:
            raise HTTPException(status_code=400, detail="Сначала авторизуйтесь")
        
        client = sessions[request.phone]['client']
        
        chats = []
        async for dialog in client.iter_dialogs():
            chat_type = "unknown"
            is_group = False
            
            if isinstance(dialog.entity, User):
                chat_type = "personal"
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
                'id': dialog.id,
                'name': dialog.name,
                'type': chat_type,
                'is_group': is_group
            })
        
        return {"success": True, "chats": chats}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/parse")
async def parse_chat(request: ParseRequest):
    """Парсинг пользователей из чата"""
    try:
        if request.phone not in sessions:
            raise HTTPException(status_code=400, detail="Сначала авторизуйтесь")
        
        client = sessions[request.phone]['client']
        
        # Получаем entity чата
        chat_entity = await client.get_entity(request.chat_id)
        
        users_data = []
        
        if request.method == "messages":
            users_data = await parse_by_messages(client, chat_entity)
        elif request.method == "members":
            users_data = await parse_by_members(client, chat_entity)
        elif request.method == "both":
            users_data = await parse_both(client, chat_entity)
        else:
            raise HTTPException(status_code=400, detail="Неверный метод парсинга")
        
        return {
            "success": True,
            "users": users_data,
            "total": len(users_data)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/disconnect")
async def disconnect(request: PhoneRequest):
    """Отключение сессии"""
    try:
        if request.phone in sessions:
            client = sessions[request.phone]['client']
            await client.disconnect()
            del sessions[request.phone]
        
        return {"success": True, "message": "Отключено"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Функции парсинга
async def parse_by_messages(client, chat_entity):
    """Парсинг по сообщениям"""
    users_dict = {}
    
    async for message in client.iter_messages(chat_entity, limit=None):
        if message.sender:
            user_id = message.sender_id
            
            if user_id not in users_dict:
                try:
                    sender = await message.get_sender()
                    if isinstance(sender, User):
                        full_name = f"{sender.first_name or ''} {sender.last_name or ''}".strip()
                        users_dict[user_id] = {
                            'name': full_name or 'Нет имени',
                            'username': f"@{sender.username}" if sender.username else '',
                            'phone': sender.phone or ''
                        }
                except:
                    pass
    
    return list(users_dict.values())


async def parse_by_members(client, chat_entity):
    """Парсинг по участникам"""
    users_list = []
    
    try:
        participants = await client.get_participants(chat_entity)
        
        for user in participants:
            if isinstance(user, User):
                full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
                users_list.append({
                    'name': full_name or 'Нет имени',
                    'username': f"@{user.username}" if user.username else '',
                    'phone': user.phone or ''
                })
        
        return users_list
    except ChatAdminRequiredError:
        raise HTTPException(status_code=403, detail="Нужны права администратора")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


async def parse_both(client, chat_entity):
    """Парсинг обоими методами"""
    users_dict = {}
    
    # Сначала участники
    try:
        participants = await client.get_participants(chat_entity)
        
        for user in participants:
            if isinstance(user, User):
                full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
                users_dict[user.id] = {
                    'name': full_name or 'Нет имени',
                    'username': f"@{user.username}" if user.username else '',
                    'phone': user.phone or ''
                }
    except:
        pass
    
    # Затем по сообщениям
    async for message in client.iter_messages(chat_entity, limit=None):
        if message.sender:
            user_id = message.sender_id
            
            if user_id not in users_dict:
                try:
                    sender = await message.get_sender()
                    if isinstance(sender, User):
                        full_name = f"{sender.first_name or ''} {sender.last_name or ''}".strip()
                        users_dict[user_id] = {
                            'name': full_name or 'Нет имени',
                            'username': f"@{sender.username}" if sender.username else '',
                            'phone': sender.phone or ''
                        }
                except:
                    pass
    
    return list(users_dict.values())


@app.get("/")
async def root():
    return {"status": "online", "service": "Telegram Parser API"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
