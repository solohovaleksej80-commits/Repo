"""
Telegram Universal Parser
Универсальный парсер для Telegram с поддержкой двух методов сканирования
"""

from telethon import TelegramClient
from telethon.tl.types import User, Channel, Chat
from telethon.errors import ChatAdminRequiredError
import asyncio
import csv
from tqdm import tqdm

# API настройки
API_ID = 27844448
API_HASH = 'e33633be38924a65b804cf1de0ed4da3'


class UniversalTelegramParser:
    def __init__(self, api_id, api_hash):
        self.client = TelegramClient('session_name', api_id, api_hash)
        self.chats = []
        
    async def start(self, phone):
        await self.client.start(phone=phone)
        print("✅ Авторизация успешна!\n")
        
    async def get_all_chats(self):
        print("📋 Загружаю чаты...\n")
        self.chats = []
        
        async for dialog in self.client.iter_dialogs():
            chat_info = {
                'id': dialog.id,
                'name': dialog.name,
                'type': self._get_chat_type(dialog.entity),
                'entity': dialog.entity,
                'is_group': isinstance(dialog.entity, (Chat, Channel))
            }
            self.chats.append(chat_info)
            
        return self.chats
    
    def _get_chat_type(self, entity):
        if isinstance(entity, User):
            return "👤 Личный"
        elif isinstance(entity, Channel):
            return "📢 Канал" if not entity.megagroup else "👥 Супергруппа"
        elif isinstance(entity, Chat):
            return "👥 Группа"
        return "❓ Неизвестно"
    
    def display_chats(self):
        print("=" * 70)
        print("ДОСТУПНЫЕ ЧАТЫ:")
        print("=" * 70)
        
        for idx, chat in enumerate(self.chats, 1):
            print(f"{idx}. {chat['type']} {chat['name']}")
        
        print("=" * 70 + "\n")
    
    async def parse_by_messages(self, chat_entity):
        """Парсинг по сообщениям"""
        print("\n🔍 Метод 1: Парсинг по сообщениям")
        
        users_dict = {}
        
        try:
            # Подсчитываем общее количество сообщений
            total = await self.client.get_messages(chat_entity, limit=0)
            total_count = total.total if hasattr(total, 'total') else 10000
            
            with tqdm(total=total_count, desc="Парсинг сообщений", unit="msg") as pbar:
                async for message in self.client.iter_messages(chat_entity, limit=None):
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
                    
                    pbar.update(1)
            
            return list(users_dict.values())
            
        except Exception as e:
            print(f"❌ Ошибка парсинга по сообщениям: {e}")
            return []
    
    async def parse_by_members(self, chat_entity):
        """Парсинг по участникам"""
        print("\n🔍 Метод 2: Парсинг по участникам")
        
        users_list = []
        
        try:
            participants = await self.client.get_participants(chat_entity)
            
            with tqdm(total=len(participants), desc="Парсинг участников", unit="user") as pbar:
                for user in participants:
                    if isinstance(user, User):
                        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
                        users_list.append({
                            'name': full_name or 'Нет имени',
                            'username': f"@{user.username}" if user.username else '',
                            'phone': user.phone or ''
                        })
                    pbar.update(1)
            
            return users_list
            
        except ChatAdminRequiredError:
            print("⚠️  Нужны права администратора для получения списка участников")
            return []
        except Exception as e:
            print(f"❌ Ошибка парсинга по участникам: {e}")
            return []
    
    async def parse_both(self, chat_entity):
        """Парсинг обоими методами"""
        print("\n🔍 Метод 3: Парсинг обоими способами")
        
        users_dict = {}
        
        # Парсинг по участникам
        try:
            participants = await self.client.get_participants(chat_entity)
            
            with tqdm(total=len(participants), desc="[1/2] Участники", unit="user") as pbar:
                for user in participants:
                    if isinstance(user, User):
                        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
                        users_dict[user.id] = {
                            'name': full_name or 'Нет имени',
                            'username': f"@{user.username}" if user.username else '',
                            'phone': user.phone or ''
                        }
                    pbar.update(1)
        except:
            print("⚠️  Не удалось получить список участников, пропускаем...")
        
        # Парсинг по сообщениям
        try:
            total = await self.client.get_messages(chat_entity, limit=0)
            total_count = total.total if hasattr(total, 'total') else 10000
            
            with tqdm(total=total_count, desc="[2/2] Сообщения", unit="msg") as pbar:
                async for message in self.client.iter_messages(chat_entity, limit=None):
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
                    
                    pbar.update(1)
        except Exception as e:
            print(f"⚠️  Ошибка при парсинге сообщений: {e}")
        
        return list(users_dict.values())
    
    def save_csv(self, data, filename="telegram_users.csv"):
        """Сохранение в CSV"""
        try:
            with open(filename, 'w', encoding='utf-8-sig', newline='') as f:
                if data:
                    writer = csv.DictWriter(f, fieldnames=['name', 'username', 'phone'])
                    writer.writeheader()
                    writer.writerows(data)
            print(f"✅ CSV сохранён: {filename}")
        except Exception as e:
            print(f"❌ Ошибка сохранения CSV: {e}")
    
    def save_txt(self, data, filename="telegram_users.txt"):
        """Сохранение в TXT"""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("РЕЗУЛЬТАТЫ ПАРСИНГА TELEGRAM\n")
                f.write("=" * 80 + "\n\n")
                
                for idx, user in enumerate(data, 1):
                    f.write(f"#{idx}\n")
                    f.write(f"Имя: {user['name']}\n")
                    if user['username']:
                        f.write(f"Username: {user['username']}\n")
                    if user['phone']:
                        f.write(f"Телефон: {user['phone']}\n")
                    f.write("\n" + "-" * 80 + "\n\n")
            
            print(f"✅ TXT сохранён: {filename}")
        except Exception as e:
            print(f"❌ Ошибка сохранения TXT: {e}")
    
    async def close(self):
        await self.client.disconnect()


async def main():
    print("=" * 70)
    print(" " * 20 + "TELEGRAM UNIVERSAL PARSER")
    print("=" * 70 + "\n")
    
    phone_number = input("📱 Введите номер телефона (+79001234567): ")
    print()
    
    parser = UniversalTelegramParser(API_ID, API_HASH)
    
    try:
        await parser.start(phone_number)
        await parser.get_all_chats()
        
        while True:
            parser.display_chats()
            
            choice = input("Введите номер чата (или 'q' для выхода): ")
            
            if choice.lower() == 'q':
                break
            
            try:
                chat_index = int(choice) - 1
                
                if chat_index < 0 or chat_index >= len(parser.chats):
                    print("❌ Неверный номер!\n")
                    continue
                
                selected_chat = parser.chats[chat_index]
                print(f"\n📋 Выбран чат: {selected_chat['name']}")
                
                print("\n" + "=" * 70)
                print("ВЫБЕРИТЕ МЕТОД ПАРСИНГА:")
                print("=" * 70)
                print("1. По сообщениям (кто писал)")
                print("2. По участникам (все члены чата)")
                print("3. Оба метода (максимальный охват)")
                print("=" * 70)
                
                method = input("\nВыберите метод (1/2/3): ")
                
                users_data = []
                
                if method == '1':
                    users_data = await parser.parse_by_messages(selected_chat['entity'])
                elif method == '2':
                    users_data = await parser.parse_by_members(selected_chat['entity'])
                elif method == '3':
                    users_data = await parser.parse_both(selected_chat['entity'])
                else:
                    print("❌ Неверный выбор!\n")
                    continue
                
                if users_data:
                    print(f"\n✅ Найдено пользователей: {len(users_data)}")
                    
                    parser.save_csv(users_data, "telegram_users.csv")
                    parser.save_txt(users_data, "telegram_users.txt")
                    print()
                else:
                    print("⚠️  Пользователи не найдены\n")
                
                cont = input("Парсить другой чат? (y/n): ")
                if cont.lower() != 'y':
                    break
                
                print()
                    
            except ValueError:
                print("❌ Введите корректный номер!\n")
            except KeyboardInterrupt:
                print("\n\n⚠️  Прервано")
                break
        
    finally:
        await parser.close()
        print("\n👋 Работа завершена!")


if __name__ == '__main__':
    asyncio.run(main())
