import json
import asyncio
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from config import BOT_TOKEN, CHECK_INTERVAL

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DATA_FILE = "data/users.json"

# --- Helper functions ---
def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_binance_price(symbol):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}USDT")
        return float(res.json()["price"])
    except:
        return None

# --- Command /start ---
@dp.message(commands=["start"])
async def start(message: types.Message):
    user_id = str(message.from_user.id)
    data = load_data()
    if user_id not in data:
        data[user_id] = {"coins": [], "alerts": {}}
        save_data(data)

    kb = InlineKeyboardBuilder()
    kb.button(text="➕ افزودن ارز", callback_data="add_coin")
    kb.button(text="💰 نمایش قیمت لحظه‌ای", callback_data="show_prices")
    kb.button(text="⚙️ ثبت سقف و کف", callback_data="set_alert")

    await message.answer(
        "سلام 👋\nبه ربات قیمت‌ لحظه‌ای ارز دیجیتال خوش اومدی!",
        reply_markup=kb.as_markup()
    )

# --- افزودن ارز ---
@dp.callback_query(lambda c: c.data == "add_coin")
async def add_coin(callback: types.CallbackQuery):
    await callback.message.answer("نام ارز مورد نظر رو بفرست (مثل BTC یا Bitcoin):")
    await callback.answer()
    dp.message.register(process_coin_name, user_id=callback.from_user.id)

async def process_coin_name(message: types.Message):
    user_id = str(message.from_user.id)
    data = load_data()

    if len(data[user_id]["coins"]) >= 20:
        await message.answer("❌ حداکثر ۲۰ ارز می‌تونی اضافه کنی.")
        return

    coin = message.text.strip().upper()
    # تبدیل اسم کامل به نماد معروف
    mapping = {"BITCOIN": "BTC", "ETHEREUM": "ETH", "BNB": "BNB"}
    if coin in mapping:
        coin = mapping[coin]

    price = get_binance_price(coin)
    if price is None:
        await message.answer("⚠️ چنین ارزی در بایننس پیدا نشد.")
        return

    if coin not in data[user_id]["coins"]:
        data[user_id]["coins"].append(coin)
        save_data(data)
        await message.answer(f"✅ ارز {coin} با موفقیت اضافه شد.")
    else:
        await message.answer("⚠️ این ارز قبلاً اضافه شده.")

# --- نمایش قیمت لحظه‌ای ---
@dp.callback_query(lambda c: c.data == "show_prices")
async def show_prices(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    data = load_data()
    coins = data.get(user_id, {}).get("coins", [])
    if not coins:
        await callback.message.answer("❌ هنوز هیچ ارزی اضافه نکردی.")
        return

    msg = "💰 قیمت لحظه‌ای ارزها:\n"
    for coin in coins:
        price = get_binance_price(coin)
        if price:
            msg += f"{coin} = {price:.2f}$\n"
        else:
            msg += f"{coin} = ❌ نامعتبر\n"

    await callback.message.answer(msg)

# --- ثبت سقف و کف ---
@dp.callback_query(lambda c: c.data == "set_alert")
async def set_alert(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    data = load_data()
    coins = data.get(user_id, {}).get("coins", [])
    if not coins:
        await callback.message.answer("❌ هنوز هیچ ارزی اضافه نکردی.")
        return

    kb = InlineKeyboardBuilder()
    for c in coins:
        kb.button(text=c, callback_data=f"alert_{c}")
    await callback.message.answer("کدوم ارز رو می‌خوای برایش سقف یا کف ثبت کنی؟", reply_markup=kb.as_markup())

@dp.callback_query(lambda c: c.data.startswith("alert_"))
async def ask_price_limit(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    coin = callback.data.split("_", 1)[1]
    await callback.message.answer(f"قیمت سقف {coin} رو بفرست (یا بنویس 'هیچ' برای رد شدن):")
    dp.message.register(lambda m: process_ceiling(m, coin), user_id=callback.from_user.id)
    await callback.answer()

async def process_ceiling(message: types.Message, coin):
    ceiling_text = message.text.strip()
    ceiling = float(ceiling_text) if ceiling_text.lower() != "هیچ" else None
    await message.answer(f"حالا قیمت کف {coin} رو بفرست (یا 'هیچ'):")
    dp.message.register(lambda m: process_floor(m, coin, ceiling), user_id=message.from_user.id)

async def process_floor(message: types.Message, coin, ceiling):
    floor_text = message.text.strip()
    floor = float(floor_text) if floor_text.lower() != "هیچ" else None

    user_id = str(message.from_user.id)
    data = load_data()
    data[user_id]["alerts"][coin] = {"ceiling": ceiling, "floor": floor}
    save_data(data)

    await message.answer(f"✅ هشدار برای {coin} ثبت شد.\n"
                         f"سقف: {ceiling or '❌'} | کف: {floor or '❌'}")

# --- بررسی مداوم قیمت‌ها ---
async def check_alerts():
    while True:
        data = load_data()
        for user_id, info in data.items():
            for coin, limits in info.get("alerts", {}).items():
                price = get_binance_price(coin)
                if price:
                    if limits["ceiling"] and price >= limits["ceiling"]:
                        await bot.send_message(user_id, f"🚀 قیمت {coin} به سقف {limits['ceiling']}$ رسید!")
                        limits["ceiling"] = None
                    if limits["floor"] and price <= limits["floor"]:
                        await bot.send_message(user_id, f"📉 قیمت {coin} به کف {limits['floor']}$ رسید!")
                        limits["floor"] = None
        save_data(data)
        await asyncio.sleep(CHECK_INTERVAL)

# --- Run bot ---
async def main():
    asyncio.create_task(check_alerts())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
