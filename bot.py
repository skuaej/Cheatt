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
MEDIA_CHANNEL_ID = int(os.getenv("MEDIA_CHANNEL_ID")) 
SOURCE_CHANNEL_ID = int(os.getenv("SOURCE_CHANNEL_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

client = AsyncIOMotorClient(MONGO_URI)
db = client["CheatBotDB"]
collection = db["cheats"]

# Strict Queue to prevent Flood
sem = asyncio.Semaphore(1)

# --- UTILS ---
def parse_caption(text):
    if not text: return None
    match = re.search(r"(?:🆔️\d+:\s*)?([^\[\n\r]+)", text)
    if match:
        return match.group(1).strip()
    return text.split('\n')[0].strip()

# --- THE SAVER ---
async def process_and_save(message: types.Message):
    async with sem:
        media = message.photo[-1] if message.photo else message.video
        if not media: return
        
        unique_id = media.file_unique_id
        # Support for same caption, different image
        existing = await collection.find_one({"file_unique_id": unique_id})
        if existing: return 

        clean_name = parse_caption(message.caption)
        if not clean_name: return

        try:
            backup = await bot.copy_message(
                chat_id=MEDIA_CHANNEL_ID,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            await collection.update_one(
                {"file_unique_id": unique_id},
                {"$set": {"msg_id": backup.message_id, "caption": clean_name}},
                upsert=True
            )
            print(f"✅ SAVED: {clean_name}")
            # ONE TAP COPY REPLIES
            await message.reply(f"`/take {clean_name}`", parse_mode="Markdown")
            await asyncio.sleep(2)

        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            await process_and_save(message)
        except Exception as e:
            print(f"❌ Error: {e}")

# --- COMMANDS ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.reply("🚀 **Bot Online!** Send media or use `/search`.")

@dp.message(Command("search"))
async def search_media(message: types.Message):
    query = message.text.replace("/search", "").strip()
    if not query: return await message.reply("`/search Name` likh bhai!")
    
    result = await collection.find_one({"caption": {"$regex": query, "$options": "i"}})
    if result:
        await bot.copy_message(chat_id=message.chat.id, from_chat_id=MEDIA_CHANNEL_ID, message_id=result["msg_id"])
    else:
        await message.reply("❌ Database mein nahi mila.")

@dp.message(Command("ping"))
async def cmd_ping(message: types.Message):
    await message.reply("🏓 **Pong!** Bot is active.")

@dp.message(Command("total"))
async def cmd_total(message: types.Message):
    count = await collection.count_documents({})
    await message.reply(f"📊 **Total Database:** `{count}`")

# --- HANDLERS ---
@dp.message(F.photo | F.video)
async def handle_private(message: types.Message):
    await process_and_save(message)

@dp.channel_post(F.photo | F.video)
async def handle_channel(message: types.Message):
    # Fix: Matching with integer ID
    if message.chat.id == SOURCE_CHANNEL_ID:
        await process_and_save(message)

# --- KOYEB SERVER ---
async def health_check(request):
    return web.Response(text="Bot is Alive", status=200)

async def main():
    await collection.create_index("file_unique_id", unique=True)
    
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 8000).start()
    
    # --- THE CONFLICT KILLER ---
    print("🧹 Cleaning Webhooks & Pending Updates...")
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Startup Notification to Owner
    try:
        await bot.send_message(OWNER_ID, "✅ **Bot has successfully restarted and cleaned sessions!**")
    except: pass

    print("🚀 Bot is Polling now...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
    
