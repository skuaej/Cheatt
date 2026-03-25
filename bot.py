import os
import time
import asyncio
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

# --- START LOGGING ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    log_text = (
        f"👤 **User Started Bot**\n\n"
        f"ID: `{user.id}`\n"
        f"Name: {user.first_name}\n"
        f"User: @{user.username if user.username else 'N/A'}"
    )
    try:
        await bot.send_message(LOG_CHANNEL_ID, log_text)
    except: pass
    await message.answer("Bhai Bot Ready Hai! Photo bhejo backup ke liye.")

# --- PHOTO HANDLER (Saving Message ID for Immortality) ---
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    photo = message.photo[-1]
    unique_id = photo.file_unique_id
    
    # Check if duplicate
    existing = await collection.find_one({"file_unique_id": unique_id})

    if existing:
        name = existing['caption'].replace(" ", "_")
        await message.reply(f" `/take {name}`")
    else:
        if message.caption:
            name = message.caption.strip()
            try:
                # 1. Channel mein photo copy karo
                backup = await bot.copy_message(
                    chat_id=MEDIA_CHANNEL_ID,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                    caption=f"Name: {name}\nUnique ID: {unique_id}"
                )
                
                # 2. DB mein Message ID save karo (Ye kabhi change nahi hota)
                await collection.update_one(
                    {"file_unique_id": unique_id},
                    {"$set": {
                        "msg_id": backup.message_id, # Yeh hai asli power
                        "caption": name
                    }},
                    upsert=True
                )
                await message.reply(f"📥 **Saved!**\n\n `/take {name.replace(' ', '_')}`")
            except Exception as e:
                await message.reply(f"❌ Error: {e}")
        else:
            await message.reply("❌ Caption ke saath bhejo tabhi save hoga.")

# --- SEARCH HANDLER (Using Copy Message) ---
@dp.message(F.text.startswith("/take "))
async def take_cheat(message: types.Message):
    name_to_find = message.text.replace("/take ", "").replace("_", " ").strip().lower()
    
    # Search in DB
    result = await collection.find_one({"caption": {"$regex": f"^{name_to_find}$", "$options": "i"}})
    
    if result:
        try:
            # Bot channel se message copy karke user ko dega
            await bot.copy_message(
                chat_id=message.chat.id,
                from_chat_id=MEDIA_CHANNEL_ID,
                message_id=result["msg_id"]
            )
        except:
            await message.reply("❌ Photo nahi mili! Shayad channel se delete ho gayi.")
    else:
        await message.reply("❌ Is naam ka koi cheat nahi hai.")

# --- UTILITY COMMANDS ---
@dp.message(Command("total"))
async def cmd_total(message: types.Message):
    if message.from_user.id != OWNER_ID: return
    count = await collection.count_documents({})
    await message.reply(f"📊 **Database:** `{count}` entries.")

@dp.message(Command("ping"))
async def cmd_ping(message: types.Message):
    s = time.time()
    m = await message.answer("Wait...")
    await m.edit(f"🚀 **Ping:** `{round((time.time()-s)*1000)}ms` | `Healthy` ✅")

# --- KOYEB SERVER ---
async def health_check(request):
    return web.Response(text="Bot is Live", status=200)

async def main():
    await collection.create_index("file_unique_id", unique=True)
    await collection.create_index("caption")
    
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 8080).start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

