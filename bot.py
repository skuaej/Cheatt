import os
import time
import asyncio
import re
import logging
import shutil
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.exceptions import TelegramRetryAfter, TelegramConflictError
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
OWNER_ID = int(os.getenv("OWNER_ID"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))
MEDIA_CHANNEL_ID = int(os.getenv("MEDIA_CHANNEL_ID")) 
SOURCE_CHANNEL_ID = int(os.getenv("SOURCE_CHANNEL_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

client = AsyncIOMotorClient(MONGO_URI)
db = client["CheatBotDB"]
collection = db["cheats"]

# Semaphore to prevent flooding (1 at a time for safety)
sem = asyncio.Semaphore(1)

# --- UTILS ---
def parse_caption(text):
    if not text: return None
    match = re.search(r"🆔️\d+:\s*([^\[\n\r]+)", text)
    if match:
        return match.group(1).strip()
    return text.split('\n')[0].strip()

# --- CORE SAVING LOGIC ---
async def process_and_save(message: types.Message):
    async with sem:
        media = message.photo[-1] if message.photo else message.video
        if not media: return
        
        unique_id = media.file_unique_id
        
        # Check DB first
        existing = await collection.find_one({"file_unique_id": unique_id})
        if existing:
            # Silent skip for duplicates to avoid spam
            return 

        clean_name = parse_caption(message.caption)
        if not clean_name: return

        try:
            # 1. Immortal Backup
            backup = await bot.copy_message(
                chat_id=MEDIA_CHANNEL_ID,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            
            # 2. MongoDB Save
            await collection.update_one(
                {"file_unique_id": unique_id},
                {"$set": {"msg_id": backup.message_id, "caption": clean_name}},
                upsert=True
            )
            
            # 3. Clean One-Tap Reply
            await message.reply(f"`/take {clean_name}`", parse_mode="Markdown")
            
            # KOYEB CONSOLE LOG (User will see this in dashboard)
            print(f"✅ SUCCESSFULLY SAVED: {clean_name}")
            
            # Anti-Ban delay
            await asyncio.sleep(2)

        except TelegramRetryAfter as e:
            print(f"⚠️ Flood limit hit! Sleeping for {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
            await process_and_save(message)
        except Exception as e:
            print(f"❌ Error processing {clean_name}: {e}")

# --- HANDLERS ---

@dp.message(F.photo | F.video)
async def handle_private(message: types.Message):
    await process_and_save(message)

@dp.channel_post(F.photo | F.video)
async def handle_channel(message: types.Message):
    # Ensure source channel matches
    if str(message.chat.id) == str(SOURCE_CHANNEL_ID):
        await process_and_save(message)

@dp.message(Command("search"))
async def search_media(message: types.Message):
    query = message.text.replace("/search", "").strip().lower()
    if not query: return await message.reply("Bhai name toh likh!")
    
    result = await collection.find_one({"caption": {"$regex": query, "$options": "i"}})
    if result:
        await bot.copy_message(chat_id=message.chat.id, from_chat_id=MEDIA_CHANNEL_ID, message_id=result["msg_id"])
    else:
        await message.reply("❌ Database mein nahi hai.")

@dp.message(Command("total"))
async def cmd_total(message: types.Message):
    count = await collection.count_documents({})
    await message.reply(f"📊 **Total Database:** `{count}`")

# --- KOYEB SERVER ---
async def health_check(request):
    return web.Response(text="Bot is Alive and Saving!", status=200)

async def main():
    await collection.create_index("file_unique_id", unique=True)
    
    # Port 8000 for Koyeb
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 8000).start()
    
    print("🚀 Anti-Conflict Engine Started. Cleaning old updates...")
    
    # drop_pending_updates=True is the key to fix Conflict Error
    await dp.start_polling(bot, skip_updates=True, drop_pending_updates=True)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
