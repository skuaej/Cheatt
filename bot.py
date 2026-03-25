import os
import time
import asyncio
import re
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.exceptions import TelegramRetryAfter
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
OWNER_ID = int(os.getenv("OWNER_ID"))
MEDIA_CHANNEL_ID = int(os.getenv("MEDIA_CHANNEL_ID")) 
SOURCE_CHANNEL_ID = int(os.getenv("SOURCE_CHANNEL_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

client = AsyncIOMotorClient(MONGO_URI)
db = client["CheatBotDB"]
collection = db["cheats"]

# --- TURBO SEMAPHORE ---
# Ab ek saath 5 media process honge (Fast & Safe)
sem = asyncio.Semaphore(5)

# --- UTILS ---
def parse_caption(text):
    if not text: return None
    # Flexible Regex: ID ke bina bhi naam nikal lega agar format thoda alag ho
    match = re.search(r"(?:🆔️\d+:\s*)?([^\[\n\r]+)", text)
    if match:
        return match.group(1).strip()
    return text.split('\n')[0].strip()

# --- CORE SAVING LOGIC ---
async def process_and_save(message: types.Message):
    async with sem:
        media = message.photo[-1] if message.photo else message.video
        if not media:
            print("⚠️ SKIPPED: No Photo/Video found in message.")
            return
        
        unique_id = media.file_unique_id
        
        # 1. DB Check
        existing = await collection.find_one({"file_unique_id": unique_id})
        if existing:
            print(f"⏩ SKIPPED: Duplicate media found ({existing['caption']})")
            return 

        clean_name = parse_caption(message.caption)
        if not clean_name:
            print("⚠️ SKIPPED: Caption missing or could not be parsed.")
            return

        try:
            # 2. Backup to Channel
            backup = await bot.copy_message(
                chat_id=MEDIA_CHANNEL_ID,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            
            # 3. DB Save
            await collection.update_one(
                {"file_unique_id": unique_id},
                {"$set": {"msg_id": backup.message_id, "caption": clean_name}},
                upsert=True
            )
            
            print(f"✅ SUCCESSFULLY SAVED: {clean_name}")
            
            # 4. Small delay to prevent Flood (1 sec is enough for 5 parallel tasks)
            await asyncio.sleep(1)

        except TelegramRetryAfter as e:
            print(f"⚠️ Flood limit hit! Sleeping for {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
            await process_and_save(message) # Retry
        except Exception as e:
            print(f"❌ ERROR saving {clean_name}: {e}")

# --- HANDLERS ---

@dp.message(F.photo | F.video)
async def handle_private(message: types.Message):
    await process_and_save(message)

@dp.channel_post(F.photo | F.video)
async def handle_channel(message: types.Message):
    # Support both int and string comparisons for ID
    if str(message.chat.id) == str(SOURCE_CHANNEL_ID):
        await process_and_save(message)
    else:
        print(f"ℹ️ Received post from unknown channel: {message.chat.id}")

@dp.message(Command("total"))
async def cmd_total(message: types.Message):
    count = await collection.count_documents({})
    await message.reply(f"📊 **Total Database:** `{count}`")

# --- KOYEB SERVER ---
async def health_check(request):
    return web.Response(text="Bot is Alive and Saving!", status=200)

async def main():
    await collection.create_index("file_unique_id", unique=True)
    
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 8000).start()
    
    print("🚀 Turbo Engine Started. Handling bulk forwards...")
    
    # skip_updates=True ensures we don't get flooded with old failed attempts
    await dp.start_polling(bot, skip_updates=True, drop_pending_updates=True)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
    
