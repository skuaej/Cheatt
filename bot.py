import os
import time
import asyncio
import re
import logging
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

client = AsyncIOMotorClient(MONGO_URI)
db = client["CheatBotDB"]
collection = db["cheats"]

# --- PARSING LOGIC (Sirf Name nikalne ke liye) ---
def parse_caption(text):
    # Pattern: 🆔️9828: Kaori Miyazono [🏖] -> Sirf "Kaori Miyazono" nikalega
    match = re.search(r"🆔️\d+:\s*([^\[\n\r]+)", text)
    if match:
        name = match.group(1).strip()
        return name
    # Agar format alag hai toh pehli line uthayega
    return text.split('\n')[0].strip()

# --- MEDIA HANDLER (Photo & Video) ---
@dp.message(F.photo | F.video)
async def handle_media(message: types.Message):
    media = message.photo[-1] if message.photo else message.video
    unique_id = media.file_unique_id
    
    existing = await collection.find_one({"file_unique_id": unique_id})

    if existing:
        # Puraana data: Click to copy format
        await message.reply(f"`/take {existing['caption']}`")
    else:
        if message.caption:
            clean_name = parse_caption(message.caption)
            try:
                # Backup to Media Channel
                backup = await bot.copy_message(
                    chat_id=MEDIA_CHANNEL_ID,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id
                )
                
                # Save to DB
                await collection.update_one(
                    {"file_unique_id": unique_id},
                    {"$set": {
                        "msg_id": backup.message_id,
                        "caption": clean_name
                    }},
                    upsert=True
                )
                # Success Reply
                await message.reply(f"📥 **Saved!**\n\n`/take {clean_name}`")
            except Exception as e:
                await message.reply(f"❌ Backup Error: {e}")
        else:
            await message.reply("❌ Bhai, isme caption nahi hai! Caption ke bina naam kaise nikalun?")

# --- SEARCH COMMAND (/search name) ---
@dp.message(Command("search"))
async def search_media(message: types.Message):
    args = message.text.split(" ", 1)
    if len(args) < 2:
        await message.reply("Usage: `/search Kaori`")
        return

    query = args[1].strip()
    # Case-insensitive search in DB
    result = await collection.find_one({"caption": {"$regex": query, "$options": "i"}})
    
    if result:
        try:
            await bot.copy_message(
                chat_id=message.chat.id,
                from_chat_id=MEDIA_CHANNEL_ID,
                message_id=result["msg_id"]
            )
        except:
            await message.reply("❌ Media channel mein nahi mila!")
    else:
        await message.reply("❌ Database mein ye naam nahi hai.")

# --- OWNER COMMANDS ---
@dp.message(Command("total"))
async def cmd_total(message: types.Message):
    if message.from_user.id != OWNER_ID: return
    count = await collection.count_documents({})
    await message.reply(f"📊 **Total Database:** `{count}`")

# --- KOYEB PORT 8080 HEALTH CHECK ---
async def health_check(request):
    return web.Response(text="Bot is Alive!", status=200)

async def start_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080) # Fixed for Koyeb
    await site.start()

async def main():
    # Indexes for fast search
    await collection.create_index("file_unique_id", unique=True)
    await collection.create_index("caption")
    
    # Start Health Server
    await start_server()
    print("🚀 Koyeb Health Check Server on Port 8080 is Running")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
