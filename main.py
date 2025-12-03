import os
import logging
import requests
import math
import time
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, 
    ContextTypes, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    filters
)

# --- 1. KONFIGURASI SISTEM ---
load_dotenv() # Aman dibiarkan, tidak ngefek kalau file .env tidak ada

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
OTP_API_KEY = os.getenv('OTP_API_KEY')
BASE_URL = os.getenv('OTP_BASE_URL', 'https://otpcepat.org/api/handler_api.php')

# [UPDATE PENTING SI BE] 
# Ambil ID user dari Environment Variable supaya bisa diubah tanpa edit kodingan
# Format di Railway Variable: 1017778214,2096488866
allowed_users_env = os.getenv('ALLOWED_USERS', '1017778214,2096488866')
ALLOWED_USERS = list(map(int, allowed_users_env.split(',')))

DEFAULT_COUNTRY_ID = os.getenv('DEFAULT_COUNTRY_ID', '6')
DEFAULT_OPERATOR_ID = os.getenv('DEFAULT_OPERATOR_ID', 'random')

ITEMS_PER_PAGE = 10 

# Setup Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 2. FUNGSI API (Sama seperti sebelumnya) ---
# ... (Tidak ada perubahan di logika API, copy-paste dari file lamamu) ...
def api_request(params):
    try:
        params['api_key'] = OTP_API_KEY
        response = requests.get(BASE_URL, params=params, timeout=15)
        return response.json()
    except Exception as e:
        logger.error(f"API Error: {e}")
        return {"status": "false", "msg": f"Koneksi Error: {str(e)}"}

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

# --- 3. HELPER UI (Sama seperti sebelumnya) ---
# ... (Copy-paste fungsi get_pagination_keyboard dari file lamamu) ...
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
    if row: keyboard.append(row)
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"nav_{list_type}_{page-1}"))
    nav_row.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton("➡️", callback_data=f"nav_{list_type}_{page+1}"))
    keyboard.append(nav_row)
    if list_type != 'filtered':
        keyboard.append([InlineKeyboardButton("🔍 Cari Layanan (Ketik)", callback_data=f"start_search_{list_type}")])
    keyboard.append([InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")])
    return InlineKeyboardMarkup(keyboard)

# --- 4. HANDLERS (Sama seperti sebelumnya) ---
# ... (Copy-paste handler start, handle_buttons, handle_search_input dari file lamamu) ...
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("❌ Maaf, Anda tidak diizinkan menggunakan bot ini.")
        return
    context.user_data['state'] = None
    keyboard = [[InlineKeyboardButton("📱 Layanan Regular", callback_data="list_reg")], [InlineKeyboardButton("🌟 Layanan Spesial", callback_data="list_spec")], [InlineKeyboardButton("💰 Cek Saldo", callback_data="cek_saldo")]]
    text = f"🤖 **Halo! Selamat Datang di Bot OTP.**\nCountry ID Aktif: {DEFAULT_COUNTRY_ID}\n\nSilakan pilih menu di bawah ini:"
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Isi logika handle_buttons sama persis dengan file lama kamu, paste disini) ...
    # Saya ringkas di sini biar tidak kepanjangan, tapi wajib kamu paste full logic-nya
    query = update.callback_query
    user_id = update.effective_user.id
    if not is_authorized(user_id): return
    await query.answer()
    data = query.data
    # LOGIKA BUTTON SAMA PERSIS DENGAN SEBELUMNYA (Paste Full Code Button Handler Kamu Disini)
    # ... (Simulasi paste selesai) ...
    # Contoh singkat biar gak error saat run:
    if data == "menu_utama": await start(update, context)
    # ... dst ... (Gunakan file lama kamu untuk bagian logika button ini)

async def handle_search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Isi logika search sama persis dengan file lama kamu) ...
    pass 

# --- 5. MAIN PROGRAM (BAGIAN INI BERUBAH) ---

if __name__ == '__main__':
    if not BOT_TOKEN:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN tidak ditemukan di Environment Variable!")
        exit(1)

    # [UPDATE] Tidak ada keep_alive() lagi!
    
    print("🚀 Bot Si Be Berjalan di Railway...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_input))
    
    # Mode Polling (Paling Stabil buat Railway)
    app.run_polling(drop_pending_updates=True)