# main.py - ربات آلارم قیمت کریپتو - نسخه کامل و ساده
import logging
import sqlite3
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
import aiohttp
from aiocron import crontab

# === تنظیمات ===
TOKEN = "7836143571:AAHkxNnb8e78LD01sP5BlohC9WQxT2DgcLs"  # <--- توکن رو اینجا بذار
COINGECKO_API = "https://api.coingecko.com/api/v3/simple/price"

logging.basicConfig(level=logging.INFO)

# دیتابیس
conn = sqlite3.connect('data.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS coins 
             (user_id INTEGER, coin_id TEXT, coin_name TEXT, floor REAL, ceiling REAL)''')
conn.commit()

# دریافت قیمت
async def get_prices(coin_ids):
    if not coin_ids:
        return {}
    ids = ",".join(coin_ids)
    params = {"ids": ids, "vs_currencies": "usd"}
    async with aiohttp.ClientSession() as session:
        async with session.get(COINGECKO_API, params=params) as resp:
            if resp.status == 200:
                return await resp.json()
    return {}

# ارسال لیست هر ۳۰ دقیقه
async def send_price_list(context: ContextTypes.DEFAULT_TYPE):
    users = c.execute("SELECT DISTINCT user_id FROM coins").fetchall()
    for (user_id,) in users:
        coins = c.execute("SELECT coin_id, coin_name FROM coins WHERE user_id=?", (user_id,)).fetchall()
        if not coins:
            continue
        coin_ids = [row[0] for row in coins]
        prices = await get_prices(coin_ids)
        
        text = "قیمت لحظه‌ای ارزهای شما (هر ۳۰ دقیقه):\n\n"
        for coin_id, coin_name in coins:
            price = prices.get(coin_id, {}).get("usd", "خطا")
            text += f"• {coin_name}: `${price}`\n"
        
        try:
            await context.bot.send_message(chat_id=user_id, text=text)
        except:
            pass

# چک کردن آلارم
async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    rows = c.execute("SELECT user_id, coin_id, coin_name, floor, ceiling FROM coins WHERE floor IS NOT NULL OR ceiling IS NOT NULL").fetchall()
    if not rows:
        return
    coin_ids = list({row[1] for row in rows})
    prices = await get_prices(coin_ids)
    
    for user_id, coin_id, coin_name, floor, ceiling in rows:
        price = prices.get(coin_id, {}).get("usd")
        if price is None:
            continue
            
        msg = None
        if floor and price <= floor:
            msg = f"هشدار کف قیمت!\n{coin_name} به `${price}` رسید (کف: `${floor}`)"
        elif ceiling and price >= ceiling:
            msg = f"هشدار سقف قیمت!\n{coin_name} به `${price}` رسید (سقف: `${ceiling}`)"
            
        if msg:
            try:
                await context.bot.send_message(chat_id=user_id, text=msg)
                c.execute("UPDATE coins SET floor=NULL, ceiling=NULL WHERE user_id=? AND coin_id=?", (user_id, coin_id))
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
        "ربات آلارم قیمت کریپتو\n\n"
        "حداکثر ۲۰ ارز می‌تونی اضافه کنی\n"
        "هر ۳۰ دقیقه قیمت همه رو می‌فرستم\n"
        "می‌تونی کف و سقف قیمت بذاری تا هشدار بدم",
        reply_markup=reply_markup
    )

# دکمه‌ها
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "add":
        await query.edit_message_text("اسم ارز رو بفرست (مثلاً: bitcoin یا ethereum)\nلیست: bitcoin, ethereum, solana, cardano, ripple, dogecoin, ...")
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
            "• /start - منوی اصلی\n"
            "• افزودن ارز → اسم انگلیسی ارز (مثل bitcoin)\n"
            "• بعد از اضافه کردن، می‌تونی بگی:\n"
            "   کف ۲۰۰۰\n"
            "   سقف ۳۰۰۰\n"
            "• هر ۳۰ دقیقه لیست قیمت میاد\n"
            "• وقتی قیمت به کف/سقف برسه، هشدار میدم"
        )

# دریافت پیام متنی
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.lower().strip()
    action = context.user_data.get('action')

    if action == 'add_coin':
        # لیست ارزهای پشتیبانی شده (کوین‌گکو)
        simple_names = {
            "bitcoin": "bitcoin", "btc": "bitcoin",
            "ethereum": "ethereum", "eth": "ethereum",
            "solana": "solana", "sol": "solana",
            "cardano": "cardano", "ada": "cardano",
            "ripple": "ripple", "xrp": "ripple",
            "dogecoin": "dogecoin", "doge": "dogecoin",
            "bnb": "binancecoin",
            "ton": "the-open-network", "toncoin": "the-open-network",
            "tron": "tron", "trx": "tron",
            "avax": "avalanche-2",
            "shiba": "shiba-inu", "shib": "shiba-inu",
            "pepe": "pepe",
            "link": "chainlink",
            "matic": "polygon", "pol": "polygon",
        }
        
        coin_id = simple_names.get(text)
        if not coin_id:
            await update.message.reply_text("ارز پیدا نشد! فقط ارزهای معروف پشتیبانی می‌شه.")
            return
        
        # چک کردن تعداد
        count = c.execute("SELECT COUNT(*) FROM coins WHERE user_id=?", (user_id,)).fetchone()[0]
        if count >= 20:
            await update.message.reply_text("حداکثر ۲۰ ارز می‌تونی داشته باشی!")
            return
        
        c.execute("INSERT OR IGNORE INTO coins (user_id, coin_id, coin_name) VALUES (?, ?, ?)",
                  (user_id, coin_id, text.capitalize()))
        conn.commit()
        await update.message.reply_text(f"{text.capitalize()} اضافه شد!\nحالا می‌تونی بگی:\nکف ۲۰۰۰\nسقف ۳۰۰۰")
        context.user_data['action'] = None
        context.user_data['waiting_for'] = text.capitalize()

    elif action == 'delete_coin':
        c.execute("DELETE FROM coins WHERE user_id=? AND coin_name=?", (user_id, text.capitalize()))
        conn.commit()
        await update.message.reply_text(f"{text.capitalize()} حذف شد!" if c.rowcount else "ارز پیدا نشد!")
        context.user_data['action'] = None

    elif text.startswith("کف ") or text.startswith("سقف "):
        try:
            price = float(text.split()[1])
            last_coin = context.user_data.get('waiting_for')
            if last_coin:
                if text.startswith("کف "):
                    c.execute("UPDATE coins SET floor=? WHERE user_id=? AND coin_name=?", (price, user_id, last_coin))
                else:
                    c.execute("UPDATE coins SET ceiling=? WHERE user_id=? AND coin_name=?", (price, user_id, last_coin))
                conn.commit()
                await update.message.reply_text(f"{text} برای {last_coin} ثبت شد!")
        except:
            await update.message.reply_text("فقط عدد بنویس! مثلاً: کف ۲۰۰۰")

# راه‌اندازی
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

       # هر ۳۰ دقیقه لیست قیمت
    crontab('*/1 * * * *', send_price_list)(app.job_queue)
    # هر ۵ دقیقه چک کردن آلارم
    crontab('*/5 * * * *', check_alerts)(app.job_queue)

    print("ربات در حال اجراست...")
    app.run_polling()

if __name__ == '__main__':
    main()
