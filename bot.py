import os
import asyncio
import re
import logging
import unicodedata
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.client.session.aiohttp import AiohttpSession
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
MEDIA_CHANNEL_ID = int(os.getenv("MEDIA_CHANNEL_ID")) 
SOURCE_CHANNEL_ID = int(os.getenv("SOURCE_CHANNEL_ID"))

session = AiohttpSession()
bot = Bot(token=BOT_TOKEN, session=session, default_parse_mode=ParseMode.HTML)
dp = Dispatcher()

client = AsyncIOMotorClient(MONGO_URI)
db = client["CheatBotDB"]
collection = db["cheats"]

sem = asyncio.Semaphore(1)

# --- UTILS ---
def normalize_text(text):
    if not text: return ""
    return "".join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c)).lower()

def clean_name_strict(text):
    """Purani ID aur kachra saaf karke sirf character name nikalne ke liye"""
    if not text: return "Unknown"
    # 1. Catch lines with or without 🆔, starting with numbers
    match = re.search(r"(?:🆔|🆔️)?\s*\d+\s*[:\s-]+([^\[\n\r🔞💍]+)", text)
    if match:
        name = match.group(1).strip()
    else:
        # Agar ID line nahi hai toh pehli valid line uthao
        lines = [l.strip() for l in text.split('\n') if l.strip() and "OwO" not in l]
        name = lines[0] if lines else "Unknown"
    
    # 2. FINAL CLEAN: Kisi bhi haal mein agar aage numbers bache hain toh udao
    name = re.sub(r"^\d+[:\s]*", "", name).strip()
    return name

def format_to_new_fashion(text, assigned_id):
    """Backup channel ke liye caption, jisme naya ALLOTTED ID hoga, purana nahi."""
    if not text: return ""
    text = text.replace("<b>", "").replace("</b>", "")
    raw_lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    # Faltu words skip karne ke liye
    forbidden = ["OwO", "➼", "Added by", "Updated by", "User:", "@", "🍬", "𝑃𝑟𝑒𝑚𝑖𝑒𝑟", "🆔"]
    
    anime, name, rarity = "Unknown", "Unknown", "Unknown"
    card_type = ""
    
    # Pehle strict name nikal lo
    name = clean_name_strict(text)

    for line in raw_lines:
        # Agar line me kachra hai, skip karo
        if any(x in line for x in forbidden):
            continue
        # Purani ID wali line skip karo (jo number se shuru hoti hai)
        if re.match(r"^\d+[:\s]", line):
            continue
            
        if "RARITY" in line.upper() or "𝙍𝘼𝙍𝙄𝙏𝙔" in line:
            match = re.search(r"(?:RARITY|𝙍𝘼𝙍𝙄𝙏𝙔)\s*[:\s]*([^\)\n\r]+)", line, re.IGNORECASE)
            rarity = match.group(1).strip() if match else line
        elif anime == "Unknown" and name not in line and len(line) > 2:
            anime = line
        else:
            # Type / Edition nikalne ke liye
            if len(line) > 1 and line != anime and line != rarity:
                card_type = line

    # Yahan humne naya allotted ID add kar diya hai
    caption = (
        f"Name: {name}\n"
        f"Artist/Anime: {anime}\n"
        f"Rarity: {rarity}\n"
        f"ID: {assigned_id}"
    )
    
    if card_type:
        caption += f"\nType: {card_type}"
        
    return caption

# --- CORE SAVER ---
async def process_and_save(message: types.Message):
    async with sem:
        try:
            media = message.photo[-1] if message.photo else message.video
            if not media: return
            
            unique_id = media.file_unique_id
            full_caption = message.caption or ""
            
            # Serial ID Calculation
            last = await collection.find_one({"serial_id": {"$exists": True}}, sort=[("serial_id", -1)])
            assigned_id = (int(last["serial_id"]) + 1) if last else 1
            
            # Updated Formatting
            char_name = clean_name_strict(full_caption)
            # Yahan assigned_id pass kiya backup caption ke liye
            new_clean_cap = format_to_new_fashion(full_caption, assigned_id)

            existing = await collection.find_one({"file_unique_id": unique_id})
            if existing:
                e_name = existing.get('char_name') or "Unknown"
                # Reply mein sirf Name aayega
                return await message.reply(f"/take {e_name}")

            # Backup channel mein ID ke sath update hoga
            backup = await bot.copy_message(
                chat_id=MEDIA_CHANNEL_ID, 
                from_chat_id=message.chat.id, 
                message_id=message.message_id,
                caption=new_clean_cap
            )
            
            await collection.update_one({"file_unique_id": unique_id}, {"$set": {
                "serial_id": assigned_id, "msg_id": backup.message_id, "char_name": char_name,
                "full_info": full_caption, "search_field": normalize_text(full_caption)
            }}, upsert=True)
            
            # Chat ka reply abhi bhi clean rahega
            await message.reply(f"/take {char_name}")
            await asyncio.sleep(4.5)

        except Exception as e:
            logging.error(f"Save Error: {e}")

# --- COMMANDS ---

@dp.message(Command("check"))
async def cmd_check(message: types.Message):
    args = message.text.split()
    if len(args) < 2: return
    try:
        res = await collection.find_one({"serial_id": int(args[1])})
        if res:
            await bot.copy_message(chat_id=message.chat.id, from_chat_id=MEDIA_CHANNEL_ID, message_id=res["msg_id"])
        else:
            await message.reply(f"❌ Not in that ID: {args[1]}")
    except: pass

@dp.message(Command("total"))
async def cmd_total(message: types.Message):
    count = await collection.count_documents({})
    await message.reply(f"📊 Total Database: {count}")

@dp.message(F.photo | F.video)
async def handle_media(message: types.Message):
    if message.chat.type == "private" or message.chat.id == SOURCE_CHANNEL_ID:
        await process_and_save(message)

# --- MAIN ---
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Allotted ID in Backup Engine Started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
