import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from sqlalchemy.exc import OperationalError

from config import load_config
from db import DB
from models import User, ConnectedAccount, Buffer, ActiveReply, MandatoryChannel
from auth_flow import AuthFlow
from sender import Sender
from language_manager import lang_manager

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def run_migrations():
    """Run database migrations on startup"""
    from sqlalchemy import text
    from config import load_config
    
    cfg = load_config()
    db_url = cfg.db_url
    
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://")
    
    from sqlalchemy import create_engine
    engine = create_engine(db_url)
    
    with engine.connect() as conn:
        # Check if approved_by column exists
        result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'approved_by'"))
        columns = [row[0] for row in result]
        
        if 'approved_by' not in columns:
            log.info("Running migration: Adding approved_by and approved_at columns...")
            conn.execute(text("ALTER TABLE users ADD COLUMN approved_by BIGINT"))
            conn.execute(text("ALTER TABLE users ADD COLUMN approved_at TIMESTAMP"))
            conn.commit()
            log.info("✅ Migration completed successfully!")
        else:
            log.info("ℹ️ Migration already applied.")
    
    engine.dispose()

cfg = load_config()
db = DB(cfg)
auth = AuthFlow(cfg)
sender = Sender(cfg)

STATE: dict[int, dict] = {}

async def db_operation(func, max_retries=3):
    """Execute database operation with retry logic for handling locks"""
    for attempt in range(max_retries):
        try:
            return func()
        except OperationalError as e:
            if "locked" in str(e).lower() or "database is locked" in str(e).lower():
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
            log.error(f"Database error: {e}")
            raise
    return None

def get_user_status(uid):
    with db.session() as s:
        user = s.query(User).filter_by(tg_user_id=uid).first()
        return user.status if user else "new"

def is_admin(uid):
    if uid == cfg.owner_id:
        return True
    with db.session() as s:
        user = s.query(User).filter_by(tg_user_id=uid).first()
        return user.is_admin if user else False

def is_user_banned(uid):
    with db.session() as s:
        user = s.query(User).filter_by(tg_user_id=uid).first()
        return user.is_banned if user else False

def resolve_user(target):
    """Resolve username or user_id to user_id. Returns None if not found."""
    if target.startswith("@"):
        username = target[1:].lower()
        with db.session() as s:
            user = s.query(User).filter(User.username == username).first()
            return user.tg_user_id if user else None
    else:
        try:
            return int(target)
        except ValueError:
            return None

def get_user_language(uid):
    """Get user's preferred language"""
    with db.session() as s:
        user = s.query(User).filter_by(tg_user_id=uid).first()
        return user.language if user else 'uz'

async def notify_owner(app, uid: int, username: str, full_name: str):
    from datetime import datetime
    
    kb = [[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"appr_{uid}"),
        InlineKeyboardButton("❌ Rad etish", callback_data=f"rej_{uid}")
    ]]
    
    # Get all admins
    with db.session() as s:
        admins = s.query(User).filter_by(is_admin=True).all()
    
    # Send to all admins
    for admin in admins:
        try:
            await app.bot.send_message(
                chat_id=admin.tg_user_id,
                text=f"🔔 Yangi so'rov!\n\nIsm: {full_name}\nUsername: @{username}\nID: {uid}",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except Exception as e:
            log.error(f"Admin {admin.tg_user_id} ga xabar yuborishda xato: {e}")

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username
    
    if is_user_banned(uid):
        await update.message.reply_text("🚫 You are banned.")
        return
    
    status = get_user_status(uid)
    
    if status == "new":
        # Show language selection first
        languages = [
            ("🇺🇿 O'zbekcha", "uz"),
            ("🇷🇺 Русский", "ru"),
            ("🇬🇧 English", "en"),
            ("🇹🇷 Türkçe", "tr"),
            ("🇰🇿 Қазақша", "kz")
        ]
        
        kb = []
        for label, code in languages:
            kb.append([InlineKeyboardButton(label, callback_data=f"init_lang_{code}")])
        
        text = "🌐 Tilni tanlang / Select language:"
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
    elif status == "pending":
        lang = get_user_language(uid)
        with db.session() as s:
            user = s.query(User).filter_by(tg_user_id=uid).first()
            if user and user.username != username:
                user.username = username
                s.commit()
        await update.message.reply_text(lang_manager.get(lang, 'start.pending_wait'))
    elif status == "rejected":
        lang = get_user_language(uid)
        await update.message.reply_text(lang_manager.get(lang, 'start.rejected'))
    elif status == "approved":
        lang = get_user_language(uid)
        with db.session() as s:
            user = s.query(User).filter_by(tg_user_id=uid).first()
            if user and user.username != username:
                user.username = username
                s.commit()
        await show_main_menu(update, ctx, uid)

async def init_language(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    lang_code = query.data.split("_")[2]
    
    username = update.effective_user.username
    
    # Create user with selected language
    with db.session() as s:
        s.add(User(tg_user_id=uid, username=username, status="pending", language=lang_code))
        s.commit()
    
    # Check if there are mandatory channels
    with db.session() as s:
        channels = s.query(MandatoryChannel).all()
    
    if channels:
        # Show channel subscription
        kb = []
        for channel in channels:
            try:
                kb.append([InlineKeyboardButton(f"📢 {channel.channel_title or channel.channel_username}", url=f"https://t.me/{channel.channel_username.lstrip('@')}")])
            except:
                pass
        kb.append([InlineKeyboardButton(lang_manager.get(lang_code, 'channel.check_button'), callback_data=f"check_subscription_{lang_code}")])
        
        text = lang_manager.get(lang_code, 'channel.subscribe_title') + "\n\n"
        text += lang_manager.get(lang_code, 'channel.subscribe_message')
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        # No channels, proceed to notify owner
        await notify_owner(ctx.application, uid, username, update.effective_user.full_name)
        await query.edit_message_text(lang_manager.get(lang_code, 'start.pending'))

async def check_subscription(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    lang_code = query.data.split("_")[2]
    
    # Check all mandatory channels
    with db.session() as s:
        channels = s.query(MandatoryChannel).all()
    
    all_subscribed = True
    for channel in channels:
        try:
            member = await ctx.application.bot.get_chat_member(channel.channel_id, uid)
            if member.status in ['left', 'kicked']:
                all_subscribed = False
                break
        except:
            all_subscribed = False
            break
    
    if all_subscribed:
        # User is subscribed to all channels
        username = update.effective_user.username
        await notify_owner(ctx.application, uid, username, update.effective_user.full_name)
        await query.edit_message_text(lang_manager.get(lang_code, 'start.pending'))
    else:
        # User not subscribed
        await query.answer(lang_manager.get(lang_code, 'channel.not_subscribed'), show_alert=True)

async def show_main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE, uid: int):
    lang = get_user_language(uid)
    with db.session() as s:
        acc = s.query(ConnectedAccount).filter_by(tg_user_id=uid).first()
    
    if not acc:
        kb = [[InlineKeyboardButton(lang_manager.get(lang, 'menu.register'), callback_data="login")]]
        text = lang_manager.get(lang, 'start.welcome')
    else:
        delay_text = f"{acc.delay}s (🎲 Random)" if acc.random_delay else f"{acc.delay}s"
        kb = [
            [InlineKeyboardButton(lang_manager.get(lang, 'menu.view_buffer'), callback_data="buf_view")],
            [InlineKeyboardButton(lang_manager.get(lang, 'menu.delete_buffer'), callback_data="buf_del")],
            [InlineKeyboardButton(f"{lang_manager.get(lang, 'menu.settings')} ({delay_text})", callback_data="set_delay")],
            [InlineKeyboardButton("🌐 Til / Language", callback_data="set_language")],
            [InlineKeyboardButton("📖 Guide / Yo'riqnomа", callback_data="show_guide")],
        ]
        text = lang_manager.get(lang, 'menu.main')
        
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def owner_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime
    
    query = update.callback_query
    admin_uid = query.from_user.id
    
    if not is_admin(admin_uid):
        await query.answer("Siz admin emassiz!", show_alert=True)
        return
    
    action, uid_str = query.data.split("_")
    uid = int(uid_str)
    
    with db.session() as s:
        user = s.query(User).filter_by(tg_user_id=uid).first()
        if not user:
            await query.answer("Foydalanuvchi topilmadi!", show_alert=True)
            return
        
        # Race condition prevention: check if already processed
        if user.status != "pending":
            # Already processed by another admin
            if user.status == "approved":
                admin = s.query(User).filter_by(tg_user_id=user.approved_by).first()
                admin_name = f"@{admin.username}" if admin else f"ID: {user.approved_by}"
                await query.answer(f"Bu foydalanuvchi allaqachon tasdiqlangan!\nTasdiqlagan: {admin_name}", show_alert=True)
            else:
                await query.answer("Bu foydalanuvchi allaqachon rad etilgan!", show_alert=True)
            return
        
        # Process approval/rejection
        if action == "appr":
            user.status = "approved"
            user.approved_by = admin_uid
            user.approved_at = datetime.now()
            s.commit()
            
            # Get admin info
            admin = s.query(User).filter_by(tg_user_id=admin_uid).first()
            admin_name = f"@{admin.username}" if admin else f"ID: {admin_uid}"
            user_name = f"@{user.username}" if user.username else f"ID: {uid}"
            timestamp = user.approved_at.strftime("%Y-%m-%d %H:%M:%S")
            
            # Notify all admins
            admins = s.query(User).filter_by(is_admin=True).all()
            for adm in admins:
                try:
                    await ctx.bot.send_message(
                        chat_id=adm.tg_user_id,
                        text=f"✅ Tasdiqlandi!\n\nUser: {user_name} [{uid}]\nTasdiqlagan admin: {admin_name} [{admin_uid}]\nSana-vaqt: {timestamp}"
                    )
                except Exception as e:
                    log.error(f"Admin {adm.tg_user_id} ga xabar yuborishda xato: {e}")
            
            # Notify user
            try:
                await ctx.bot.send_message(uid, "✅ So'rovingiz tasdiqlandi! /start buyrug'ini qayta bosing.")
            except: pass
        else:
            user.status = "rejected"
            s.commit()
            
            # Notify all admins
            admins = s.query(User).filter_by(is_admin=True).all()
            for adm in admins:
                try:
                    await ctx.bot.send_message(
                        chat_id=adm.tg_user_id,
                        text=f"❌ Rad etildi!\n\nUser: @{user.username or uid} [{uid}]\nRad etgan admin: @{query.from_user.username or admin_uid} [{admin_uid}]"
                    )
                except Exception as e:
                    log.error(f"Admin {adm.tg_user_id} ga xabar yuborishda xato: {e}")
            
            # Notify user
            try:
                await ctx.bot.send_message(uid, "❌ Kechirasiz, sizning so'rovingiz rad etilgan.")
            except: pass
    
    await query.edit_message_text("✅ Amal bajarildi!")

async def on_login(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    STATE[update.effective_user.id] = {"step": "phone"}
    await update.callback_query.edit_message_text("📱 Telefon raqamingizni kiriting (+998...):")

async def save_account(uid, phone, enc):
    with db.session() as s:
        acc = s.query(ConnectedAccount).filter_by(tg_user_id=uid).first()
        if acc:
            acc.encrypted_session = enc
            acc.phone_hint = "+***" + phone[-4:]
        else:
            s.add(ConnectedAccount(tg_user_id=uid, encrypted_session=enc, phone_hint="+***" + phone[-4:]))
        s.commit()

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    st = STATE.get(uid, {})
    step = st.get("step")
    text = update.message.text.strip() if update.message.text else ""

    if step == "phone":
        st["phone"] = text
        st["step"] = "code"
        try:
            await auth.send_code(uid, text)
            await update.message.reply_text("📩 Kodni kiriting:")
        except Exception as e:
            STATE.pop(uid, None)
            await update.message.reply_text(f"Xato: {type(e).__name__}")
    elif step == "code":
        try:
            encrypted, finished = await auth.submit_code(uid, text)
        except RuntimeError as e:
            await update.message.reply_text(f"❌ {e}")
            return
        if not finished:
            st["step"] = "2fa"
            await update.message.reply_text("🔐 2FA parolingizni kiriting:")
            return
        await save_account(uid, st["phone"], encrypted)
        STATE.pop(uid, None)
        await update.message.reply_text("✅ Akkaunt ulandi!")
        await show_main_menu(update, ctx, uid)
    elif step == "2fa":
        try:
            encrypted, finished = await auth.submit_code(uid, "", password_2fa=text)
        except RuntimeError as e:
            await update.message.reply_text(f"❌ {e}")
            return
        if finished:
            await save_account(uid, st["phone"], encrypted)
            STATE.pop(uid, None)
            await update.message.reply_text("✅ Akkaunt ulandi!")
            await show_main_menu(update, ctx, uid)
    elif step == "buf_add":
        lang = get_user_language(uid)
        with db.session() as s:
            buf = s.query(Buffer).filter_by(tg_user_id=uid).first()
            if not buf:
                buf = Buffer(tg_user_id=uid, text=text)
                s.add(buf)
            else:
                buf.text = text
            s.commit()
        STATE.pop(uid, None)
        await update.message.reply_text(lang_manager.get(lang, 'buffer.saved'))
        await show_main_menu(update, ctx, uid)
    elif step == "delay":
        lang = get_user_language(uid)
        try:
            val = float(text)
            if 0.04 <= val <= 0.5:
                with db.session() as s:
                    acc = s.query(ConnectedAccount).filter_by(tg_user_id=uid).first()
                    if acc:
                        acc.delay = val
                        s.commit()
                await update.message.reply_text(lang_manager.get(lang, 'settings.delay_saved') + f"{val}" + lang_manager.get(lang, 'settings.delay_saved_end'))
            else:
                await update.message.reply_text(lang_manager.get(lang, 'settings.delay_error'))
        except:
            await update.message.reply_text(lang_manager.get(lang, 'settings.delay_invalid'))
        STATE.pop(uid, None)
        await show_main_menu(update, ctx, uid)
    elif step == "admin_edit_buf":
        target_user_id = st.get("target_user_id")
        with db.session() as s:
            buf = s.query(Buffer).filter_by(tg_user_id=target_user_id).first()
            if not buf:
                buf = Buffer(tg_user_id=target_user_id, text=text)
                s.add(buf)
            else:
                buf.text = text
            s.commit()
        STATE.pop(uid, None)
        await update.message.reply_text(f"✅ User {target_user_id} buferi yangilandi!")
        kb = [[InlineKeyboardButton("◀️ Orqaga", callback_data=f"admin_user_{target_user_id}")]]
        await update.message.reply_text("Admin menyuga qaytish:", reply_markup=InlineKeyboardMarkup(kb))
    elif step == "add_channel":
        try:
            channel_username = text.strip()
            if not channel_username.startswith("@"):
                channel_username = "@" + channel_username
            
            # Try to get channel info
            try:
                chat = await ctx.application.bot.get_chat(channel_username)
                channel_id = chat.id
                channel_title = chat.title
                
                with db.session() as s:
                    existing = s.query(MandatoryChannel).filter_by(channel_id=channel_id).first()
                    if existing:
                        await update.message.reply_text("❌ Bu kanal allaqachon qo'shilgan!")
                    else:
                        s.add(MandatoryChannel(channel_id=channel_id, channel_username=channel_username, channel_title=channel_title))
                        s.commit()
                        await update.message.reply_text(f"✅ Kanal qo'shildi: {channel_title}")
            except Exception as e:
                await update.message.reply_text(f"❌ Kanal topilmadi: {e}")
        except Exception as e:
            await update.message.reply_text(f"❌ Xato: {e}")
        STATE.pop(uid, None)
        await admin_menu(update, ctx)

async def on_buf_view(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    uid = update.effective_user.id
    lang = get_user_language(uid)
    with db.session() as s:
        buf = s.query(Buffer).filter_by(tg_user_id=uid).first()
    
    if not buf or not buf.text:
        text = lang_manager.get(lang, 'buffer.empty')
        kb = [[InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data="back")]]
    else:
        text = lang_manager.get(lang, 'buffer.view') + buf.text
        kb = [
            [InlineKeyboardButton(lang_manager.get(lang, 'buffer.edit_button'), callback_data="buf_add")],
            [InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data="back")]
        ]
    
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def on_buf_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    uid = update.effective_user.id
    lang = get_user_language(uid)
    with db.session() as s:
        buf = s.query(Buffer).filter_by(tg_user_id=uid).first()
    
    if buf and buf.text:
        text = lang_manager.get(lang, 'buffer.edit') + buf.text + lang_manager.get(lang, 'buffer.edit_prompt')
    else:
        text = lang_manager.get(lang, 'buffer.new_prompt')
    
    STATE[update.effective_user.id] = {"step": "buf_add"}
    await update.callback_query.edit_message_text(text)

async def on_buf_del(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    uid = update.effective_user.id
    lang = get_user_language(uid)
    with db.session() as s:
        s.query(Buffer).filter_by(tg_user_id=uid).delete()
        s.commit()
    await update.callback_query.answer(lang_manager.get(lang, 'buffer.deleted'))
    await show_main_menu(update, ctx, uid)

async def on_set_delay(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    uid = update.effective_user.id
    lang = get_user_language(uid)
    with db.session() as s:
        acc = s.query(ConnectedAccount).filter_by(tg_user_id=uid).first()
    
    current_delay = acc.delay if acc else 0.04
    current_random = acc.random_delay if acc else False
    
    kb = [
        [InlineKeyboardButton(lang_manager.get(lang, 'settings.toggle_random') if not current_random else lang_manager.get(lang, 'settings.toggle_random_off'), callback_data="toggle_random_delay")],
        [InlineKeyboardButton(lang_manager.get(lang, 'settings.change_delay'), callback_data="change_delay")],
        [InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data="back")]
    ]
    
    text = lang_manager.get(lang, 'settings.title')
    text += lang_manager.get(lang, 'settings.current') + f"{current_delay}s\n"
    text += lang_manager.get(lang, 'settings.random') + f" {lang_manager.get(lang, 'settings.random_on') if current_random else lang_manager.get(lang, 'settings.random_off')}\n\n"
    text += lang_manager.get(lang, 'settings.random_info') + f"{current_delay}" + lang_manager.get(lang, 'settings.random_info_end')
    
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def toggle_random_delay(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    uid = update.effective_user.id
    with db.session() as s:
        acc = s.query(ConnectedAccount).filter_by(tg_user_id=uid).first()
        if acc:
            acc.random_delay = not acc.random_delay
            s.commit()
    await on_set_delay(update, ctx)

async def change_delay(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    uid = update.effective_user.id
    lang = get_user_language(uid)
    STATE[update.effective_user.id] = {"step": "delay"}
    await update.callback_query.edit_message_text(lang_manager.get(lang, 'settings.delay_prompt'))

async def set_language(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    uid = update.effective_user.id
    lang = get_user_language(uid)
    
    languages = [
        ("🇺🇿 O'zbekcha", "uz"),
        ("🇷🇺 Русский", "ru"),
        ("🇬🇧 English", "en"),
        ("🇹🇷 Türkçe", "tr"),
        ("🇰🇿 Қазақша", "kz")
    ]
    
    kb = []
    for label, code in languages:
        kb.append([InlineKeyboardButton(label, callback_data=f"lang_{code}")])
    kb.append([InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data="back")])
    
    text = "🌐 Tilni tanlang / Select language:"
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def change_language(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    uid = update.effective_user.id
    lang_code = update.callback_query.data.split("_")[1]
    
    with db.session() as s:
        user = s.query(User).filter_by(tg_user_id=uid).first()
        if user:
            user.language = lang_code
            s.commit()
    
    await show_main_menu(update, ctx, uid)

async def on_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await show_main_menu(update, ctx, update.effective_user.id)

async def show_guide(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    lang = get_user_language(uid)
    
    text = f"{lang_manager.get(lang, 'guide.title')}\n\n"
    text += f"**{lang_manager.get(lang, 'guide.purpose')}**\n"
    text += f"{lang_manager.get(lang, 'guide.purpose_text')}\n\n"
    text += f"**{lang_manager.get(lang, 'guide.buffer_send')}**\n"
    text += f"{lang_manager.get(lang, 'guide.buffer_send_1')}\n"
    text += f"{lang_manager.get(lang, 'guide.buffer_send_2')}\n"
    text += f"{lang_manager.get(lang, 'guide.buffer_send_3')}\n"
    text += f"{lang_manager.get(lang, 'guide.buffer_send_4')}\n\n"
    text += f"**{lang_manager.get(lang, 'guide.reply_to')}**\n"
    text += f"{lang_manager.get(lang, 'guide.reply_to_1')}\n"
    text += f"{lang_manager.get(lang, 'guide.reply_to_2')}\n"
    text += f"{lang_manager.get(lang, 'guide.reply_to_3')}\n"
    text += f"{lang_manager.get(lang, 'guide.reply_to_4')}\n\n"
    text += f"**{lang_manager.get(lang, 'guide.stop_reply')}**\n"
    text += f"{lang_manager.get(lang, 'guide.stop_reply_text')}\n\n"
    text += f"**{lang_manager.get(lang, 'guide.summary')}**\n"
    text += f"• {lang_manager.get(lang, 'guide.summary_buffer')}\n"
    text += f"• {lang_manager.get(lang, 'guide.summary_reply')}\n"
    text += f"• {lang_manager.get(lang, 'guide.summary_stop')}\n\n"
    text += f"{lang_manager.get(lang, 'guide.disclaimer_title')}\n"
    text += f"{lang_manager.get(lang, 'guide.disclaimer_text')}"
    
    kb = [[InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data="back")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def admin_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    lang = get_user_language(uid)
    if not is_admin(update.effective_user.id):
        if update.message:
            await update.message.reply_text(lang_manager.get(lang, 'admin.not_admin'))
        else:
            await update.callback_query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    with db.session() as s:
        all_users = s.query(User).all()
        approved_users = s.query(User).filter_by(status="approved").all()
        banned_users = s.query(User).filter_by(is_banned=True).all()
        pending_users = s.query(User).filter_by(status="pending").all()
        admins = s.query(User).filter_by(is_admin=True).all()
        channels = s.query(MandatoryChannel).all()
        
        # Count logged in users
        logged_in_ids = [acc.tg_user_id for acc in s.query(ConnectedAccount).all()]
        logged_in = len([u for u in approved_users if u.tg_user_id in logged_in_ids])
        not_logged_in = len(approved_users) - logged_in
    
    kb = [
        [InlineKeyboardButton(f"{lang_manager.get(lang, 'admin.users')} ({len(approved_users)} ta)", callback_data="list_users")],
        [InlineKeyboardButton(f"{lang_manager.get(lang, 'admin.banned')} ({len(banned_users)} ta)", callback_data="list_banned")],
        [InlineKeyboardButton(f"{lang_manager.get(lang, 'admin.admins')} ({len(admins)} ta)", callback_data="list_admins")],
        [InlineKeyboardButton(f"📢 Kanallar ({len(channels)} ta)", callback_data="list_channels")],
    ]
    
    text = lang_manager.get(lang, 'admin.panel') + "\n\n"
    text += "📊 **Statistika:**\n"
    text += f"👥 Jami foydalanuvchilar: {len(all_users)} ta\n"
    text += f"✅ Tasdiqlanganlar: {len(approved_users)} ta\n"
    text += f"⏳ Tasdiqlash kutayotganlar: {len(pending_users)} ta\n"
    text += f"🚫 Ban qilinganlar: {len(banned_users)} ta\n"
    text += f"📝 Akkaunt ulaganlar: {logged_in} ta\n"
    text += f"❓ Akkaunt ulamaganlar: {not_logged_in} ta\n"
    
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def admin_list_channels(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    lang = get_user_language(uid)
    if not is_admin(query.from_user.id):
        await query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    await query.answer()
    
    with db.session() as s:
        channels = s.query(MandatoryChannel).all()
    
    kb = []
    for channel in channels:
        kb.append([InlineKeyboardButton(f"📢 {channel.channel_title or channel.channel_username}", callback_data=f"channel_detail_{channel.id}")])
    
    kb.append([InlineKeyboardButton("➕ Kanal qo'shish", callback_data="add_channel")])
    kb.append([InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data="admin_menu")])
    
    text = f"📢 Kanallar ({len(channels)} ta):"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def admin_add_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    lang = get_user_language(uid)
    if not is_admin(query.from_user.id):
        await query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    await query.answer()
    STATE[uid] = {"step": "add_channel"}
    await query.edit_message_text("Kanal usernameini kiriting (masalan: @mychannel):")

async def admin_channel_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    lang = get_user_language(uid)
    if not is_admin(query.from_user.id):
        await query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    await query.answer()
    channel_id = int(query.data.split("_")[-1])
    
    with db.session() as s:
        channel = s.query(MandatoryChannel).filter_by(id=channel_id).first()
    
    if not channel:
        await query.answer("Kanal topilmadi!", show_alert=True)
        return
    
    text = f"📢 Kanal: {channel.channel_title or channel.channel_username}\n"
    text += f"Username: {channel.channel_username}\n"
    text += f"ID: {channel.channel_id}"
    
    kb = [
        [InlineKeyboardButton("🗑 O'chirish", callback_data=f"del_channel_{channel.id}")],
        [InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data="list_channels")]
    ]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def admin_delete_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    lang = get_user_language(uid)
    if not is_admin(query.from_user.id):
        await query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    await query.answer()
    channel_id = int(query.data.split("_")[-1])
    
    with db.session() as s:
        s.query(MandatoryChannel).filter_by(id=channel_id).delete()
        s.commit()
    
    await query.answer("Kanal o'chirildi!")
    await admin_list_channels(update, ctx)

async def admin_list_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    lang = get_user_language(uid)
    if not is_admin(query.from_user.id):
        await query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    await query.answer()
    
    with db.session() as s:
        users = s.query(User).filter_by(status="approved", is_banned=False).all()
    
    kb = []
    for user in users:
        display_name = f"@{user.username}" if user.username else f"ID: {user.tg_user_id}"
        kb.append([InlineKeyboardButton(f"✅ {display_name}", callback_data=f"admin_user_{user.tg_user_id}")])
    
    kb.append([InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data="admin_menu")])
    
    text = f"{lang_manager.get(lang, 'admin.users')} ({len(users)} ta):"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def admin_list_banned(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    lang = get_user_language(uid)
    if not is_admin(query.from_user.id):
        await query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    await query.answer()
    
    with db.session() as s:
        banned_users = s.query(User).filter_by(is_banned=True).all()
    
    kb = []
    for user in banned_users:
        display_name = f"@{user.username}" if user.username else f"ID: {user.tg_user_id}"
        kb.append([InlineKeyboardButton(f"🚫 {display_name}", callback_data=f"admin_user_{user.tg_user_id}")])
    
    kb.append([InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data="admin_menu")])
    
    text = f"{lang_manager.get(lang, 'admin.banned')} ({len(banned_users)} ta):"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def admin_list_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    lang = get_user_language(uid)
    if not is_admin(query.from_user.id):
        await query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    await query.answer()
    
    with db.session() as s:
        admins = s.query(User).filter_by(is_admin=True).all()
    
    kb = []
    for admin in admins:
        is_owner = admin.tg_user_id == cfg.owner_id
        display_name = f"@{admin.username}" if admin.username else f"ID: {admin.tg_user_id}"
        label = f"👑 {display_name} {lang_manager.get(lang, 'admin.owner')}" if is_owner else f"👑 {display_name}"
        if not is_owner:
            kb.append([InlineKeyboardButton(label, callback_data=f"admin_detail_{admin.tg_user_id}")])
        else:
            kb.append([InlineKeyboardButton(label, callback_data=f"admin_user_{admin.tg_user_id}")])
    
    kb.append([InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data="admin_menu")])
    
    text = f"{lang_manager.get(lang, 'admin.admins')} ({len(admins)} ta):"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def admin_user_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    lang = get_user_language(uid)
    if not is_admin(query.from_user.id):
        await query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    await query.answer()
    user_id = int(query.data.split("_")[-1])
    
    with db.session() as s:
        user = s.query(User).filter_by(tg_user_id=user_id).first()
        acc = s.query(ConnectedAccount).filter_by(tg_user_id=user_id).first()
        buf = s.query(Buffer).filter_by(tg_user_id=user_id).first()
    
    is_owner = user.tg_user_id == cfg.owner_id
    status = lang_manager.get(lang, 'admin.banned_status') if user.is_banned else lang_manager.get(lang, 'admin.active')
    admin_status = lang_manager.get(lang, 'admin.admin_role') if user.is_admin else lang_manager.get(lang, 'admin.user_role')
    phone = acc.phone_hint if acc else lang_manager.get(lang, 'admin.not_connected')
    delay = f"{acc.delay}s" if acc else "-"
    
    text = lang_manager.get(lang, 'admin.user_detail') + f"{user_id}\n"
    text += lang_manager.get(lang, 'admin.phone') + f"{phone}\n"
    text += lang_manager.get(lang, 'admin.delay') + f"{delay}\n"
    text += lang_manager.get(lang, 'admin.status') + f"{status}\n"
    text += lang_manager.get(lang, 'admin.role') + f"{admin_status}\n"
    
    if buf and buf.text:
        preview = buf.text[:100] + "..." if len(buf.text) > 100 else buf.text
        text += lang_manager.get(lang, 'admin.buffer_preview') + f"{preview}"
    else:
        text += lang_manager.get(lang, 'admin.buffer_empty')
    
    kb = []
    if not is_owner:
        kb.append([InlineKeyboardButton(lang_manager.get(lang, 'admin.view_buf'), callback_data=f"view_buf_{user_id}")])
        kb.append([InlineKeyboardButton(lang_manager.get(lang, 'admin.edit_buf'), callback_data=f"edit_buf_{user_id}")])
        kb.append([InlineKeyboardButton(lang_manager.get(lang, 'admin.del_buf'), callback_data=f"del_buf_{user_id}")])
        kb.append([InlineKeyboardButton(lang_manager.get(lang, 'admin.ban') if not user.is_banned else lang_manager.get(lang, 'admin.unban'), callback_data=f"toggle_ban_{user_id}")])
        if user.is_admin:
            kb.append([InlineKeyboardButton(lang_manager.get(lang, 'admin.remove_admin'), callback_data=f"remove_admin_{user_id}")])
        else:
            kb.append([InlineKeyboardButton(lang_manager.get(lang, 'admin.add_admin'), callback_data=f"add_admin_{user_id}")])
    kb.append([InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data="admin_menu")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def admin_view_buffer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    lang = get_user_language(uid)
    if not is_admin(query.from_user.id):
        await query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    await query.answer()
    user_id = int(query.data.split("_")[-1])
    
    with db.session() as s:
        buf = s.query(Buffer).filter_by(tg_user_id=user_id).first()
    
    if not buf or not buf.text:
        text = lang_manager.get(lang, 'buffer.empty')
    else:
        text = lang_manager.get(lang, 'buffer.view') + buf.text
    
    kb = [[InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data=f"admin_user_{user_id}")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def admin_edit_buffer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    lang = get_user_language(uid)
    if not is_admin(query.from_user.id):
        await query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    await query.answer()
    user_id = int(query.data.split("_")[-1])
    
    STATE[query.from_user.id] = {"step": "admin_edit_buf", "target_user_id": user_id}
    await query.edit_message_text(lang_manager.get(lang, 'buffer.new_prompt'))

async def admin_delete_buffer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    lang = get_user_language(uid)
    if not is_admin(query.from_user.id):
        await query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    await query.answer()
    user_id = int(query.data.split("_")[-1])
    
    with db.session() as s:
        s.query(Buffer).filter_by(tg_user_id=user_id).delete()
        s.commit()
    
    await query.answer(lang_manager.get(lang, 'buffer.deleted'))
    kb = [[InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data=f"admin_user_{user_id}")]]
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))

async def admin_toggle_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    lang = get_user_language(uid)
    if not is_admin(query.from_user.id):
        await query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    await query.answer()
    user_id = int(query.data.split("_")[-1])
    
    with db.session() as s:
        user = s.query(User).filter_by(tg_user_id=user_id).first()
        if user:
            user.is_banned = not user.is_banned
            s.commit()
            status = lang_manager.get(lang, 'admin.ban_success_end') if user.is_banned else lang_manager.get(lang, 'admin.unban_success_end')
            await query.answer(lang_manager.get(lang, 'admin.ban_success') + f"{user_id} " + status + "!")
            kb = [[InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data=f"admin_user_{user_id}")]]
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
        else:
            await query.answer(lang_manager.get(lang, 'admin.user_not_found'), show_alert=True)

async def admin_back_to_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    lang = get_user_language(uid)
    if not is_admin(query.from_user.id):
        await query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    await query.answer()
    # Call admin_menu with the same update (it now handles both message and callback)
    await admin_menu(update, ctx)

async def ban_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    lang = get_user_language(uid)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(lang_manager.get(lang, 'admin.not_admin'))
        return
    
    if not ctx.args:
        await update.message.reply_text(lang_manager.get(lang, 'admin.ban_usage'))
        return
    
    target = ctx.args[0]
    user_id = resolve_user(target)
    
    if user_id is None:
        await update.message.reply_text(lang_manager.get(lang, 'admin.user_not_found'))
        return
    
    with db.session() as s:
        user = s.query(User).filter_by(tg_user_id=user_id).first()
        if user:
            user.is_banned = True
            s.commit()
            await update.message.reply_text(lang_manager.get(lang, 'admin.ban_success') + f"{user_id}" + lang_manager.get(lang, 'admin.ban_success_end'))
        else:
            await update.message.reply_text(lang_manager.get(lang, 'admin.user_not_found'))

async def unban_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    lang = get_user_language(uid)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(lang_manager.get(lang, 'admin.not_admin'))
        return
    
    if not ctx.args:
        await update.message.reply_text(lang_manager.get(lang, 'admin.unban_usage'))
        return
    
    target = ctx.args[0]
    user_id = resolve_user(target)
    
    if user_id is None:
        await update.message.reply_text(lang_manager.get(lang, 'admin.user_not_found'))
        return
    
    with db.session() as s:
        user = s.query(User).filter_by(tg_user_id=user_id).first()
        if user:
            user.is_banned = False
            s.commit()
            await update.message.reply_text(lang_manager.get(lang, 'admin.unban_success') + f"{user_id}" + lang_manager.get(lang, 'admin.unban_success_end'))
        else:
            await update.message.reply_text(lang_manager.get(lang, 'admin.user_not_found'))

async def add_admin_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    lang = get_user_language(uid)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(lang_manager.get(lang, 'admin.not_admin'))
        return
    
    if not ctx.args:
        await update.message.reply_text(lang_manager.get(lang, 'admin.add_admin_usage'))
        return
    
    target = ctx.args[0]
    user_id = resolve_user(target)
    
    if user_id is None:
        await update.message.reply_text(lang_manager.get(lang, 'admin.user_not_found'))
        return
    
    if user_id == cfg.owner_id:
        await update.message.reply_text(lang_manager.get(lang, 'admin.owner_admin'))
        return
    
    with db.session() as s:
        user = s.query(User).filter_by(tg_user_id=user_id).first()
        if user:
            if user.is_admin:
                await update.message.reply_text(lang_manager.get(lang, 'admin.already_admin'))
            else:
                user.is_admin = True
                s.commit()
                await update.message.reply_text(lang_manager.get(lang, 'admin.add_admin_success') + f"{user_id}" + lang_manager.get(lang, 'admin.add_admin_success_end'))
        else:
            await update.message.reply_text(lang_manager.get(lang, 'admin.user_not_found'))

async def del_admin_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    lang = get_user_language(uid)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(lang_manager.get(lang, 'admin.not_admin'))
        return
    
    if not ctx.args:
        await update.message.reply_text(lang_manager.get(lang, 'admin.del_admin_usage'))
        return
    
    target = ctx.args[0]
    user_id = resolve_user(target)
    
    if user_id is None:
        await update.message.reply_text(lang_manager.get(lang, 'admin.user_not_found'))
        return
    
    if user_id == cfg.owner_id:
        await update.message.reply_text(lang_manager.get(lang, 'admin.owner_cannot_remove'))
        return
    
    with db.session() as s:
        user = s.query(User).filter_by(tg_user_id=user_id).first()
        if user:
            if not user.is_admin:
                await update.message.reply_text(lang_manager.get(lang, 'admin.not_admin_user'))
            else:
                user.is_admin = False
                s.commit()
                await update.message.reply_text(lang_manager.get(lang, 'admin.remove_admin_success') + f"{user_id}" + lang_manager.get(lang, 'admin.remove_admin_success_end'))
        else:
            await update.message.reply_text(lang_manager.get(lang, 'admin.user_not_found'))

async def admin_add_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    lang = get_user_language(uid)
    if not is_admin(query.from_user.id):
        await query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    await query.answer()
    user_id = int(query.data.split("_")[-1])
    
    if user_id == cfg.owner_id:
        await query.answer(lang_manager.get(lang, 'admin.owner_protected'), show_alert=True)
        return
    
    with db.session() as s:
        user = s.query(User).filter_by(tg_user_id=user_id).first()
        if user:
            user.is_admin = True
            s.commit()
            await query.answer(lang_manager.get(lang, 'admin.add_admin_success') + f"{user_id}" + lang_manager.get(lang, 'admin.add_admin_success_end'))
            kb = [[InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data=f"admin_user_{user_id}")]]
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
        else:
            await query.answer(lang_manager.get(lang, 'admin.user_not_found'), show_alert=True)

async def admin_remove_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    lang = get_user_language(uid)
    if not is_admin(query.from_user.id):
        await query.answer(lang_manager.get(lang, 'admin.not_admin_alert'), show_alert=True)
        return
    
    await query.answer()
    user_id = int(query.data.split("_")[-1])
    
    if user_id == cfg.owner_id:
        await query.answer(lang_manager.get(lang, 'admin.cannot_remove_owner'), show_alert=True)
        return
    
    with db.session() as s:
        user = s.query(User).filter_by(tg_user_id=user_id).first()
        if user:
            user.is_admin = False
            s.commit()
            await query.answer(lang_manager.get(lang, 'admin.remove_admin_success') + f"{user_id}" + lang_manager.get(lang, 'admin.remove_admin_success_end'))
            kb = [[InlineKeyboardButton(lang_manager.get(lang, 'menu.back'), callback_data=f"admin_user_{user_id}")]]
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
        else:
            await query.answer(lang_manager.get(lang, 'admin.user_not_found'), show_alert=True)

async def start_userbot(app):
    with db.session() as s:
        accounts = s.query(ConnectedAccount).all()
        account_data = [{"uid": a.tg_user_id, "enc": a.encrypted_session, "delay": a.delay, "random_delay": a.random_delay} for a in accounts]
    for acc in account_data:
        asyncio.create_task(run_telethon_client(acc["uid"], acc["enc"], acc["delay"], acc["random_delay"], app))

async def run_telethon_client(uid, enc_session, delay, random_delay, app):
    import random
    session_str = sender.crypto.dec(enc_session)
    client = TelegramClient(StringSession(session_str), cfg.api_id, cfg.api_hash)
    
    @client.on(events.NewMessage(outgoing=True))
    async def handler(event):
        if event.raw_text == ".bufer":
            reply_msg = await event.get_reply_message()
            with db.session() as s:
                buf = s.query(Buffer).filter_by(tg_user_id=uid).first()
                if not buf or not buf.text:
                    return
                buffer_text = buf.text
            
            if reply_msg:
                target_user = reply_msg.sender_id
                target_chat = event.chat_id
                with db.session() as s:
                    s.query(ActiveReply).filter_by(tg_user_id=uid, chat_id=target_chat).update({"is_active": False})
                    s.add(ActiveReply(tg_user_id=uid, target_user_id=target_user, chat_id=target_chat, is_active=True))
                    s.commit()
                await event.delete()
            else:
                await event.delete()
                try:
                    await client.send_message(event.chat_id, buffer_text, parse_mode='HTML')
                except FloodWaitError as e:
                    await app.bot.send_message(uid, f"⚠️ FloodWait: {e.seconds} soniya kuting.")

    @client.on(events.NewMessage(incoming=True))
    async def on_incoming(event):
        with db.session() as s:
            active = s.query(ActiveReply).filter_by(
                tg_user_id=uid, target_user_id=event.sender_id, chat_id=event.chat_id, is_active=True
            ).first()
            if active:
                buf = s.query(Buffer).filter_by(tg_user_id=uid).first()
                if buf and buf.text:
                    if random_delay:
                        # Random delay: base delay ± 20%
                        variation = delay * 0.2
                        d = random.uniform(delay - variation, delay + variation)
                        d = max(0.04, min(0.5, d))  # Keep within bounds
                    else:
                        d = delay
                    try:
                        await asyncio.sleep(d)
                        await client.send_message(event.chat_id, buf.text, reply_to=event.id, parse_mode='HTML')
                    except FloodWaitError as e:
                        with db.session() as s:
                            active.is_active = False
                            s.commit()
                        await app.bot.send_message(uid, f"⚠️ FloodWait. Reply to'xtatildi.")

    @client.on(events.NewMessage(outgoing=True, pattern=r"\.stop"))
    async def stop_handler(event):
        with db.session() as s:
            s.query(ActiveReply).filter_by(tg_user_id=uid, chat_id=event.chat_id).update({"is_active": False})
            s.commit()
        await event.delete()
        await app.bot.send_message(uid, "🛑 Reply to'xtatildi.")
    
    await client.start()
    log.info(f"Userbot ulandi: {uid}")

async def main_app():
    # Run migrations on startup
    run_migrations()
    
    app = Application.builder().token(cfg.bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_menu))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("add_admin", add_admin_command))
    app.add_handler(CommandHandler("del_admin", del_admin_command))
    app.add_handler(CallbackQueryHandler(owner_approve, pattern="^(appr|rej)_"))
    app.add_handler(CallbackQueryHandler(init_language, pattern="^init_lang_"))
    app.add_handler(CallbackQueryHandler(check_subscription, pattern="^check_subscription_"))
    app.add_handler(CallbackQueryHandler(on_login, pattern="^login$"))
    app.add_handler(CallbackQueryHandler(on_buf_view, pattern="^buf_view$"))
    app.add_handler(CallbackQueryHandler(on_buf_add, pattern="^buf_add$"))
    app.add_handler(CallbackQueryHandler(on_buf_del, pattern="^buf_del$"))
    app.add_handler(CallbackQueryHandler(on_set_delay, pattern="^set_delay$"))
    app.add_handler(CallbackQueryHandler(toggle_random_delay, pattern="^toggle_random_delay$"))
    app.add_handler(CallbackQueryHandler(change_delay, pattern="^change_delay$"))
    app.add_handler(CallbackQueryHandler(set_language, pattern="^set_language$"))
    app.add_handler(CallbackQueryHandler(change_language, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(show_guide, pattern="^show_guide$"))
    app.add_handler(CallbackQueryHandler(on_back, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(admin_list_users, pattern="^list_users$"))
    app.add_handler(CallbackQueryHandler(admin_list_banned, pattern="^list_banned$"))
    app.add_handler(CallbackQueryHandler(admin_list_admins, pattern="^list_admins$"))
    app.add_handler(CallbackQueryHandler(admin_user_detail, pattern="^admin_user_"))
    app.add_handler(CallbackQueryHandler(admin_user_detail, pattern="^admin_detail_"))
    app.add_handler(CallbackQueryHandler(admin_view_buffer, pattern="^view_buf_"))
    app.add_handler(CallbackQueryHandler(admin_edit_buffer, pattern="^edit_buf_"))
    app.add_handler(CallbackQueryHandler(admin_delete_buffer, pattern="^del_buf_"))
    app.add_handler(CallbackQueryHandler(admin_toggle_ban, pattern="^toggle_ban_"))
    app.add_handler(CallbackQueryHandler(admin_add_admin, pattern="^add_admin_"))
    app.add_handler(CallbackQueryHandler(admin_remove_admin, pattern="^remove_admin_"))
    app.add_handler(CallbackQueryHandler(admin_back_to_menu, pattern="^admin_menu$"))
    app.add_handler(CallbackQueryHandler(admin_back_to_menu, pattern="^back_to_main$"))
    app.add_handler(CallbackQueryHandler(admin_list_channels, pattern="^list_channels$"))
    app.add_handler(CallbackQueryHandler(admin_add_channel, pattern="^add_channel$"))
    app.add_handler(CallbackQueryHandler(admin_channel_detail, pattern="^channel_detail_"))
    app.add_handler(CallbackQueryHandler(admin_delete_channel, pattern="^del_channel_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    
    asyncio.create_task(start_userbot(app))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    log.info("Bot ishga tushdi")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main_app())
