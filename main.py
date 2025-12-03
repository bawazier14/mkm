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
# Di Railway, kita ambil semua dari Environment Variable
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
OTP_API_KEY = os.environ.get('OTP_API_KEY')
BASE_URL = os.environ.get('OTP_BASE_URL', 'https://otpcepat.org/api/handler_api.php')

# Parsing Allowed Users (Mencegah error jika env kosong)
allowed_users_env = os.environ.get('ALLOWED_USERS', '1017778214,2096488866')
try:
    ALLOWED_USERS = list(map(int, allowed_users_env.split(',')))
except ValueError:
    ALLOWED_USERS = []

DEFAULT_COUNTRY_ID = os.environ.get('DEFAULT_COUNTRY_ID', '6')
DEFAULT_OPERATOR_ID = os.environ.get('DEFAULT_OPERATOR_ID', 'random')
ITEMS_PER_PAGE = 10 

# Setup Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- FUNGSI API (BACKEND) ---

def api_request(params):
    """Wrapper untuk memanggil API dengan retry mechanism"""
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            params['api_key'] = OTP_API_KEY
            response = requests.get(BASE_URL, params=params, timeout=20)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout attempt {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
        except Exception as e:
            logger.error(f"API Error: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                return {"status": "false", "msg": f"Error: {str(e)}"}
    
    return {"status": "false", "msg": "Gagal koneksi ke server OTP."}

def check_api_success(response):
    status = response.get('status')
    return status is True or str(status).lower() == 'true'

def fetch_services(type='regular'):
    action = 'getServices' if type == 'regular' else 'getSpecialServices'
    params = {'action': action}
    if type == 'regular':
        params['country_id'] = DEFAULT_COUNTRY_ID

    data = api_request(params)
    if check_api_success(data):
        return data.get('data', [])
    return []

def order_number(service_id):
    return api_request({
        'action': 'get_order',
        'service_id': service_id,
        'operator_id': DEFAULT_OPERATOR_ID,
        'country_id': DEFAULT_COUNTRY_ID
    })

def check_order_sms(order_id):
    return api_request({'action': 'get_status', 'order_id': order_id})

def update_order_status(order_id, status_code):
    return api_request({'action': 'set_status', 'order_id': order_id, 'status': status_code})

def get_balance():
    return api_request({'action': 'getBalance'})

def is_authorized(user_id):
    return user_id in ALLOWED_USERS

# --- HELPER UI ---

def get_pagination_keyboard(services, page, list_type):
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
        btn_text = f"{name} ({price})"
        row.append(InlineKeyboardButton(btn_text, callback_data=f"buy_{sid}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: 
        keyboard.append(row)
        
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"nav_{list_type}_{page-1}"))
    
    nav_row.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"nav_{list_type}_{page+1}"))
        
    keyboard.append(nav_row)
    
    if list_type != 'filtered':
        keyboard.append([InlineKeyboardButton("🔍 Cari Layanan (Ketik)", callback_data=f"start_search_{list_type}")])
    
    keyboard.append([InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")])
    return InlineKeyboardMarkup(keyboard)

# --- HANDLERS ---
# (Bagian handler ini sama persis, logika bot tidak berubah)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception: {context.error}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("❌ Maaf, Anda tidak diizinkan.")
        return

    context.user_data['state'] = None
    keyboard = [
        [InlineKeyboardButton("📱 Layanan Regular", callback_data="list_reg")],
        [InlineKeyboardButton("🌟 Layanan Spesial", callback_data="list_spec")],
        [InlineKeyboardButton("💰 Cek Saldo", callback_data="cek_saldo")]
    ]
    text = f"🤖 **Halo! Selamat Datang.**\nCountry ID: {DEFAULT_COUNTRY_ID}\nSilakan pilih menu:"
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await query.answer("❌ Ditolak.", show_alert=True)
        return

    await query.answer()
    data = query.data
    
    # --- LOGIKA TOMBOL (Versi Ringkas tapi Lengkap) ---
    if data == "menu_utama":
        await start(update, context)
    
    elif data in ["list_reg", "list_spec"]:
        list_type = 'regular' if data == "list_reg" else 'special'
        short_code = 'reg' if data == "list_reg" else 'spec'
        await query.edit_message_text("🔄 Mengambil data...")
        services = fetch_services(list_type)
        if not services:
            await query.edit_message_text("❌ Data kosong.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu_utama")]]))
            return
        context.user_data[f'services_{short_code}'] = services
        markup = get_pagination_keyboard(services, 0, short_code)
        await query.edit_message_text(f"📋 **Layanan ({list_type.title()}):**", reply_markup=markup, parse_mode='Markdown')

    elif data.startswith("nav_"):
        _, type_code, page_num = data.split("_")
        page = int(page_num)
        services = context.user_data.get(f'services_{type_code}')
        if services:
            markup = get_pagination_keyboard(services, page, type_code)
            try: await query.edit_message_text(f"📋 **Daftar Layanan:**", reply_markup=markup, parse_mode='Markdown')
            except: pass
        else:
            await query.edit_message_text("⚠️ Sesi habis.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu_utama")]]))

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
            txt = f"✅ **Order Berhasil!**\n📱 `{d.get('number')}`\n🆔 `{d.get('order_id')}`\n💰 {d.get('price')}"
            kb = [[InlineKeyboardButton("🔄 Cek SMS", callback_data=f"chk_{d.get('order_id')}")], [InlineKeyboardButton("✅ Selesai", callback_data=f"fin_{d.get('order_id')}"), InlineKeyboardButton("🚫 Batal", callback_data=f"cncl_{d.get('order_id')}")]]
            await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        else:
            await query.edit_message_text(f"❌ Gagal: {resp.get('msg')}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu_utama")]]))

    elif data.startswith("chk_"):
        oid = data.split("_")[1]
        resp = check_order_sms(oid)
        if check_api_success(resp):
            d = resp.get('data', {})
            sms = d.get('sms')
            status = d.get('status', 'Unknown')
            if sms: msg = f"📩 **SMS MASUK!**\n`{sms}`"
            elif status == 'Recieved': msg = "📩 SMS DITERIMA! Cek aplikasi."
            else: msg = f"⏳ Status: {status}\nBelum ada SMS."
        else: msg = f"⚠️ Error: {resp.get('msg')}"
        kb = [[InlineKeyboardButton("🔄 Cek Lagi", callback_data=f"chk_{oid}")], [InlineKeyboardButton("✅ Selesai", callback_data=f"fin_{oid}"), InlineKeyboardButton("🚫 Batal", callback_data=f"cncl_{oid}")]]
        try: await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        except: pass

    elif data.startswith("fin_") or data.startswith("cncl_"):
        action, oid = data.split("_")
        code = 4 if action == "fin" else 2
        await query.edit_message_text("🔄 Updating...")
        update_order_status(oid, code)
        await query.edit_message_text("✅ Transaksi Selesai." if action == "fin" else "🚫 Dibatalkan.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu_utama")]]))

    elif data == "cek_saldo":
        res = get_balance()
        if check_api_success(res):
            saldo = res['data']['saldo']
            email = res['data']['email']
            await query.edit_message_text(f"👤 Akun: {email}\n💰 Saldo: **Rp {saldo}**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu_utama")]]))
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

# --- MAIN (RAILWAY READY) ---

def main():
    if not BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN tidak ditemukan! Cek Variables Railway.")
        exit(1)
    
    if not OTP_API_KEY:
        logger.error("❌ OTP_API_KEY tidak ditemukan! Cek Variables Railway.")
        exit(1)

    logger.info("🚀 Starting Bot on Railway (Polling Mode)...")
    logger.info(f"📊 Allowed Users Count: {len(ALLOWED_USERS)}")

    # Build Application
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_input))
    app.add_error_handler(error_handler)
    
    logger.info("✅ Bot Started! Waiting for updates...")
    
    # Run Polling (Mode Paling Stabil untuk Railway Worker)
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()

