import asyncio
import json
import os
import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.filters import Command

# --- تنظیمات ---
TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "users.json"

bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# --- توابع کمکی ---

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

async def get_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}USDT"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                return float(data["price"])
            return None

# --- دکمه‌ها ---
def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ افزودن ارز", callback_data="add_coin")],
        [InlineKeyboardButton(text="💲 نمایش قیمت‌ها", callback_data="show_prices")],
        [InlineKeyboardButton(text="📈 ثبت سقف و کف", callback_data="set_limits")]
    ])

# --- هندلر شروع ---
@router.message(Command("start"))
async def start_cmd(msg: Message):
    user_id = str(msg.from_user.id)
    data = load_data()
    if user_id not in data:
        data[user_id] = {"coins": {}, "limits": {}}
        save_data(data)
    await msg.answer("سلام 👋 به ربات هشدار قیمت خوش اومدی!", reply_markup=main_keyboard())

# --- افزودن ارز ---
@router.callback_query(F.data == "add_coin")
async def add_coin(cb: CallbackQuery):
    await cb.message.answer("نام ارز مورد نظر رو بفرست (مثلاً BTC یا Ethereum):")
    await cb.answer()
    dp["waiting_for_coin"] = cb.from_user.id

@router.message()
async def handle_message(msg: Message):
    user_id = str(msg.from_user.id)
    data = load_data()

    if dp.get("waiting_for_coin") == msg.from_user.id:
        coin = msg.text.strip().upper()
        price = await get_price(coin)
        if price is None:
            await msg.answer("❌ این ارز در بایننس پیدا نشد.")
        else:
            if len(data[user_id]["coins"]) >= 20:
                await msg.answer("🚫 حداکثر ۲۰ ارز می‌تونی اضافه کنی.")
            else:
                data[user_id]["coins"][coin] = price
                save_data(data)
                await msg.answer(f"✅ ارز {coin} با موفقیت افزوده شد.")
        dp["waiting_for_coin"] = None

# --- نمایش قیمت‌ها ---
@router.callback_query(F.data == "show_prices")
async def show_prices(cb: CallbackQuery):
    user_id = str(cb.from_user.id)
    data = load_data()

    if not data.get(user_id) or not data[user_id]["coins"]:
        await cb.message.answer("📭 هنوز هیچ ارزی اضافه نکردی.")
        await cb.answer()
        return

    msg_text = "💰 قیمت لحظه‌ای:\n\n"
    for coin in data[user_id]["coins"].keys():
        price = await get_price(coin)
        if price:
            msg_text += f"{coin} = {price:.2f} $\n"
    await cb.message.answer(msg_text)
    await cb.answer()

# --- ثبت سقف و کف ---
@router.callback_query(F.data == "set_limits")
async def set_limits(cb: CallbackQuery):
    user_id = str(cb.from_user.id)
    data = load_data()
    coins = list(data[user_id]["coins"].keys())

    if not coins:
        await cb.message.answer("📭 هیچ ارزی نداری که براش سقف یا کف ثبت کنی.")
        await cb.answer()
        return

    buttons = [[InlineKeyboardButton(text=c, callback_data=f"limit_{c}")] for c in coins]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await cb.message.answer("یکی از ارزها رو انتخاب کن:", reply_markup=markup)
    await cb.answer()

@router.callback_query(F.data.startswith("limit_"))
async def ask_limit(cb: CallbackQuery):
    coin = cb.data.replace("limit_", "")
    dp["waiting_limit_coin"] = (cb.from_user.id, coin)
    await cb.message.answer(f"مقدار سقف {coin} رو وارد کن (می‌تونی خالی بزاری):")
    await cb.answer()

@router.message()
async def handle_limits(msg: Message):
    user_id = msg.from_user.id
    waiting = dp.get("waiting_limit_coin")
    if waiting and waiting[0] == user_id:
        coin = waiting[1]
        data = load_data()
        data[str(user_id)]["limits"][coin] = {"high": msg.text.strip(), "low": None}
        save_data(data)
        dp["waiting_limit_coin"] = None
        await msg.answer("✅ مقدار ثبت شد. ربات تغییرات قیمت رو بررسی می‌کنه.")

# --- شروع ---
async def main():
    print("Bot is running ...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
