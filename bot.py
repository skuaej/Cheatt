import os
import time
import asyncio
import re
import logging
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
SOURCE_CHANNEL_ID = int(os.getenv("SOURCE_CHANNEL_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

client = AsyncIOMotorClient(MONGO_URI)
db = client["CheatBotDB"]
collection = db["cheats"]

# --- UTILS ---
def parse_caption(text):
    if not text: return None
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

# --- CORE SAVING LOGIC ---
async def process_and_save(message: types.Message):
    media = message.photo[-1] if message.photo else message.video
    if not media: return
    
    unique_id = media.file_unique_id
    existing = await collection.find_one({"file_unique_id": unique_id})

    if existing:
        # One-tap copy reply
        await message.reply(f"`/take {existing['caption']}`", parse_mode="Markdown")
    else:
        clean_name = parse_caption(message.caption)
        if clean_name:
            try:
                # Copy to Backup Storage Channel
                backup = await bot.copy_message(
                    chat_id=MEDIA_CHANNEL_ID,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id
                )
                
                # Save to MongoDB
                await collection.update_one(
                    {"file_unique_id": unique_id},
                    {"$set": {"msg_id": backup.message_id, "caption": clean_name}},
                    upsert=True
                )
                
                # One-tap copy command reply
                await message.reply(f"`/take {clean_name}`", parse_mode="Markdown")
                
                # Log to Log Channel
                try:
                    await bot.send_message(LOG_CHANNEL_ID, f"🆕 **Saved:** `{clean_name}`", parse_mode="Markdown")
                except: pass
            except Exception as e:
                logging.error(f"Backup Error: {e}")

# --- HANDLERS ---

# Handle Media in Private Chats and Groups
@dp.message(F.photo | F.video)
async def handle_private_media(message: types.Message):
    await process_and_save(message)

# Handle Media in Channels (Yeh missing tha!)
@dp.channel_post(F.photo | F.video)
async def handle_channel_media(message: types.Message):
    # Sirf tere Source Channel se hi save karega
    if message.chat.id == SOURCE_CHANNEL_ID:
        await process_and_save(message)

@dp.message(Command("search"))
async def search_media(message: types.Message):
    query = message.text.replace("/search", "").strip().lower()
    if not query: return await message.reply("Usage: `/search Name`")

    result = await collection.find_one({"caption": {"$regex": query, "$options": "i"}})
    if result:
        try:
            await bot.copy_message(
                chat_id=message.chat.id, 
                from_chat_id=MEDIA_CHANNEL_ID, 
                message_id=result["msg_id"]
            )
        except:
            await message.reply("❌ Error: Bot ko Backup Channel mein Admin banao!")
    else:
        await message.reply("❌ Database mein nahi mila.")

@dp.message(Command("ping"))
async def cmd_ping(message: types.Message):
    start = time.time()
    msg = await message.answer("⚡ Checking...")
    latency = round((time.time() - start) * 1000)
    ram_u, ram_t, sto_u, sto_t = get_sys_info()
    status_msg = f"🚀 **Status:** Healthy\n⏱ **Ping:** `{latency}ms`\n📟 **RAM:** `{ram_u}MB / {ram_t}MB`"
    await msg.edit_text(text=status_msg)

@dp.message(Command("total"))
async def cmd_total(message: types.Message):
    if message.from_user.id != OWNER_ID: return
    count = await collection.count_documents({})
    await message.reply(f"📊 **Total Database:** `{count}`")

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
    await web.TCPSite(runner, '0.0.0.0', 8000).start()
    
    print("🚀 Bot is running with Channel Support on Port 8000")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
    
