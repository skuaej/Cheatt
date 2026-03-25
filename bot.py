import os
import time
import asyncio
import re
import logging
import psutil
import shutil
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
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

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# MongoDB Setup
client = AsyncIOMotorClient(MONGO_URI)
db = client["CheatBotDB"]
collection = db["cheats"]

# --- UTILS ---
def parse_caption(text):
    # Pattern: 🆔️9828: Kaori Miyazono [🏖] -> "Kaori Miyazono"
    match = re.search(r"🆔️\d+:\s*([^\[\n\r]+)", text)
    if match:
        return match.group(1).strip()
    return text.split('\n')[0].strip()

def get_sys_info():
    mem = psutil.virtual_memory()
    ram_used = round(mem.used / (1024**2), 2)
    ram_total = round(mem.total / (1024**2), 2)
    total, used, free = shutil.disk_usage("/")
    sto_used = round(used / (1024**3), 2)
    sto_total = round(total / (1024**3), 2)
    return ram_used, ram_total, sto_used, sto_total

# --- HANDLERS ---

@dp.message(F.photo | F.video)
async def handle_media(message: types.Message):
    media = message.photo[-1] if message.photo else message.video
    unique_id = media.file_unique_id
    
    existing = await collection.find_one({"file_unique_id": unique_id})

    if existing:
        await message.reply(f"`/take {existing['caption']}`")
    else:
        if message.caption:
            clean_name = parse_caption(message.caption)
            try:
                # Immortal Backup
                backup = await bot.copy_message(
                    chat_id=MEDIA_CHANNEL_ID,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id
                )
                
                await collection.update_one(
                    {"file_unique_id": unique_id},
                    {"$set": {
                        "msg_id": backup.message_id,
                        "caption": clean_name
                    }},
                    upsert=True
                )
                # Format fixed: No extra quotes, one-tap copy
                await message.reply(f"📥 **Saved!**\n\n`/take {clean_name}`")
            except Exception as e:
                await message.reply(f"❌ Error: {e}")

@dp.message(Command("ping"))
async def cmd_ping(message: types.Message):
    start_time = time.time()
    msg = await message.answer("⚡ Checking System...")
    latency = round((time.time() - start_time) * 1000)
    
    ram_u, ram_t, sto_u, sto_t = get_sys_info()
    status_msg = (
        f"🚀 **Bot Health: Healthy**\n\n"
        f"⏱ **Ping:** `{latency}ms`\n"
        f"📟 **RAM:** `{ram_u}MB / {ram_t}MB`\n"
        f"💾 **Storage:** `{sto_u}GB / {sto_t}GB`"
    )
    await msg.edit(text=status_msg)

@dp.message(Command("total"))
async def cmd_total(message: types.Message):
    if message.from_user.id != OWNER_ID: return
    count = await collection.count_documents({})
    await message.reply(f"📊 **Total Database:** `{count}`")

# --- KOYEB SERVER (Fixed Concurrency) ---
async def health_check(request):
    return web.Response(text="I am alive!", status=200)

async def start_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    # 0.0.0.0 is mandatory for Koyeb health checks
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    print("✅ Port 8080 Web Server Started.")

async def main():
    # 1. Database Indexing
    await collection.create_index("file_unique_id", unique=True)
    
    # 2. Show Total Characters in Logs on Startup
    total_chars = await collection.count_documents({})
    print("=" * 40)
    print(f"📊 STARTUP LOG: Total Characters in DB: {total_chars}")
    print("=" * 40)

    # 3. Start Web Server
    await start_server()

    # 4. Start Bot Polling
    print("🚀 Bot Polling Started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot Stopped!")
