import os
import logging
import requests
import math
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, 
    ContextTypes, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    filters
)

# --- KONFIGURASI SISTEM ---
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
OTP_API_KEY = os.environ.get('OTP_API_KEY')
BASE_URL = os.environ.get('OTP_BASE_URL', 'https://otpcepat.org/api/handler_api.php')

allowed_users_env = os.environ.get('ALLOWED_USERS', '1017778214,2096488866')
try:
    ALLOWED_USERS = list(map(int, allowed_users_env.split(',')))
except ValueError:
    ALLOWED_USERS = []

DEFAULT_COUNTRY_ID = os.environ.get('DEFAULT_COUNTRY_ID', '6')
DEFAULT_OPERATOR_ID = os.environ.get('DEFAULT_OPERATOR_ID', 'random')
ITEMS_PER_PAGE = 10 

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- FUNGSI API (BACKEND) ---
def api_request(params):
    try:
        params['api_key'] = OTP_API_KEY
        response = requests.get(BASE_URL, params=params, timeout=20)
        return response.json()
    except Exception as e:
        logger.error(f"API Error: {e}")
        return {"status": "false", "msg": "API Error"}

def check_api_success(response):
    status = response.get('status')
    return status is True or str(status).lower() == 'true'

def fetch_services(type='regular'):
    action = 'getServices' if type == 'regular' else 'getSpecialServices'
    params = {'action': action}
    if type == 'regular': params['country_id'] = DEFAULT_COUNTRY_ID
    data = api_request(params)
    return data.get('data', []) if check_api_success(data) else []

def order_number(service_id):
    return api_request({'action': 'get_order', 'service_id': service_id, 'operator_id': DEFAULT_OPERATOR_ID, 'country_id': DEFAULT_COUNTRY_ID})

def check_order_sms(order_id):
    return api_request({'action': 'get_status', 'order_id': order_id})

def update_order_status(order_id, status_code):
    return api_request({'action': 'set_status', 'order_id': order_id, 'status': status_code})

def get_balance():
    return api_request({'action': 'getBalance'})

def is_authorized(user_id):
    return user_id in ALLOWED_USERS

# --- JOB QUEUE (AUTO CHECKER) ---
async def auto_check_sms_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    order_id = job.data['order_id']
    chat_id = job.data['chat_id']
    
    resp = check_order_sms(order_id)
    
    if check_api_success(resp):
        d = resp.get('data', {})
        sms = d.get('sms')
        status = d.get('status')
        
        if sms:
            logger.info(f"SMS Diterima untuk Order {order_id}")
            text_sms = f"📩 **SMS MASUK!** (ID: {order_id})\n\n`{sms}`\n\nSilakan gunakan kode tersebut."
            kb = [[InlineKeyboardButton("✅ Selesai", callback_data=f"fin_{order_id}"), InlineKeyboardButton("🚫 Batalkan", callback_data=f"cncl_{order_id}")]]
            await context.bot.send_message(chat_id=chat_id, text=text_sms, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
            job.schedule_removal()
        elif status == 'Canceled' or status == 'Refunded':
            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Order {order_id} dibatalkan oleh sistem/timeout.")
            job.schedule_removal()
    else:
        pass

def stop_auto_check(context, order_id):
    current_jobs = context.job_queue.get_jobs_by_name(str(order_id))
    for job in current_jobs:
        job.schedule_removal()

# --- HELPER UI ---
def get_pagination_keyboard(services, page, list_type):
    import math
    total_items = len(services)
    total_pages = math.ceil(total_items / ITEMS_PER_PAGE)
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    current_items = services[start:end]
    keyboard = []
    row = []
    for item in current_items:
        name = item['serviceName'][:20]
        price = item['price']
        sid = item['serviceID']
        row.append(InlineKeyboardButton(f"{name} ({price})", callback_data=f"buy_{sid}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"nav_{list_type}_{page-1}"))
    nav_row.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton("➡️", callback_data=f"nav_{list_type}_{page+1}"))
    keyboard.append(nav_row)
    if list_type != 'filtered':
        keyboard.append([InlineKeyboardButton("🔍 Cari", callback_data=f"start_search_{list_type}")])
    keyboard.append([InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")])
    return InlineKeyboardMarkup(keyboard)

# --- HANDLERS ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"App Error: {context.error}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Cek Auth
    if not is_authorized(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("❌ Maaf, Anda tidak diizinkan.")
        return

    context.user_data['state'] = None
    
    keyboard = [
        [InlineKeyboardButton("📱 Layanan Regular", callback_data="list_reg")],
        [InlineKeyboardButton("🌟 Layanan Spesial", callback_data="list_spec")],
        [InlineKeyboardButton("💰 Cek Saldo", callback_data="cek_saldo")]
    ]
    
    text = (
        "🤖 **Halo! Selamat Datang di Bot OTP.**\n"
        f"Country ID Aktif: {DEFAULT_COUNTRY_ID}\n\n"
        "Silakan pilih menu di bawah ini:"
    )
    
    # --- LOGIKA PINTAR: DETEKSI TOMBOL VS KETIKAN ---
    if update.callback_query:
        # Jika dipanggil dari tombol (misal: "Kembali"), EDIT pesan
        try:
            await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        except Exception:
            pass 
    elif update.message:
        # Jika dipanggil dari ketikan /start, KIRIM pesan baru
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not is_authorized(user_id):
        await query.answer("Ditolak.", show_alert=True)
        return
    await query.answer()
    data = query.data
    
    if data == "menu_utama":
        await start(update, context)
    
    elif data in ["list_reg", "list_spec"]:
        sc = 'reg' if data == "list_reg" else 'spec'
        lt = 'regular' if data == "list_reg" else 'special'
        await query.edit_message_text("🔄 Loading...")
        srv = fetch_services(lt)
        context.user_data[f'services_{sc}'] = srv
        await query.edit_message_text(f"📋 **{lt.title()}**", reply_markup=get_pagination_keyboard(srv, 0, sc), parse_mode='Markdown')

    elif data.startswith("nav_"):
        _, t, p = data.split("_")
        await query.edit_message_text("📋 List:", reply_markup=get_pagination_keyboard(context.user_data.get(f'services_{t}'), int(p), t), parse_mode='Markdown')

    elif data.startswith("start_search_"):
        target_type = data.split("_")[2]
        context.user_data['state'] = 'SEARCHING'
        context.user_data['search_target'] = target_type
        await query.edit_message_text(f"🔍 **Cari Layanan ({target_type.upper()})**\nKetik nama layanan:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Batal", callback_data=f"list_{target_type}")]]) )

    elif data.startswith("buy_"):
        sid = data.split("_")[1]
        await query.edit_message_text(f"🔄 Order ID {sid}...")
        resp = order_number(sid)
        if check_api_success(resp):
            d = resp.get('data', {})
            order_id = d.get('order_id')
            txt = (f"✅ **Order Berhasil!**\n📱 `{d.get('number')}`\n🆔 `{order_id}`\n💰 {d.get('price')}\n\n"
                   f"⏳ **Menunggu SMS Otomatis...**\nBot akan mengecek setiap 5 detik.")
            kb = [[InlineKeyboardButton("🔄 Cek Manual", callback_data=f"chk_{order_id}")], 
                  [InlineKeyboardButton("✅ Selesai", callback_data=f"fin_{order_id}"), InlineKeyboardButton("🚫 Batal", callback_data=f"cncl_{order_id}")]]
            await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
            
            # Start Auto Check Job
            context.job_queue.run_repeating(auto_check_sms_job, interval=5, first=2, data={'order_id': order_id, 'chat_id': chat_id}, name=str(order_id))
        else:
            await query.edit_message_text(f"❌ Gagal: {resp.get('msg')}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu_utama")]]))

    elif data.startswith("chk_"):
        oid = data.split("_")[1]
        resp = check_order_sms(oid)
        if check_api_success(resp):
            d = resp.get('data', {})
            sms = d.get('sms')
            status = d.get('status', 'Unknown')
            if sms: 
                msg = f"📩 **SMS MASUK!**\n`{sms}`"
                stop_auto_check(context, oid)
            else: 
                msg = f"⏳ Status: {status}\nBelum ada SMS (Auto-check aktif)."
        else: msg = f"⚠️ Error: {resp.get('msg')}"
        kb = [[InlineKeyboardButton("🔄 Cek Lagi", callback_data=f"chk_{oid}")], [InlineKeyboardButton("✅ Selesai", callback_data=f"fin_{oid}"), InlineKeyboardButton("🚫 Batal", callback_data=f"cncl_{oid}")]]
        try: await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        except: pass

    elif data.startswith("fin_") or data.startswith("cncl_"):
        action, oid = data.split("_")
        stop_auto_check(context, oid)
        code = 4 if action == "fin" else 2
        await query.edit_message_text("🔄 Updating...")
        update_order_status(oid, code)
        await query.edit_message_text("✅ Transaksi Selesai." if action == "fin" else "🚫 Dibatalkan.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu_utama")]]))

    elif data == "cek_saldo":
        await query.edit_message_text("🔄 Mengambil info akun...")
        res = get_balance()
        if check_api_success(res):
            data_saldo = res.get('data', {})
            saldo = data_saldo.get('saldo', '0')
            email = data_saldo.get('email', 'Tidak ada email')
            text_info = f"👤 **Info Akun**\n📧 Email: `{email}`\n💰 Saldo: **Rp {saldo}**"
            await query.edit_message_text(text_info, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu_utama")]]))
        else:
            await query.edit_message_text(f"❌ Gagal: {res.get('msg')}")

    elif data == "noop": pass

async def handle_search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') == 'SEARCHING':
        key = update.message.text.lower()
        target = context.user_data.get('search_target')
        services = context.user_data.get(f'services_{target}', [])
        filtered = [s for s in services if key in s['serviceName'].lower()]
        if filtered:
            context.user_data['services_filtered'] = filtered
            markup = get_pagination_keyboard(filtered, 0, 'filtered')
            await update.message.reply_text(f"🔎 Hasil: {len(filtered)} layanan", reply_markup=markup)
        else:
            await update.message.reply_text("❌ Tidak ditemukan.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Kembali", callback_data=f"list_{target}")]]))
    else:
        await update.message.reply_text("Ketik /start untuk menu.")

# --- MAIN ---
def main():
    if not BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN tidak ditemukan!")
        exit(1)
    
    if not OTP_API_KEY:
        logger.error("❌ OTP_API_KEY tidak ditemukan!")
        exit(1)

    logger.info("🚀 Starting Bot on Railway (Polling Mode)...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_input))
    app.add_error_handler(error_handler)
    
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
