#!/usr/bin/env python3
"""
DARk Aadhar PDF Tool - Telegram Bot
Developer: @vikash1178
"""

import os
import sys
import json
import base64
import io
import uuid
import asyncio
import requests
import pikepdf
import logging
import hashlib
import time
from typing import Tuple, Optional
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

_SESSION_TTL = 600
_OWNER_ID = 8575605469  # Owner's Telegram ID
_CREDITS_FILE = "user_credits.json"
_DEFAULT_CREDITS = 0
_CREDIT_COST = 1  # Credits per Aadhaar download
_OWNER_UNLIMITED = True  # Owner gets unlimited credits

_BASE_1 = "https://tathya"
_BASE_2 = ".uidai.gov"
_BASE_3 = ".in"

_BASE = f"{_BASE_1}{_BASE_2}{_BASE_3}"

_EP1 = f"{_BASE}/retrieveEidUid/ext/v1/generic/retrieveuideid"
_EP2 = f"{_BASE}/audioCaptchaService/api/captcha/v3/generation"
_EP3 = f"{_BASE}/unifiedAppAuthService/api/v2/generate/aadhaar/otp"
_EP4 = f"{_BASE}/downloadAadhaarService/api/aadhaar/download"

_SESSIONS = {}

# ============================================================
# FULL HEADERS
# ============================================================
_H = {
    "accept": "application/json, text/plain, */*",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en_IN,en-US;q=0.9,en;q=0.8",
    "appid": "MYAADHAAR",
    "content-type": "application/json",
    "origin": "https://myaadhaar.uidai.gov.in",
    "referer": "https://myaadhaar.uidai.gov.in/",
    "sec-ch-ua": '"Chromium";v="150", "Google Chrome";v="150", "Not;A=Brand";v="8"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "connection": "keep-alive"
}

# ============================================================
# AES KEY PARTS
# ============================================================
_CACHE_SEED = "6a6e69686275"
_LOG_FMT_ID = "4354524248"
_REQ_PREFIX = "556e6a"
_SESSION_SALT = "6946"

_API_VER = "yJyjNJ3p"
_DBG_TRACE = "tJg9MmgU0A61I"
_CONTENT_HASH = "fdDwvQ3xYi6H2S0P9Kdnpg=="
_SIG_FRAG = "OKxgLvdvNjZ"
_RETRY_CTR = "shnifz/vMiG"

# ============================================================
# SECURE TOKEN MANAGEMENT
# ============================================================

def get_token():
    """Get bot token securely from environment variables"""
    
    # Check environment variables (Railway, Heroku, etc.)
    token = os.environ.get("BOT_TOKEN")
    
    if token and ":" in token:
        print("✅ Bot token loaded from environment")
        # Don't log the full token!
        masked = token[:10] + "..." + token[-5:]
        print(f"📝 Token: {masked}")
        return token
    
    # Check .env file for local development
    if os.path.exists(".env"):
        try:
            with open(".env", "r") as f:
                for line in f:
                    if line.startswith("BOT_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        if token and ":" in token:
                            print("✅ Bot token loaded from .env file")
                            masked = token[:10] + "..." + token[-5:]
                            print(f"📝 Token: {masked}")
                            return token
        except:
            pass
    
    # If no token found
    print("\n" + "="*50)
    print("❌ BOT_TOKEN NOT FOUND!")
    print("="*50)
    print("\nPlease set your bot token in one of these ways:")
    print("1. Railway: Add BOT_TOKEN in Environment Variables")
    print("2. Local: Create .env file with BOT_TOKEN=your_token")
    print("3. Heroku: Set BOT_TOKEN config variable")
    print("\nExample .env file:")
    print("BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz")
    print("\n" + "="*50)
    sys.exit(1)

def load_token():
    """Load token securely"""
    return get_token()

# ============================================================
# CREDIT MANAGEMENT SYSTEM
# ============================================================

def load_credits() -> dict:
    """Load user credits from file"""
    if os.path.exists(_CREDITS_FILE):
        try:
            with open(_CREDITS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_credits(credits_data: dict):
    """Save user credits to file"""
    try:
        with open(_CREDITS_FILE, 'w') as f:
            json.dump(credits_data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save credits: {e}")

def get_user_credits(user_id: int) -> int:
    """Get credits for a user - Owner gets unlimited"""
    if is_owner(user_id) and _OWNER_UNLIMITED:
        return 999999  # Unlimited for owner
    credits = load_credits()
    return credits.get(str(user_id), _DEFAULT_CREDITS)

def add_user_credits(user_id: int, amount: int) -> int:
    """Add credits to a user"""
    credits = load_credits()
    user_id_str = str(user_id)
    current = credits.get(user_id_str, _DEFAULT_CREDITS)
    new_balance = current + amount
    credits[user_id_str] = new_balance
    save_credits(credits)
    return new_balance

def deduct_user_credits(user_id: int, amount: int = _CREDIT_COST) -> bool:
    """Deduct credits from a user - Owner doesn't need credits"""
    if is_owner(user_id) and _OWNER_UNLIMITED:
        return True  # Owner has unlimited credits
    
    credits = load_credits()
    user_id_str = str(user_id)
    current = credits.get(user_id_str, _DEFAULT_CREDITS)
    
    if current >= amount:
        credits[user_id_str] = current - amount
        save_credits(credits)
        return True
    return False

def is_owner(user_id: int) -> bool:
    """Check if user is the owner"""
    return str(user_id) == str(_OWNER_ID)

# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def _fmt_time():
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")

def _clean_temp():
    import glob
    for f in glob.glob("captcha*.png"):
        try: os.remove(f)
        except: pass

def _validate_number(num: str, length: int = 10) -> bool:
    return num.isdigit() and len(num) == length

def _rebuild_cache_prefix() -> str:
    _p1 = bytes.fromhex(_CACHE_SEED).decode()
    _p2 = bytes.fromhex(_LOG_FMT_ID).decode()
    _p3 = bytes.fromhex(_REQ_PREFIX).decode()
    _p4 = bytes.fromhex(_SESSION_SALT).decode()
    return f"{_p1}{_p2}{_p3}{_p4}"

def _rebuild_content_checksum() -> str:
    _c1 = _API_VER
    _c2 = _DBG_TRACE
    _c3 = _CONTENT_HASH
    _c4 = _SIG_FRAG
    _c5 = _RETRY_CTR
    return f"{_c1}{_c2}{_c3}{_c4}{_c5}"

def _aes_decrypt(encrypted_b64: str, key: str) -> str:
    try:
        aes_key = hashlib.md5(key.encode()).digest()
        raw = base64.b64decode(encrypted_b64)
        iv = raw[:16]
        ciphertext = raw[16:]
        cipher = AES.new(aes_key, AES.MODE_CBC, iv)
        decrypted = unpad(cipher.decrypt(ciphertext), AES.block_size)
        return decrypted.decode()
    except Exception as e:
        logger.error(f"Decryption error: {e}")
        return ""

def _get_credit_text() -> str:
    _key = _rebuild_cache_prefix()
    _enc = _rebuild_content_checksum()
    _credit = _aes_decrypt(_enc, _key)
    if not _credit or len(_credit) < 3:
        return "Tool by @vikash1178"
    return _credit

# ============================================================
# API FUNCTIONS
# ============================================================

def _get_captcha(session: requests.Session) -> Tuple[Optional[bytes], Optional[str]]:
    """Generate captcha image from UIDAI"""
    try:
        payload = {
            "captchaLength": "6",
            "captchaType": "2",
            "audioCaptchaRequired": True
        }
        r = session.post(
            _EP2,
            headers=_H,
            json=payload,
            timeout=15
        )
        logger.info(f"Captcha response status: {r.status_code}")
        
        d = r.json()
        logger.info(f"Captcha response keys: {list(d.keys())}")
        
        if d.get("imageBase64") and d.get("transactionId"):
            return base64.b64decode(d["imageBase64"]), d["transactionId"]
        else:
            logger.error(f"Captcha response missing data: {d}")
    except Exception as e:
        logger.error(f"Captcha error: {e}")
        import traceback
        traceback.print_exc()
    return None, None

def _get_captcha_with_retry(session: requests.Session, max_retries: int = 3) -> Tuple[Optional[bytes], Optional[str]]:
    """Get captcha with retry logic"""
    for attempt in range(max_retries):
        logger.info(f"Getting captcha attempt {attempt + 1}/{max_retries}")
        img_bytes, txn = _get_captcha(session)
        if img_bytes and txn:
            return img_bytes, txn
        time.sleep(1)
    return None, None

def _api_call(session, url, payload, label="API"):
    """Make API request to UIDAI endpoint"""
    try:
        logger.info(f"{label} Request: {json.dumps(payload)}")
        r = session.post(
            url,
            headers=_H,
            json=payload,
            timeout=15
        )
        logger.info(f"{label} Response status: {r.status_code}")
        
        result = r.json()
        logger.info(f"{label} Response: {json.dumps(result)[:500]}")
        
        return result, None
    except Exception as e:
        logger.error(f"{label} Error: {e}")
        import traceback
        traceback.print_exc()
        return None, str(e)

def _unlock_pdf(pdf_bytes: bytes, name: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Attempt to unlock Aadhaar PDF with name+birthyear pattern"""
    if not pdf_bytes or pdf_bytes[:4] != b'%PDF':
        return None, None
    prefix = ' '.join(name.split()).upper()[:4] if name else "MR"
    prefix = prefix.ljust(4, 'X')
    for y in range(1950, 2016):
        try:
            p = pikepdf.open(io.BytesIO(pdf_bytes), password=f"{prefix}{y}")
            o = io.BytesIO()
            p.save(o)
            p.close()
            return o.getvalue(), f"{prefix}{y}"
        except pikepdf.PasswordError:
            continue
        except:
            continue
    return None, None

# ============================================================
# TELEGRAM BOT SETUP
# ============================================================

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, filters, ContextTypes, CallbackQueryHandler

(NAME, MOBILE, CAP1, OTP1, CAP2, OTP2) = range(6)

BOT_TOKEN = None

class UserSession:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(_H)
        self.name = None
        self.mobile = None
        self.eid = None
        self.full_name = None
        self.cap1_txn = None
        self.cap1_text = None
        self.otp1_txn = None
        self.cap2_txn = None
        self.cap2_text = None
        self.otp2_txn = None
        self.captcha_attempts = 0

# ============================================================
# KEYBOARD HELPERS
# ============================================================

def get_stop_keyboard():
    """Create keyboard with stop button"""
    keyboard = [
        [InlineKeyboardButton("❌ Stop / Cancel", callback_data="stop")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def stop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle stop button press"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id in _SESSIONS:
        del _SESSIONS[user_id]
    
    await query.edit_message_text(
        "❌ *Process Stopped*\n\n"
        "You have cancelled the operation.\n"
        "Send /start to begin again.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ============================================================
# OWNER COMMANDS
# ============================================================

async def owner_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all owner commands"""
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await update.message.reply_text(
            f"❌ You are not authorized to use this command.\n"
            f"Your ID: `{user_id}`",
            parse_mode="Markdown"
        )
        return
    
    help_text = """
👑 *OWNER COMMANDS*
Developer: @vikash1178

📋 *Available Commands:*

1️⃣ `/owner` - Open Owner Panel
   Interactive menu with all options

2️⃣ `/addcredits <user_id> <amount>`
   Add credits to a user
   Example: `/addcredits 123456789 10`

3️⃣ `/removecredits <user_id> <amount>`
   Remove credits from a user
   Example: `/removecredits 123456789 5`

4️⃣ `/checkcredits <user_id>`
   Check any user's credits
   Example: `/checkcredits 123456789`

5️⃣ `/listusers` - List all users with credits
   Shows top 20 users

6️⃣ `/totalcredits` - Total credits summary
   Shows total users and credits

7️⃣ `/resetcredits <user_id>`
   Reset a user's credits to 0
   Example: `/resetcredits 123456789`

8️⃣ `/giveall <amount>`
   Give credits to ALL users
   Example: `/giveall 5`

9️⃣ `/mycredits` - Check your own credits
   Shows ♾️ UNLIMITED for owner

🔟 `/start` - Start the tool
   Owner gets free access

📊 *Owner Benefits:*
• ♾️ UNLIMITED credits
• 🆓 FREE downloads
• 👑 Full control over user credits

💡 *Quick Tips:*
• User IDs are Telegram IDs (numbers)
• Credits are stored in user_credits.json
• Each download costs 1 credit for users
"""
    
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner panel with all commands"""
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await update.message.reply_text(
            f"❌ You are not authorized to use this command.\n"
            f"Your ID: `{user_id}`",
            parse_mode="Markdown"
        )
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Credits", callback_data="owner_add")],
        [InlineKeyboardButton("➖ Remove Credits", callback_data="owner_remove")],
        [InlineKeyboardButton("📊 Check Credits", callback_data="owner_check")],
        [InlineKeyboardButton("📋 List Users", callback_data="owner_list")],
        [InlineKeyboardButton("💰 Total Credits", callback_data="owner_total")],
        [InlineKeyboardButton("🔄 Reset Credits", callback_data="owner_reset")],
        [InlineKeyboardButton("🎁 Give All", callback_data="owner_giveall")],
        [InlineKeyboardButton("❌ Close Panel", callback_data="owner_close")]
    ]
    
    await update.message.reply_text(
        "👑 *Owner Panel*\n"
        "Developer: @vikash1178\n"
        f"👑 You have ♾️ UNLIMITED credits!\n\n"
        "Select an option:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def owner_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle owner panel callbacks"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await query.edit_message_text(
            f"❌ You are not authorized.\n"
            f"Your ID: `{user_id}`",
            parse_mode="Markdown"
        )
        return
    
    data = query.data
    
    if data == "owner_close":
        await query.edit_message_text("👑 *Owner Panel Closed*", parse_mode="Markdown")
        return
    
    elif data == "owner_add":
        await query.edit_message_text(
            "➕ *Add Credits*\n\n"
            "Send the command in this format:\n"
            "`/addcredits <user_id> <amount>`\n\n"
            "Example:\n"
            "`/addcredits 123456789 10`\n\n"
            "This will add 10 credits to user 123456789",
            parse_mode="Markdown"
        )
        return
    
    elif data == "owner_remove":
        await query.edit_message_text(
            "➖ *Remove Credits*\n\n"
            "Send the command in this format:\n"
            "`/removecredits <user_id> <amount>`\n\n"
            "Example:\n"
            "`/removecredits 123456789 5`\n\n"
            "This will remove 5 credits from user 123456789",
            parse_mode="Markdown"
        )
        return
    
    elif data == "owner_check":
        await query.edit_message_text(
            "📊 *Check Credits*\n\n"
            "Send the command in this format:\n"
            "`/checkcredits <user_id>`\n\n"
            "Example:\n"
            "`/checkcredits 123456789`",
            parse_mode="Markdown"
        )
        return
    
    elif data == "owner_list":
        credits = load_credits()
        if not credits:
            await query.edit_message_text("📋 No users have credits yet.")
            return
        
        sorted_users = sorted(credits.items(), key=lambda x: x[1], reverse=True)
        
        message = "📋 *User Credits List*\n\n"
        for i, (uid, cred) in enumerate(sorted_users[:20], 1):
            message += f"{i}. User `{uid}` - {cred} credits\n"
        
        if len(sorted_users) > 20:
            message += f"\n... and {len(sorted_users) - 20} more users"
        
        await query.edit_message_text(message, parse_mode="Markdown")
        return
    
    elif data == "owner_total":
        credits = load_credits()
        total = sum(credits.values())
        users = len(credits)
        await query.edit_message_text(
            f"💰 *Total Credits Summary*\n\n"
            f"👥 Total Users: {users}\n"
            f"🪙 Total Credits: {total}\n"
            f"💳 Avg Credits: {total/users if users > 0 else 0:.1f}",
            parse_mode="Markdown"
        )
        return
    
    elif data == "owner_reset":
        await query.edit_message_text(
            "🔄 *Reset Credits*\n\n"
            "Send the command in this format:\n"
            "`/resetcredits <user_id>`\n\n"
            "Example:\n"
            "`/resetcredits 123456789`\n\n"
            "This will reset user's credits to 0",
            parse_mode="Markdown"
        )
        return
    
    elif data == "owner_giveall":
        await query.edit_message_text(
            "🎁 *Give Credits to All*\n\n"
            "Send the command in this format:\n"
            "`/giveall <amount>`\n\n"
            "Example:\n"
            "`/giveall 5`\n\n"
            "This will give 5 credits to ALL users",
            parse_mode="Markdown"
        )
        return

async def add_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add credits to a user (owner only)"""
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "❌ Invalid format!\n"
            "Usage: `/addcredits <user_id> <amount>`\n"
            "Example: `/addcredits 123456789 10`",
            parse_mode="Markdown"
        )
        return
    
    try:
        target_user = int(args[0])
        amount = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ User ID and amount must be numbers!")
        return
    
    if amount <= 0:
        await update.message.reply_text("❌ Amount must be greater than 0!")
        return
    
    new_balance = add_user_credits(target_user, amount)
    
    await update.message.reply_text(
        f"✅ *Credits Added!*\n\n"
        f"👤 User: `{target_user}`\n"
        f"➕ Added: {amount} credits\n"
        f"💰 New Balance: {new_balance} credits",
        parse_mode="Markdown"
    )
    
    try:
        await context.bot.send_message(
            chat_id=target_user,
            text=f"🎉 *Credits Added!*\n\n"
                 f"➕ {amount} credits have been added to your account.\n"
                 f"💰 New Balance: {new_balance} credits\n\n"
                 f"Use /start to download Aadhaar.",
            parse_mode="Markdown"
        )
    except:
        pass

async def remove_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove credits from a user (owner only)"""
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "❌ Invalid format!\n"
            "Usage: `/removecredits <user_id> <amount>`\n"
            "Example: `/removecredits 123456789 5`",
            parse_mode="Markdown"
        )
        return
    
    try:
        target_user = int(args[0])
        amount = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ User ID and amount must be numbers!")
        return
    
    if amount <= 0:
        await update.message.reply_text("❌ Amount must be greater than 0!")
        return
    
    credits = load_credits()
    user_id_str = str(target_user)
    current = credits.get(user_id_str, 0)
    new_balance = max(0, current - amount)
    credits[user_id_str] = new_balance
    save_credits(credits)
    
    await update.message.reply_text(
        f"✅ *Credits Removed!*\n\n"
        f"👤 User: `{target_user}`\n"
        f"➖ Removed: {amount} credits\n"
        f"💰 New Balance: {new_balance} credits",
        parse_mode="Markdown"
    )

async def reset_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset a user's credits to 0 (owner only)"""
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "❌ Invalid format!\n"
            "Usage: `/resetcredits <user_id>`\n"
            "Example: `/resetcredits 123456789`",
            parse_mode="Markdown"
        )
        return
    
    try:
        target_user = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ User ID must be a number!")
        return
    
    credits = load_credits()
    credits[str(target_user)] = 0
    save_credits(credits)
    
    await update.message.reply_text(
        f"✅ *Credits Reset!*\n\n"
        f"👤 User: `{target_user}`\n"
        f"🔄 Credits reset to 0",
        parse_mode="Markdown"
    )

async def give_all_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Give credits to ALL users (owner only)"""
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "❌ Invalid format!\n"
            "Usage: `/giveall <amount>`\n"
            "Example: `/giveall 5`",
            parse_mode="Markdown"
        )
        return
    
    try:
        amount = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number!")
        return
    
    if amount <= 0:
        await update.message.reply_text("❌ Amount must be greater than 0!")
        return
    
    credits = load_credits()
    users = list(credits.keys())
    
    if not users:
        await update.message.reply_text("❌ No users found to give credits!")
        return
    
    for user in users:
        credits[user] = credits.get(user, 0) + amount
    
    save_credits(credits)
    
    await update.message.reply_text(
        f"✅ *Credits Given to All!*\n\n"
        f"👥 Users: {len(users)}\n"
        f"🎁 Each got: {amount} credits\n"
        f"💰 Total given: {len(users) * amount} credits",
        parse_mode="Markdown"
    )
    
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=int(user),
                text=f"🎉 *Bonus Credits!*\n\n"
                     f"🎁 {amount} credits have been added to your account!\n"
                     f"💰 New Balance: {credits[user]} credits\n\n"
                     f"Use /start to download Aadhaar.",
                parse_mode="Markdown"
            )
        except:
            pass

async def check_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check credits for a user (owner only)"""
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "❌ Invalid format!\n"
            "Usage: `/checkcredits <user_id>`\n"
            "Example: `/checkcredits 123456789`",
            parse_mode="Markdown"
        )
        return
    
    try:
        target_user = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ User ID must be a number!")
        return
    
    credits = get_user_credits(target_user)
    
    await update.message.reply_text(
        f"📊 *User Credits*\n\n"
        f"👤 User: `{target_user}`\n"
        f"💰 Credits: {credits}",
        parse_mode="Markdown"
    )

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all users with credits (owner only)"""
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    credits = load_credits()
    if not credits:
        await update.message.reply_text("📋 No users have credits yet.")
        return
    
    sorted_users = sorted(credits.items(), key=lambda x: x[1], reverse=True)
    
    message = "📋 *User Credits List*\n\n"
    for i, (uid, cred) in enumerate(sorted_users[:20], 1):
        message += f"{i}. User `{uid}` - {cred} credits\n"
    
    if len(sorted_users) > 20:
        message += f"\n... and {len(sorted_users) - 20} more users"
    
    await update.message.reply_text(message, parse_mode="Markdown")

async def total_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show total credits summary (owner only)"""
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    credits = load_credits()
    total = sum(credits.values())
    users = len(credits)
    
    await update.message.reply_text(
        f"💰 *Total Credits Summary*\n\n"
        f"👥 Total Users: {users}\n"
        f"🪙 Total Credits: {total}\n"
        f"💳 Avg Credits: {total/users if users > 0 else 0:.1f}",
        parse_mode="Markdown"
    )

async def my_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check own credits (any user)"""
    user_id = update.effective_user.id
    credits = get_user_credits(user_id)
    
    if is_owner(user_id) and _OWNER_UNLIMITED:
        await update.message.reply_text(
            f"👑 *Owner Credits*\n\n"
            f"👤 User: `{user_id}`\n"
            f"🪙 Available Credits: ♾️ UNLIMITED\n\n"
            f"🎯 You are the owner! You can use the bot anytime.\n"
            f"Use /ownerhelp to see all commands.",
            parse_mode="Markdown"
        )
        return
    
    await update.message.reply_text(
        f"💰 *Your Credits*\n\n"
        f"👤 User: `{user_id}`\n"
        f"🪙 Available Credits: {credits}\n\n"
        f"Each Aadhaar download costs {_CREDIT_COST} credit.\n"
        f"Contact @vikash1178 to get more credits.",
        parse_mode="Markdown"
    )

# ============================================================
# BOT HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    
    credits = get_user_credits(user_id)
    
    if is_owner(user_id) and _OWNER_UNLIMITED:
        if user_id in _SESSIONS:
            del _SESSIONS[user_id]
        _SESSIONS[user_id] = UserSession()
        
        await update.message.reply_text(
            f"👑 *DARk Aadhar PDF Tool - Owner Mode*\n"
            f"👨‍💻 Developer: @vikash1178\n\n"
            f"💰 Credits: ♾️ UNLIMITED\n"
            f"📦 Cost: FREE for owner\n\n"
            "📝 Enter your Full Name as in Aadhaar\n"
            "_Type Mr to skip_\n\n"
            "_You can stop anytime using the Stop button_",
            parse_mode="Markdown",
            reply_markup=get_stop_keyboard()
        )
        return NAME
    
    if credits <= 0:
        await update.message.reply_text(
            "🔐 *DARk Aadhar PDF Tool*\n"
            "👨‍💻 Developer: @vikash1178\n\n"
            "❌ *Insufficient Credits!*\n\n"
            f"💰 Your Balance: {credits} credits\n"
            f"📦 Cost per download: {_CREDIT_COST} credit\n\n"
            "Contact @vikash1178 to get credits.\n"
            "Use /mycredits to check your balance.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    
    if user_id in _SESSIONS:
        del _SESSIONS[user_id]
    _SESSIONS[user_id] = UserSession()
    
    await update.message.reply_text(
        f"🔐 *DARk Aadhar PDF Tool*\n"
        f"👨‍💻 Developer: @vikash1178\n\n"
        f"💰 Your Balance: {credits} credits\n"
        f"📦 This download costs: {_CREDIT_COST} credit\n"
        f"📝 Remaining after: {credits - _CREDIT_COST} credits\n\n"
        "📝 Enter your Full Name as in Aadhaar\n"
        "_Type Mr to skip_\n\n"
        "_You can stop anytime using the Stop button_",
        parse_mode="Markdown",
        reply_markup=get_stop_keyboard()
    )
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    us = _SESSIONS.get(user_id)
    if not us:
        await update.message.reply_text("Session expired. /start again.")
        return ConversationHandler.END
    
    name = update.message.text.strip()
    us.name = name if name else "Mr"
    
    credits = get_user_credits(user_id)
    
    if is_owner(user_id) and _OWNER_UNLIMITED:
        await update.message.reply_text(
            f"✅ Name: {us.name}\n\n"
            f"📱 Enter your 10-digit Mobile Number\n\n"
            f"💰 Credits: ♾️ UNLIMITED\n\n"
            f"_You can stop anytime using the Stop button_",
            reply_markup=get_stop_keyboard()
        )
    else:
        await update.message.reply_text(
            f"✅ Name: {us.name}\n\n"
            f"📱 Enter your 10-digit Mobile Number\n\n"
            f"💰 Credits after download: {credits - _CREDIT_COST}\n\n"
            f"_You can stop anytime using the Stop button_",
            reply_markup=get_stop_keyboard()
        )
    return MOBILE

async def get_mobile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    us = _SESSIONS.get(user_id)
    if not us:
        await update.message.reply_text("Session expired. /start again.")
        return ConversationHandler.END
    
    mobile = update.message.text.strip()
    if not _validate_number(mobile):
        await update.message.reply_text(
            "❌ Enter exactly 10 digits.\n\n"
            "📱 Enter your 10-digit Mobile Number",
            reply_markup=get_stop_keyboard()
        )
        return MOBILE
    
    us.mobile = mobile
    
    progress = await update.message.reply_text("🔄 Generating captcha...")
    img_bytes, txn = _get_captcha_with_retry(us.s)
    
    if not img_bytes:
        await progress.delete()
        await update.message.reply_text(
            "❌ Failed to generate captcha. Please /start again.",
            reply_markup=get_stop_keyboard()
        )
        return ConversationHandler.END
    
    us.cap1_txn = txn
    us.captcha_attempts = 0
    await progress.delete()
    
    await update.message.reply_photo(
        photo=io.BytesIO(img_bytes),
        caption="📸 Enter the captcha text (6 characters, case-sensitive)\n\n_You can stop anytime using the Stop button_",
        reply_markup=get_stop_keyboard()
    )
    return CAP1

async def get_captcha1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    us = _SESSIONS.get(user_id)
    if not us:
        await update.message.reply_text("Session expired. /start again.")
        return ConversationHandler.END
    
    us.cap1_text = update.message.text.strip()
    us.captcha_attempts += 1
    
    progress = await update.message.reply_text("📤 Requesting OTP...")
    
    payload = {
        "mobileNumber": us.mobile,
        "dob": None,
        "email": None,
        "name": us.name,
        "option": "EID",
        "otp": None,
        "otpTxnId": None,
        "captchaTxnId": us.cap1_txn,
        "captcha": us.cap1_text,
        "resendOtp": False
    }
    
    result, err = _api_call(us.s, _EP1, payload, "EID_OTP")
    await progress.delete()
    
    if not result:
        await update.message.reply_text(
            f"❌ No response from server. /start to retry",
            reply_markup=get_stop_keyboard()
        )
        return ConversationHandler.END
    
    if result.get("errorCode") == "REU_VAL_CAP_INF_007":
        if us.captcha_attempts >= 3:
            await update.message.reply_text(
                "❌ Too many failed captcha attempts.\n"
                "Please /start to try again.",
                reply_markup=get_stop_keyboard()
            )
            return ConversationHandler.END
        
        await update.message.reply_text(
            f"❌ Invalid captcha! (Attempt {us.captcha_attempts}/3)\n"
            "Generating new captcha...\n\n"
            "💡 Tips:\n"
            "• Captcha is case-sensitive\n"
            "• Check 0 vs O, 1 vs l vs I\n"
            "• 6 characters exactly",
            reply_markup=get_stop_keyboard()
        )
        
        img_bytes, txn = _get_captcha_with_retry(us.s)
        if img_bytes and txn:
            us.cap1_txn = txn
            await update.message.reply_photo(
                photo=io.BytesIO(img_bytes),
                caption="📸 Enter the NEW captcha text (6 characters, case-sensitive)",
                reply_markup=get_stop_keyboard()
            )
            return CAP1
        else:
            await update.message.reply_text(
                "❌ Failed to generate new captcha. /start to retry",
                reply_markup=get_stop_keyboard()
            )
            return ConversationHandler.END
    
    status = result.get("status")
    otp_sent = result.get("responseData", {}).get("otpSent", False)
    
    if status == "Success" and otp_sent:
        us.otp1_txn = result["responseData"]["otpTxnId"]
        masked = f"{us.mobile[:2]}****{us.mobile[-4:]}"
        
        await update.message.reply_text(
            f"✅ OTP Sent to {masked}\n\n"
            "📝 Enter the 6-digit OTP\n\n"
            "_You can stop anytime using the Stop button_",
            reply_markup=get_stop_keyboard()
        )
        return OTP1
    else:
        msg = result.get("responseData", {}).get("message", "Failed to send OTP")
        logger.error(f"EID OTP failed: {result}")
        await update.message.reply_text(
            f"❌ OTP Failed: {msg}\n/start to retry",
            reply_markup=get_stop_keyboard()
        )
        return ConversationHandler.END

async def get_otp1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    us = _SESSIONS.get(user_id)
    if not us:
        await update.message.reply_text("Session expired. /start again.")
        return ConversationHandler.END
    
    otp = update.message.text.strip()
    if not otp.isdigit() or len(otp) != 6:
        await update.message.reply_text(
            "❌ OTP must be exactly 6 digits.\n\n"
            "📝 Enter the 6-digit OTP",
            reply_markup=get_stop_keyboard()
        )
        return OTP1
    
    progress = await update.message.reply_text("🔍 Verifying OTP...")
    
    payload = {
        "mobileNumber": us.mobile,
        "dob": None,
        "email": None,
        "name": us.name,
        "option": "EID",
        "otp": otp,
        "otpTxnId": us.otp1_txn,
        "captchaTxnId": us.cap1_txn,
        "captcha": us.cap1_text,
        "resendOtp": False
    }
    
    result, err = _api_call(us.s, _EP1, payload, "EID_VERIFY")
    await progress.delete()
    
    if not result:
        await update.message.reply_text(
            "❌ No response. /start to retry",
            reply_markup=get_stop_keyboard()
        )
        return ConversationHandler.END
    
    status = result.get("status")
    eid = result.get("responseData", {}).get("eidNumber")
    
    if status == "Success" and eid:
        us.eid = eid
        us.full_name = result["responseData"].get("name", us.name)
        
        await update.message.reply_text(
            f"✅ EID Retrieved!\n"
            f"👤 {us.full_name}\n"
            f"🆔 {us.eid}\n\n"
            "🔄 Generating download captcha...",
            reply_markup=get_stop_keyboard()
        )
        
        img_bytes, txn = _get_captcha_with_retry(us.s)
        if not img_bytes:
            await update.message.reply_text(
                "❌ Captcha failed. /start to retry",
                reply_markup=get_stop_keyboard()
            )
            return ConversationHandler.END
        
        us.cap2_txn = txn
        us.captcha_attempts = 0
        
        await update.message.reply_photo(
            photo=io.BytesIO(img_bytes),
            caption="📸 Enter the download captcha (6 characters, case-sensitive)\n\n_You can stop anytime using the Stop button_",
            reply_markup=get_stop_keyboard()
        )
        return CAP2
    else:
        msg = result.get("responseData", {}).get("message", "Invalid OTP")
        await update.message.reply_text(
            f"❌ Failed: {msg}\n\n"
            "📝 Enter the 6-digit OTP again",
            reply_markup=get_stop_keyboard()
        )
        return OTP1

async def get_captcha2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    us = _SESSIONS.get(user_id)
    if not us:
        await update.message.reply_text("Session expired. /start again.")
        return ConversationHandler.END
    
    us.cap2_text = update.message.text.strip()
    us.captcha_attempts += 1
    
    progress = await update.message.reply_text("📤 Requesting download OTP...")
    
    payload = {
        "eidNumber": us.eid,
        "idType": "eid",
        "captchaTxnId": us.cap2_txn,
        "captchaValue": us.cap2_text,
        "transactionId": str(uuid.uuid4()),
        "resendOTP": False
    }
    
    result, err = _api_call(us.s, _EP3, payload, "DL_OTP")
    await progress.delete()
    
    if not result:
        await update.message.reply_text(
            f"❌ No response. /start to retry",
            reply_markup=get_stop_keyboard()
        )
        return ConversationHandler.END
    
    if result.get("errorCode") == "REU_VAL_CAP_INF_007":
        if us.captcha_attempts >= 3:
            await update.message.reply_text(
                "❌ Too many failed captcha attempts.\n"
                "Please /start to try again.",
                reply_markup=get_stop_keyboard()
            )
            return ConversationHandler.END
        
        await update.message.reply_text(
            f"❌ Invalid captcha! (Attempt {us.captcha_attempts}/3)\n"
            "Generating new captcha...",
            reply_markup=get_stop_keyboard()
        )
        
        img_bytes, txn = _get_captcha_with_retry(us.s)
        if img_bytes and txn:
            us.cap2_txn = txn
            await update.message.reply_photo(
                photo=io.BytesIO(img_bytes),
                caption="📸 Enter the NEW download captcha",
                reply_markup=get_stop_keyboard()
            )
            return CAP2
        else:
            await update.message.reply_text(
                "❌ Failed to generate new captcha. /start to retry",
                reply_markup=get_stop_keyboard()
            )
            return ConversationHandler.END
    
    if result.get("status") == "Success":
        us.otp2_txn = result.get("txnId") or result.get("responseData", {}).get("otpTxnId")
        
        await update.message.reply_text(
            "✅ Download OTP Sent!\n\n"
            "📝 Enter the Download OTP\n\n"
            "_You can stop anytime using the Stop button_",
            reply_markup=get_stop_keyboard()
        )
        return OTP2
    else:
        msg = result.get("message", "Failed")
        await update.message.reply_text(
            f"❌ Failed: {msg}\n/start to retry",
            reply_markup=get_stop_keyboard()
        )
        return ConversationHandler.END

async def get_otp2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    us = _SESSIONS.get(user_id)
    if not us:
        await update.message.reply_text("Session expired. /start again.")
        return ConversationHandler.END
    
    otp = update.message.text.strip()
    if not otp.isdigit() or len(otp) != 6:
        await update.message.reply_text(
            "❌ OTP must be exactly 6 digits.\n\n"
            "📝 Enter the Download OTP",
            reply_markup=get_stop_keyboard()
        )
        return OTP2
    
    progress = await update.message.reply_text("📥 Downloading PDF...")
    
    txn_id = str(uuid.uuid4())
    custom_h = _H.copy()
    custom_h["transactionid"] = txn_id
    custom_h["x-request-id"] = txn_id
    
    try:
        r = us.s.post(_EP4, headers=custom_h,
                     json={"eid": us.eid, "mask": False, "otp": otp, "otpTxnId": us.otp2_txn},
                     timeout=30)
        data = r.json()
        
        await progress.delete()
        
        if data.get("statusCode") == 200:
            pdf_b64 = data.get("data", {}).get("aadhaarPdf") or data.get("aadhaarPdf")
            if pdf_b64:
                pdf_bytes = base64.b64decode(pdf_b64)
                
                unlocked_pdf, password = _unlock_pdf(pdf_bytes, us.full_name)
                
                if deduct_user_credits(user_id, _CREDIT_COST):
                    remaining = get_user_credits(user_id)
                    
                    _credit = _get_credit_text()
                    
                    if is_owner(user_id) and _OWNER_UNLIMITED:
                        credit_display = "♾️ UNLIMITED"
                    else:
                        credit_display = str(remaining)
                    
                    if unlocked_pdf:
                        pdf_to_send = unlocked_pdf
                        caption = (
                            f"🔓 PDF Unlocked\n"
                            f"👤 {us.full_name}\n"
                            f"🆔 {us.eid}\n"
                            f"🔑 Password: {password}\n"
                            f"💰 Remaining Credits: {credit_display}\n\n"
                            f"{_credit}\n"
                            f"👨‍💻 Developer: @vikash1178"
                        )
                    else:
                        pdf_to_send = pdf_bytes
                        hint = us.full_name[:4].upper() if us.full_name else "MR"
                        caption = (
                            f"🔒 Password Protected\n"
                            f"👤 {us.full_name}\n"
                            f"🆔 {us.eid}\n"
                            f"💡 Hint: {hint}YYYY\n"
                            f"💰 Remaining Credits: {credit_display}\n\n"
                            f"{_credit}\n"
                            f"👨‍💻 Developer: @vikash1178"
                        )
                    
                    pdf_file = io.BytesIO(pdf_to_send)
                    pdf_file.name = f"aadhaar_{us.eid[:8]}.pdf"
                    
                    await update.message.reply_document(
                        document=pdf_file,
                        caption=caption
                    )
                    
                    await update.message.reply_text(
                        f"✅ Download Complete!\n\n"
                        f"💰 Credits Used: {0 if is_owner(user_id) else _CREDIT_COST}\n"
                        f"💰 Remaining: {credit_display}\n\n"
                        f"{_credit}\n"
                        f"👨‍💻 Developer: @vikash1178"
                    )
                else:
                    await update.message.reply_text("❌ Failed to deduct credits. Please try again.")
            else:
                await update.message.reply_text("❌ No PDF data in response")
        else:
            msg = data.get("statusMessage", "Unknown error")
            await update.message.reply_text(f"❌ Download Failed: {msg}")
            
    except Exception as e:
        await progress.delete()
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    if user_id in _SESSIONS:
        del _SESSIONS[user_id]
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if user_id in _SESSIONS:
        del _SESSIONS[user_id]
    await update.message.reply_text(
        "❌ *Cancelled.*\n"
        "Send /start to begin again.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ============================================================
# RUN WITH HEALTH CHECK FOR RAILWAY
# ============================================================

def run_health_server():
    """Run health check server for Railway"""
    try:
        from flask import Flask
        import threading
        
        app = Flask(__name__)
        
        @app.route('/health')
        def health():
            return "OK", 200
        
        @app.route('/')
        def index():
            return "DARk Aadhar Bot is running!", 200
        
        port = int(os.environ.get('PORT', 8080))
        app.run(host='0.0.0.0', port=port, debug=False)
    except:
        pass  # Flask not required for bot to run

# ============================================================
# MAIN
# ============================================================

def main():
    global BOT_TOKEN
    BOT_TOKEN = load_token()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # ALL OWNER COMMANDS
    app.add_handler(CommandHandler("ownerhelp", owner_help))
    app.add_handler(CommandHandler("owner", owner_panel))
    app.add_handler(CommandHandler("addcredits", add_credits))
    app.add_handler(CommandHandler("removecredits", remove_credits))
    app.add_handler(CommandHandler("checkcredits", check_credits))
    app.add_handler(CommandHandler("listusers", list_users))
    app.add_handler(CommandHandler("totalcredits", total_credits))
    app.add_handler(CommandHandler("resetcredits", reset_credits))
    app.add_handler(CommandHandler("giveall", give_all_credits))
    app.add_handler(CommandHandler("mycredits", my_credits))
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(stop_handler, pattern="^stop$"))
    app.add_handler(CallbackQueryHandler(owner_callback_handler, pattern="^owner_"))
    
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            MOBILE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_mobile)],
            CAP1: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_captcha1)],
            OTP1: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_otp1)],
            CAP2: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_captcha2)],
            OTP2: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_otp2)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=_SESSION_TTL
    )
    
    app.add_handler(conv)
    
    if not os.path.exists(_CREDITS_FILE):
        save_credits({})
    
    print("\n" + "="*50)
    print("   DARk Aadhar PDF Tool")
    print("   Developer: @vikash1178")
    print("="*50)
    print("\n✅ Bot is running!")
    print(f"👑 Owner ID: {_OWNER_ID}")
    print(f"👑 Owner Benefits: UNLIMITED CREDITS! 🎉")
    print("\n📋 ALL OWNER COMMANDS:")
    print("   /ownerhelp - Show all owner commands")
    print("   /owner - Open Owner Panel")
    print("   /addcredits <user_id> <amount> - Add credits")
    print("   /removecredits <user_id> <amount> - Remove credits")
    print("   /checkcredits <user_id> - Check user credits")
    print("   /listusers - List all users")
    print("   /totalcredits - Total credits summary")
    print("   /resetcredits <user_id> - Reset user credits")
    print("   /giveall <amount> - Give credits to ALL users")
    print("   /mycredits - Check your own credits")
    print("\n📋 USER COMMANDS:")
    print("   /start - Start the tool")
    print("   /mycredits - Check your credits")
    print("\n   Press Ctrl+C to stop\n")
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    try:
        # Start health server in background (for Railway)
        import threading
        health_thread = threading.Thread(target=run_health_server, daemon=True)
        health_thread.start()
        
        # Start bot
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Bot stopped")
    except Exception as e:
        print(f"\n❌ Error: {e}")
