# main.py - ربات آلارم قیمت کریپتو با Binance API - نسخه حرفه‌ای و کامل
import logging
import sqlite3
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters, ConversationHandler
import aiohttp
from aiocron import crontab

# === وضعیت‌های Conversation ===
SELECT_COIN, SET_CEILING, SET_FLOOR = range(3)

# === تنظیمات ===
TOKEN = "7836143571:AAHkxNnb8e78LD01sP5BlohC9WQxT2DgcLs"  # توکن رباتت رو اینجا بذار
BINANCE_PRICE_API = "https://api.binance.com/api/v3/ticker/price"
BINANCE_TICKER_API = "https://api.binance.com/api/v3/exchangeInfo"

logging.basicConfig(level=logging.INFO)

# دیتابیس دائمی
conn = sqlite3.connect('/tmp/data.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS coins 
             (user_id INTEGER, coin_symbol TEXT, coin_name TEXT, floor REAL, ceiling REAL)''')
conn.commit()

# دریافت لیست تمام symbolهای Binance
async def get_binance_symbols():
    async with aiohttp.ClientSession() as session:
        async with session.get(BINANCE_TICKER_API) as resp:
            if resp.status == 200:
                data = await resp.json()
                symbols = {}
                for s in data['symbols']:
                    if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING':
                        base = s['baseAsset']
                        symbol = s['symbol']
                        symbols[base.lower()] = symbol
                        symbols[base] = symbol
                        symbols[s['symbol'].replace('USDT', '').lower()] = symbol
                return symbols
    return {}

# دریافت قیمت
async def get_prices(symbols):
    if not symbols:
        return {}
    params = {"symbols": f'["{\'", "\'".join(symbols)}"]'}
    async with aiohttp.ClientSession() as session:
        async with session.get(BINANCE_PRICE_API, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                prices = {item['symbol']: float(item['price']) for item in data}
                return prices
    return {}

# چک کردن هشدارها هر ۲ دقیقه
async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    rows = c.execute("SELECT user_id, coin_symbol, coin_name, floor, ceiling FROM coins WHERE floor IS NOT NULL OR ceiling IS NOT NULL").fetchall()
    if not rows:
        return
    symbols = list({row[1] for row in rows})
    prices = await get_prices(symbols)
    
    for user_id, symbol, name, floor, ceiling in rows:
        price = prices.get(symbol)
        if price is None:
            continue
        msg = None
        if floor and price <= floor:
            msg = f"هشدار کف قیمت!\n{name} به `${price:,}` رسید (کف: `${floor:,}`)"
        elif ceiling and price >= ceiling:
            msg = f"هشدار سقف قیمت!\n{name} به `${price:,}` رسید (سقف: `${ceiling:,}`)"
        if msg:
            try:
                await context.bot.send_message(chat_id=user_id, text=msg)
                c.execute("UPDATE coins SET floor=NULL, ceiling=NULL WHERE user_id=? AND coin_symbol=?", (user_id, symbol))
                conn.commit()
            except:
                pass

# منوی اصلی
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("افزودن ارز", callback_data="add_coin")],
        [InlineKeyboardButton("نمایش قیمت لحظه‌ای", callback_data="show_prices")],
        [InlineKeyboardButton("ثبت سقف و کف", callback_data="set_alert")],
        [InlineKeyboardButton("لیست ارزهای من", callback_data="my_coins")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "ربات آلارم قیمت کریپتو\n"
        "قیمت‌ها مستقیم از Binance\n"
        "هشدار سقف و کف با دقت بالا",
        reply_markup=reply_markup
    )

# دکمه‌ها
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "add_coin":
        await query.edit_message_text("اسم ارز رو بفرست (مثل BTC یا Bitcoin)")
        context.user_data['action'] = 'add_coin'
    
    elif query.data == "show_prices":
        coins = c.execute("SELECT coin_symbol, coin_name FROM coins WHERE user_id=?", (user_id,)).fetchall()
        if not coins:
            await query.edit_message_text("هنوز ارزی اضافه نکردی!")
            return
        symbols = [row[0] for row in coins]
        prices = await get_prices(symbols)
        text = "قیمت لحظه‌ای ارزها (از Binance):\n\n"
        for symbol, name in coins:
            price = prices.get(symbol, "خطا")
            text += f"• {name}: `${price:,}`\n" if price != "خطا" else f"• {name}: خطا\n"
        await query.edit_message_text(text)
    
    elif query.data == "my_coins":
        coins = c.execute("SELECT coin_name, floor, ceiling FROM coins WHERE user_id=?", (user_id,)).fetchall()
        if not coins:
            await query.edit_message_text("لیست خالیه!")
            return
        text = "ارزهای تو:\n\n"
        for name, floor, ceiling in coins:
            f = f" | کف: ${floor:,}" if floor else ""
            c = f" | سقف: ${ceiling:,}" if ceiling else ""
            text += f"• {name}{f}{c}\n"
        await query.edit_message_text(text)
    
    elif query.data == "set_alert":
        coins = c.execute("SELECT coin_name, coin_symbol FROM coins WHERE user_id=?", (user_id,)).fetchall()
        if not coins:
            await query.edit_message_text("اول ارز اضافه کن!")
            return
        keyboard = [[InlineKeyboardButton(name, callback_data=f"select_coin_{symbol}")] for name, symbol in coins]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("ارز مورد نظر رو انتخاب کن:", reply_markup=reply_markup)

    elif query.data.startswith("select_coin_"):
        symbol = query.data.split("_", 2)[2]
        name = next((row[0] for row in c.execute("SELECT coin_name FROM coins WHERE user_id=? AND coin_symbol=?", (user_id, symbol))), symbol)
        context.user_data['selected_symbol'] = symbol
        context.user_data['selected_name'] = name
        await query.edit_message_text(f"ارز: {name}\n\nقیمت سقف رو بفرست (یا /skip):")
        return SET_CEILING

# افزودن ارز
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    action = context.user_data.get('action')

    if action == 'add_coin':
        symbols = await get_binance_symbols()
        symbol = symbols.get(text.lower())
        if not symbol:
            await update.message.reply_text("این ارز در Binance موجود نیست!\nمثال: BTC, ETH, SOL, BNB")
            return
        
        count = c.execute("SELECT COUNT(*) FROM coins WHERE user_id=?", (user_id,)).fetchone()[0]
        if count >= 20:
            await update.message.reply_text("حداکثر ۲۰ ارز!")
            return
        
        name = text.upper()
        c.execute("INSERT OR IGNORE INTO coins (user_id, coin_symbol, coin_name) VALUES (?, ?, ?)", (user_id, symbol, name))
        conn.commit()
        await update.message.reply_text(f"{name} با موفقیت اضافه شد!")
        context.user_data['action'] = None

# Conversation برای سقف و کف
async def set_ceiling(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "/skip":
        await update.message.reply_text("قیمت سقف رد شد.\nحالا قیمت کف رو بفرست (یا /skip):")
        return SET_FLOOR
    
    try:
        ceiling = float(text.replace(',', ''))
        symbol = context.user_data['selected_symbol']
        c.execute("UPDATE coins SET ceiling=? WHERE user_id=? AND coin_symbol=?", (ceiling, update.message.from_user.id, symbol))
        conn.commit()
        await update.message.reply_text(f"سقف `${ceiling:,}` ثبت شد.\nحالا قیمت کف رو بفرست (یا /skip):")
        return SET_FLOOR
    except:
        await update.message.reply_text("عدد معتبر بنویس! مثال: 70000")

async def set_floor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    symbol = context.user_data['selected_symbol']
    name = context.user_data['selected_name']
    
    if text != "/skip":
        try:
            floor = float(text.replace(',', ''))
            c.execute("UPDATE coins SET floor=? WHERE user_id=? AND coin_symbol=?", (floor, update.message.from_user.id, symbol))
            conn.commit()
            await update.message.reply_text(f"کف `${floor:,}` برای {name} ثبت شد!\nهشدار فعال شد.")
        except:
            await update.message.reply_text("عدد معتبر بنویس!")
    else:
        await update.message.reply_text(f"تنظیمات برای {name} ذخیره شد.")
    
    await start(update, context)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.")
    await start(update, context)
    return ConversationHandler.END

def main():
    app = Application.builder().token(TOKEN).build()

    # منوی اصلی
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))

    # افزودن ارز
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # تنظیم سقف و کف
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button)],
        states={
            SET_CEILING: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_ceiling)],
            SET_FLOOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_floor)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)

    # چک کردن هشدارها هر ۲ دقیقه
    crontab('*/2 * * * *', check_alerts)(app.job_queue)

    print("ربات حرفه‌ای با Binance API فعال شد...")
    app.run_polling()

if __name__ == '__main__':
    main()
