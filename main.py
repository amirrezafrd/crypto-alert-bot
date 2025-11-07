import asyncio
import json
import os
import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage  # برای FSM

# --- تنظیمات ---
TOKEN = os.getenv("7836143571:AAHkxNnb8e78LD01sP5BlohC9WQxT2DgcLs")
if TOKEN is None:
    raise ValueError("BOT_TOKEN is not set in environment variables.")

DATA_FILE = "users.json"

bot = Bot(token=TOKEN)
storage = MemoryStorage()  # برای FSM
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# --- States ---
class AddCoin(StatesGroup):
    waiting_for_coin = State()

class SetLimits(StatesGroup):
    select_coin = State()
    high = State()
    low = State()

class DeleteCoin(StatesGroup):
    select_coin = State()

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
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return float(data["price"])
    except Exception as e:
        print(f"Error getting price for {symbol}: {e}")
    return None

# --- دکمه‌ها ---
def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ افزودن ارز", callback_data="add_coin")],
        [InlineKeyboardButton(text="💲 نمایش قیمت‌ها", callback_data="show_prices")],
        [InlineKeyboardButton(text="📈 ثبت سقف و کف", callback_data="set_limits")],
        [InlineKeyboardButton(text="🗑 حذف ارز", callback_data="delete_coin")]
    ])

# --- هندلر شروع ---
@router.message(Command("start"))
async def start_cmd(msg: Message, state: FSMContext):
    await state.clear()  # پاک کردن state احتمالی
    user_id = str(msg.from_user.id)
    data = load_data()
    if user_id not in data:
        data[user_id] = {"coins": {}, "limits": {}}
        save_data(data)
    await msg.answer("سلام 👋 به ربات هشدار قیمت خوش اومدی!", reply_markup=main_keyboard())

# --- افزودن ارز ---
@router.callback_query(F.data == "add_coin")
async def add_coin(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer("نام ارز مورد نظر رو بفرست (مثلاً BTC یا Ethereum):")
    await state.set_state(AddCoin.waiting_for_coin)
    await cb.answer()

@router.message(AddCoin.waiting_for_coin)
async def handle_add_coin(msg: Message, state: FSMContext):
    user_id = str(msg.from_user.id)
    data = load_data()
    coin = msg.text.strip().upper()
    price = await get_price(coin)
    if price is None:
        await msg.answer("❌ این ارز در بایننس پیدا نشد.")
    else:
        if len(data[user_id]["coins"]) >= 20:
            await msg.answer("🚫 حداکثر ۲۰ ارز می‌تونی اضافه کنی.")
        else:
            data[user_id]["coins"][coin] = price  # ذخیره قیمت اولیه (اختیاری)
            save_data(data)
            await msg.answer(f"✅ ارز {coin} با موفقیت افزوده شد.")
    await state.clear()

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
    coins = list(data[user_id]["coins"].keys())
    prices = await asyncio.gather(*(get_price(coin) for coin in coins))
    for coin, price in zip(coins, prices):
        if price:
            msg_text += f"{coin} = {price:.2f} $\n"
    await cb.message.answer(msg_text)
    await cb.answer()

# --- ثبت سقف و کف ---
@router.callback_query(F.data == "set_limits")
async def set_limits(cb: CallbackQuery, state: FSMContext):
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
    await state.set_state(SetLimits.select_coin)
    await cb.answer()

@router.callback_query(SetLimits.select_coin, F.data.startswith("limit_"))
async def ask_high(cb: CallbackQuery, state: FSMContext):
    coin = cb.data.replace("limit_", "")
    await state.update_data(coin=coin)
    await cb.message.answer(f"مقدار سقف برای {coin} رو وارد کن (عدد، یا خالی برای رد شدن):")
    await state.set_state(SetLimits.high)
    await cb.answer()

@router.message(SetLimits.high)
async def handle_high(msg: Message, state: FSMContext):
    input_high = msg.text.strip()
    try:
        high = float(input_high) if input_high else None
    except ValueError:
        await msg.answer("❌ مقدار باید عدد باشه.")
        return
    await state.update_data(high=high)
    data_state = await state.get_data()
    coin = data_state["coin"]
    await msg.answer(f"مقدار کف برای {coin} رو وارد کن (عدد، یا خالی برای رد شدن):")
    await state.set_state(SetLimits.low)

@router.message(SetLimits.low)
async def handle_low(msg: Message, state: FSMContext):
    input_low = msg.text.strip()
    try:
        low = float(input_low) if input_low else None
    except ValueError:
        await msg.answer("❌ مقدار باید عدد باشه.")
        await state.clear()
        return
    data_state = await state.get_data()
    coin = data_state["coin"]
    high = data_state["high"]
    user_id = str(msg.from_user.id)
    data = load_data()
    data[user_id]["limits"][coin] = {"high": high, "low": low}
    save_data(data)
    await msg.answer(f"✅ محدودیت‌ها برای {coin} ثبت شد: سقف {high}, کف {low}")
    await state.clear()

# --- حذف ارز ---
@router.callback_query(F.data == "delete_coin")
async def delete_coin(cb: CallbackQuery, state: FSMContext):
    user_id = str(cb.from_user.id)
    data = load_data()
    coins = list(data[user_id]["coins"].keys())
    if not coins:
        await cb.message.answer("📭 هیچ ارزی نداری.")
        await cb.answer()
        return
    buttons = [[InlineKeyboardButton(text=c, callback_data=f"delete_{c}")] for c in coins]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await cb.message.answer("کدام ارز رو حذف کنم؟", reply_markup=markup)
    await state.set_state(DeleteCoin.select_coin)
    await cb.answer()

@router.callback_query(DeleteCoin.select_coin, F.data.startswith("delete_"))
async def confirm_delete(cb: CallbackQuery, state: FSMContext):
    coin = cb.data.replace("delete_", "")
    user_id = str(cb.from_user.id)
    data = load_data()
    if coin in data[user_id]["coins"]:
        del data[user_id]["coins"][coin]
        data[user_id]["limits"].pop(coin, None)
        save_data(data)
        await cb.message.answer(f"✅ {coin} حذف شد.")
    await state.clear()
    await cb.answer()

# --- چک دوره‌ای قیمت و هشدار ---
async def price_checker():
    while True:
        data = load_data()
        for user_id, user_data in data.items():
            coins = list(user_data["coins"].keys())
            prices = await asyncio.gather(*(get_price(coin) for coin in coins))
            for coin, price in zip(coins, prices):
                if price:
                    limits = user_data.get("limits", {}).get(coin, {})
                    high = limits.get("high")
                    low = limits.get("low")
                    if high and price > high:
                        await bot.send_message(user_id, f"⚠️ {coin} از سقف رد شد: {price:.2f} $")
                        # می‌تونی حد رو ریست کنی اگر بخوای: limits['high'] = None
                    if low and price < low:
                        await bot.send_message(user_id, f"⚠️ {coin} به کف رسید: {price:.2f} $")
                        # مشابه برای low
        await asyncio.sleep(60)  # هر ۱ دقیقه چک کن (می‌تونی تغییر بدی)

# --- شروع ---
async def main():
    print("Bot is running ...")
    asyncio.create_task(price_checker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
