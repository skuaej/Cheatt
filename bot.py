import os
import time
import asyncio
import re
import logging
import shutil
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
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

# Default ParseMode HTML set kar diya hai taaki <code> tag kaam kare
bot = Bot(token=BOT_TOKEN, default_parse_mode=ParseMode.HTML)
dp = Dispatcher()

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
    try:
        with open('/proc/meminfo', 'r') as f:
            lines = f.readlines()
        mem_total = int(lines[0].split()[1]) / 1024
        mem_free = int(lines[1].split()[1]) / 1024
        ram_u = round(mem_total - mem_free, 2)
        ram_t = round(mem_total, 2)
    except: ram_u, ram_t = 0, 0
    total, used, free = shutil.disk_usage("/")
    return ram_u, ram_t, round(used / (1024**3), 2), round(total / (1024**3), 2)

# --- HANDLERS ---

@dp.message(F.photo | F.video)
async def handle_media(message: types.Message):
    media = message.photo[-1] if message.photo else message.video
    unique_id = media.file_unique_id
    
    existing = await collection.find_one({"file_unique_id": unique_id})

    if existing:
        # <code> tag ensures auto-copy on Telegram mobile
        await message.reply(f"<code>/take {existing['caption']}</code>")
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
                    {"$set": {"msg_id": backup.message_id, "caption": clean_name}},
                    upsert=True
                )
                
                # Reply with ONLY the copyable command
                await message.reply(f"<code>/take {clean_name}</code>")
                
                # Silent Log
                try:
                    await bot.send_message(LOG_CHANNEL_ID, f"🆕 Saved: <code>{clean_name}</code>")
                except: pass

            except Exception as e:
                await message.reply(f"Error: {e}")
        else:
            await message.reply("Bhai caption (name) toh likh!")

@dp.message(Command("search"))
async def search_media(message: types.Message):
    query = message.text.replace("/search", "").strip().lower()
    if not query: return await message.reply("Usage: /search Name")

    result = await collection.find_one({"caption": {"$regex": query, "$options": "i"}})
    
    if result:
        try:
            await bot.copy_message(
                chat_id=message.chat.id, 
                from_chat_id=MEDIA_CHANNEL_ID, 
                message_id=result["msg_id"]
            )
        except:
            await message.reply("Error: Bot backup channel mein Admin nahi hai!")
    else:
        await message.reply("Database mein nahi mila.")

@dp.message(Command("ping"))
async def cmd_ping(message: types.Message):
    start = time.time()
    msg = await message.answer("⚡ Checking...")
    latency = round((time.time() - start) * 1000)
    ram_u, ram_t, sto_u, sto_t = get_sys_info()
    
    status_msg = (
        f"🚀 <b>Status: Healthy</b>\n\n"
        f"⏱ <b>Ping:</b> <code>{latency}ms</code>\n"
        f"📟 <b>RAM:</b> <code>{ram_u}MB / {ram_t}MB</code>\n"
        f"💾 <b>Storage:</b> <code>{sto_u}GB / {sto_t}GB</code>"
    )
    await msg.edit_text(text=status_msg)

@dp.message(Command("total"))
async def cmd_total(message: types.Message):
    if message.from_user.id != OWNER_ID: return
    count = await collection.count_documents({})
    await message.reply(f"📊 <b>Total DB:</b> <code>{count}</code>")

# --- KOYEB PORT 8000 ---
async def health_check(request):
    return web.Response(text="Bot Alive", status=200)

async def main():
    await collection.create_index("file_unique_id", unique=True)
    await collection.create_index("caption")
    
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    # Koyeb Port 8000
    await web.TCPSite(runner, '0.0.0.0', 8000).start()
    
    print("🚀 Port 8000 Started. Bot is Live.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
    
