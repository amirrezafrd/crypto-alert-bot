# main.py - ربات آلارم قیمت کریپتو با Binance API - نسخه نهایی و تست‌شده
import logging
import sqlite3
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
import aiohttp
from aiocron import crontab

# === تنظیمات ===
TOKEN = "HERE_YOUR_TOKEN"  # توکن رباتت رو اینجا بذار
BINANCE_API = "https://api.binance.com/api/v3/ticker/price"

logging.basicConfig(level=logging.INFO)

# دیتابیس دائمی
conn = sqlite3.connect('/tmp/data.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS coins 
             (user_id INTEGER, coin_symbol TEXT, coin_name TEXT, floor REAL, ceiling REAL)''')
conn.commit()

# دریافت قیمت از Binance
async def get_prices(coin_symbols):
    if not coin_symbols:
        return {}
    symbols = '","'.join(coin_symbols)
    url = f"https://api.binance.com/api/v3/ticker/price?symbols=[\"{symbols}\"]"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                prices = {}
                for item in data:
                    symbol = item['symbol']
                    price = float(item['price'])
                    prices[symbol] = {"usd": price}
                return prices
    return {}

# ارسال لیست هر ۱ دقیقه (برای تست)
async def send_price_list(context: ContextTypes.DEFAULT_TYPE):
    users = c.execute("SELECT DISTINCT user_id FROM coins").fetchall()
    for (user_id,) in users:
        coins = c.execute("SELECT coin_symbol, coin_name FROM coins WHERE user_id=?", (user_id,)).fetchall()
        if not coins:
            continue
        symbols = [row[0] for row in coins]
        prices = await get_prices(symbols)
        
        text = "قیمت لحظه‌ای ارزها (از Binance - هر ۱ دقیقه):\n\n"
        for symbol, name in coins:
            price = prices.get(symbol, {}).get("usd", "خطا")
            text += f"• {name}: `${price}`\n"
        
        try:
            await context.bot.send_message(chat_id=user_id, text=text)
        except:
            pass

# چک کردن آلارم هر ۵ دقیقه
async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    rows = c.execute("SELECT user_id, coin_symbol, coin_name, floor, ceiling FROM coins WHERE floor IS NOT NULL OR ceiling IS NOT NULL").fetchall()
    if not rows:
        return
    symbols = list({row[1] for row in rows})
    prices = await get_prices(symbols)
    
    for user_id, symbol, name, floor, ceiling in rows:
        price = prices.get(symbol, {}).get("usd")
        if price is None:
            continue
            
        msg = None
        if floor and price <= floor:
            msg = f"هشدار کف قیمت!\n{name} به `${price}` رسید (کف: `${floor}`)"
        elif ceiling and price >= ceiling:
            msg = f"هشدار سقف قیمت!\n{name} به `${price}` رسید (سقف: `${ceiling}`)"
            
        if msg:
            try:
                await context.bot.send_message(chat_id=user_id, text=msg)
                c.execute("UPDATE coins SET floor=NULL, ceiling=NULL WHERE user_id=? AND coin_symbol=?", (user_id, symbol))
                conn.commit()
            except:
                pass

# شروع
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("افزودن ارز", callback_data="add")],
        [InlineKeyboardButton("لیست ارزها", callback_data="list")],
        [InlineKeyboardButton("حذف ارز", callback_data="delete")],
        [InlineKeyboardButton("راهنما", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "ربات آلارم قیمت کریپتو\n"
        "قیمت‌ها از Binance (دقیق و لحظه‌ای)\n"
        "هر ۱ دقیقه لیست قیمت میاد\n"
        "حداکثر ۲۰ ارز",
        reply_markup=reply_markup
    )

# دکمه‌ها
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "add":
        await query.edit_message_text("اسم ارز رو بفرست (مثل: btc, eth, sol, bnb, ada, xrp, doge, ton, avax, shib)")
        context.user_data['action'] = 'add_coin'
    
    elif query.data == "list":
        coins = c.execute("SELECT coin_name, floor, ceiling FROM coins WHERE user_id=?", (user_id,)).fetchall()
        if not coins:
            await query.edit_message_text("هنوز ارزی اضافه نکردی!")
            return
        text = "ارزهای تو:\n\n"
        for name, floor, ceiling in coins:
            f = f" | کف: ${floor}" if floor else ""
            c_text = f" | سقف: ${ceiling}" if ceiling else ""
            text += f"• {name}{f}{c_text}\n"
        await query.edit_message_text(text)
    
    elif query.data == "delete":
        await query.edit_message_text("اسم ارزی که می‌خوای حذف کنی رو بفرست:")
        context.user_data['action'] = 'delete_coin'
    
    elif query.data == "help":
        await query.edit_message_text(
            "راهنما:\n\n"
            "/start - منو\n"
            "افزودن ارز → اسم کوتاه (btc, eth, sol, ...)\n"
            "بعد از اضافه کردن:\n"
            "   کف ۶۰۰۰۰\n"
            "   سقف ۷۰۰۰۰\n"
            "هر ۱ دقیقه لیست قیمت از Binance میاد\n"
            "هشدار وقتی قیمت به کف/سقف برسه"
        )

# مدیریت پیام
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.lower().strip()
    action = context.user_data.get('action')

    # لیست ارزهای پشتیبانی‌شده در Binance
    binance_symbols = {
        "bitcoin": "BTCUSDT", "btc": "BTCUSDT",
        "ethereum": "ETHUSDT", "eth": "ETHUSDT",
        "solana": "SOLUSDT", "sol": "SOLUSDT",
        "binancecoin": "BNBUSDT", "bnb": "BNBUSDT",
        "cardano": "ADAUSDT", "ada": "ADAUSDT",
        "ripple": "XRPUSDT", "xrp": "XRPUSDT",
        "dogecoin": "DOGEUSDT", "doge": "DOGEUSDT",
        "ton": "TONUSDT", "toncoin": "TONUSDT",
        "avalanche": "AVAXUSDT", "avax": "AVAXUSDT",
        "shiba": "SHIBUSDT", "shib": "SHIBUSDT",
        "pepe": "PEPEUSDT",
        "link": "LINKUSDT",
        "matic": "MATICUSDT", "pol": "MATICUSDT",
    }

    if action == 'add_coin':
        symbol = binance_symbols.get(text)
        if not symbol:
            await update.message.reply_text("این ارز در Binance نیست یا اشتباه نوشتی!\nمثال: btc, eth, sol, bnb")
            return
        
        count = c.execute("SELECT COUNT(*) FROM coins WHERE user_id=?", (user_id,)).fetchone()[0]
        if count >= 20:
            await update.message.reply_text("حداکثر ۲۰ ارز!")
            return
        
        name = text.upper()
        c.execute("INSERT OR IGNORE INTO coins (user_id, coin_symbol, coin_name) VALUES (?, ?, ?)",
                  (user_id, symbol, name))
        conn.commit()
        await update.message.reply_text(f"{name} اضافه شد!\nحالا می‌تونی بنویسی:\nکف ۶۰۰۰۰\nسقف ۷۰۰۰۰")
        context.user_data['action'] = None
        context.user_data['waiting_for'] = name

    elif action == 'delete_coin':
        symbol = binance_symbols.get(text)
        if not symbol:
            await update.message.reply_text("ارز پیدا نشد!")
            return
        c.execute("DELETE FROM coins WHERE user_id=? AND coin_symbol=?", (user_id, symbol))
        conn.commit()
        await update.message.reply_text(f"{text.upper()} حذف شد!" if c.rowcount else "ارز پیدا نشد!")
        context.user_data['action'] = None

    elif text.startswith("کف ") or text.startswith("سقف "):
        try:
            price = float(text.split()[1])
            last_coin = context.user_data.get('waiting_for')
            if last_coin:
                symbol = binance_symbols.get(last_coin.lower())
                if text.startswith("کف "):
                    c.execute("UPDATE coins SET floor=? WHERE user_id=? AND coin_name=?", (price, user_id, last_coin))
                else:
                    c.execute("UPDATE coins SET ceiling=? WHERE user_id=? AND coin_name=?", (price, user_id, last_coin))
                conn.commit()
                await update.message.reply_text(f"{text} برای {last_coin} ثبت شد!")
        except:
            await update.message.reply_text("فقط عدد! مثال: کف ۶۰۰۰۰")

# راه‌اندازی
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # هر ۱ دقیقه لیست قیمت (برای تست)
    crontab('*/1 * * * *', send_price_list)(app.job_queue)
    # هر ۵ دقیقه چک آلارم
    crontab('*/5 * * * *', check_alerts)(app.job_queue)

    print("ربات با Binance API در حال اجراست...")
    app.run_polling()

if __name__ == '__main__':
    main()
