#!/usr/bin/env python3
"""
To'liq Telegram Bot - Django bilan integratsiya qilingan
"""

import os
import sys
import django
import logging
import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path

# Django sozlamalarini o'rnatish
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

# Admin chat ID ni global o'zgaruvchi sifatida e'lon qilish
ADMIN_CHAT_ID = None

try:
    django.setup()
    from django.contrib.auth.models import User
    from store.models import Product, Category, Order, Courier, OrderStatus
    from django.db import transaction
    DJANGO_AVAILABLE = True
    print("✅ Django muvaffaqiyatli yuklandi")
except Exception as e:
    print(f"⚠️ Django setup error: {e}")
    print("⚠️ Emergency mode ishga tushdi")
    DJANGO_AVAILABLE = False
    # Emergency data structures
    class EmergencyOrder:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    
    class EmergencyCourier:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    
    Order = EmergencyOrder
    Courier = EmergencyCourier
    OrderStatus = type('OrderStatus', (), {
        'PENDING': 'pending',
        'ACCEPTED': 'accepted',
        'DELIVERING': 'delivering',
        'DELIVERED': 'delivered',
        'CANCELLED': 'cancelled'
    })()

from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    WebAppInfo,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    MenuButtonWebApp,
    BotCommand
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

# Logging sozlamalari
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot konfiguratsiyasi
BOT_TOKEN = "8448936121:AAFMFbhcfyKkie5NVtTL-1kmtryGoa6Ndt4"
ADMIN_USERNAMES = ["Defender_0925", "admin"]  # @ belgisiz

# Conversation holatlari
(
    MAIN_MENU,
    COURIER_REGISTER,
    COURIER_PHONE,
    COURIER_CONFIRM,
    COURIER_DASHBOARD,
    ADMIN_PANEL,
    ADMIN_ORDERS,
    ADMIN_STATISTICS,
    ADMIN_COURIERS,
    VIEW_ORDER_DETAILS,
    ACCEPT_ORDER,
    DELIVER_ORDER,
) = range(12)

# Vaqtinchalik ma'lumotlar uchun
user_data = {}

class DatabaseManager:
    """Django mavjud bo'lmaganda emergency database"""
    
    def __init__(self):
        self.conn = sqlite3.connect('bot_data.db', check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS couriers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                full_name TEXT,
                phone TEXT,
                status TEXT DEFAULT 'active',
                rating REAL DEFAULT 5.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE,
                customer_name TEXT,
                customer_phone TEXT,
                customer_address TEXT,
                order_data TEXT,
                total_amount REAL,
                status TEXT DEFAULT 'pending',
                courier_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                delivered_at TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                telegram_id INTEGER UNIQUE
            )
        ''')
        
        # Adminlarni qo'shish
        for admin in ADMIN_USERNAMES:
            cursor.execute('''
                INSERT OR IGNORE INTO admin_users (username) VALUES (?)
            ''', (admin,))
        
        self.conn.commit()
        print("✅ Emergency database yaratildi")
    
    def add_courier(self, telegram_id, full_name, phone):
        cursor = self.conn.cursor()
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO couriers (telegram_id, full_name, phone)
                VALUES (?, ?, ?)
            ''', (telegram_id, full_name, phone))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding courier: {e}")
            return False
    
    def get_courier(self, telegram_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM couriers WHERE telegram_id = ?', (telegram_id,))
        row = cursor.fetchone()
        if row:
            return {
                'id': row[0],
                'telegram_id': row[1],
                'full_name': row[2],
                'phone': row[3],
                'status': row[4],
                'rating': row[5],
                'created_at': row[6]
            }
        return None
    
    def add_order(self, order_data):
        cursor = self.conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO orders (order_id, customer_name, customer_phone, 
                customer_address, order_data, total_amount, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                order_data.get('order_id', f"ORD{int(datetime.now().timestamp())}"),
                order_data.get('customer_name', ''),
                order_data.get('customer_phone', ''),
                order_data.get('customer_address', ''),
                json.dumps(order_data.get('items', [])),
                order_data.get('total_amount', 0),
                'pending'
            ))
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error adding order: {e}")
            return None
    
    def get_pending_orders(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM orders WHERE status = "pending" ORDER BY created_at DESC LIMIT 10')
        rows = cursor.fetchall()
        orders = []
        for row in rows:
            orders.append({
                'id': row[0],
                'order_id': row[1],
                'customer_name': row[2],
                'customer_phone': row[3],
                'customer_address': row[4],
                'order_data': json.loads(row[5]) if row[5] else [],
                'total_amount': row[6],
                'status': row[7],
                'courier_id': row[8],
                'created_at': row[9]
            })
        return orders

# Emergency database
db_manager = DatabaseManager()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botni ishga tushirish"""
    user = update.effective_user
    user_id = user.id
    username = user.username or ""
    
    # Foydalanuvchi ma'lumotlarini saqlash
    context.user_data['user_id'] = user_id
    context.user_data['username'] = username
    
    logger.info(f"User started bot: {user_id} - {username}")
    
    # Admin tekshirish
    is_admin = await check_if_admin(username)
    context.user_data['is_admin'] = is_admin
    
    # Agar admin bo'lsa, chat_id ni saqlash
    if is_admin:
        global ADMIN_CHAT_ID
        if ADMIN_CHAT_ID is None:
            ADMIN_CHAT_ID = user_id
            print(f"✅ Admin chat ID saqlandi: {ADMIN_CHAT_ID}")
    
    # Kuryer tekshirish
    is_courier = await check_if_courier(user_id)
    context.user_data['is_courier'] = is_courier
    
    # Asosiy menyu
    keyboard = [
        [
            InlineKeyboardButton(
                "🛍 Online Do'kon", 
                web_app=WebAppInfo(url="https://azizbekkhakimov87.github.io/mubotmini/")
            )
        ],
        [
            InlineKeyboardButton("📞 Admin bilan bog'lanish", 
                               callback_data='contact_admin')
        ],
        [
            InlineKeyboardButton("🚚 Kuryer paneli", 
                               callback_data='courier_panel')
        ]
    ]
    
    # Admin panel qo'shish
    if is_admin:
        keyboard.append([
            InlineKeyboardButton("🔐 Admin panel", 
                               callback_data='admin_panel')
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = f"""
👋 Assalomu alaykum {user.first_name}!

✨ Xush kelibsiz! Onlayn do'konimizga.

🛍 **Online Do'kon** - Mahsulotlarni ko'rish va buyurtma berish
📞 **Admin bilan bog'lanish** - Savol va takliflaringiz bo'lsa
🚚 **Kuryer paneli** - Kuryer sifatida ro'yxatdan o'tish
"""
    
    if is_admin:
        welcome_text += "\n🔐 **Admin panel** - Botni boshqarish"
    
    if update.message:
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.callback_query.edit_message_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    return MAIN_MENU

async def check_if_admin(username: str) -> bool:
    """Foydalanuvchini admin ekanligini tekshirish"""
    if not username:
        return False
    
    # Django orqali tekshirish
    if DJANGO_AVAILABLE:
        try:
            user = User.objects.filter(username=username).first()
            if user and user.is_staff:
                return True
        except Exception as e:
            logger.error(f"Django admin check error: {e}")
    
    # Emergency tekshirish
    return username in ADMIN_USERNAMES

async def check_if_courier(telegram_id: int) -> bool:
    """Foydalanuvchini kuryer ekanligini tekshirish"""
    # Django orqali tekshirish
    if DJANGO_AVAILABLE:
        try:
            courier = Courier.objects.filter(telegram_id=telegram_id).first()
            return courier is not None
        except Exception as e:
            logger.error(f"Django courier check error: {e}")
    
    # Emergency tekshirish
    courier = db_manager.get_courier(telegram_id)
    return courier is not None

async def contact_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin bilan bog'lanish"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📞 **Admin bilan bog'lanish**\n\n"
        "Savol, taklif yoki shikoyatlaringiz bo'lsa, "
        "quyidagi admin bilan bog'lanishingiz mumkin:\n\n"
        "👤 Admin: @Defender_0925\n"
        "📩 Shaxsiy xabar yuboring yoki bu yerda yozing.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Xabar yozish", 
                                 url="https://t.me/Defender_0925")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data='back_to_main')]
        ])
    )

async def courier_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kuryer paneli"""
    query = update.callback_query
    await query.answer()
    
    user_id = context.user_data.get('user_id')
    
    # Kuryer ekanligini tekshirish
    if await check_if_courier(user_id):
        # Kuryer dashboardini ko'rsatish
        await show_courier_dashboard(update, context)
        return COURIER_DASHBOARD
    else:
        # Ro'yxatdan o'tish
        await query.edit_message_text(
            "🚚 **Kuryer paneli**\n\n"
            "Kuryer sifatida ishlash uchun ro'yxatdan o'ting.\n"
            "Ism familiyangizni yuboring:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Orqaga", callback_data='back_to_main')]
            ])
        )
        return COURIER_REGISTER

async def courier_register_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kuryer ismini qabul qilish"""
    if update.message:
        full_name = update.message.text
        context.user_data['courier_full_name'] = full_name
        
        # Telefon raqam so'rash
        contact_keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        await update.message.reply_text(
            f"👤 Ism familiya: {full_name}\n\n"
            f"Endi telefon raqamingizni yuboring:",
            reply_markup=contact_keyboard
        )
        
        return COURIER_PHONE
    return MAIN_MENU

async def courier_register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kuryer telefon raqamini qabul qilish"""
    if update.message:
        contact = update.message.contact
        if contact:
            phone_number = contact.phone_number
            user_id = contact.user_id
        else:
            phone_number = update.message.text
            user_id = update.effective_user.id
        
        context.user_data['courier_phone'] = phone_number
        
        # Tasdiqlash
        keyboard = [
            [
                InlineKeyboardButton("✅ Tasdiqlash", callback_data='confirm_courier'),
                InlineKeyboardButton("❌ Bekor qilish", callback_data='cancel_courier')
            ]
        ]
        
        await update.message.reply_text(
            f"📋 **Ro'yxatdan o'tish ma'lumotlari:**\n\n"
            f"👤 Ism familiya: {context.user_data['courier_full_name']}\n"
            f"📱 Telefon: {phone_number}\n\n"
            f"Ma'lumotlar to'g'rimi?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
        return COURIER_CONFIRM
    return MAIN_MENU

async def confirm_courier_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kuryer ro'yxatdan o'tishni tasdiqlash"""
    query = update.callback_query
    await query.answer()
    
    user_id = context.user_data.get('user_id')
    full_name = context.user_data.get('courier_full_name')
    phone = context.user_data.get('courier_phone')
    
    # Django orqali saqlash
    if DJANGO_AVAILABLE:
        try:
            from django.db import transaction
            with transaction.atomic():
                courier, created = Courier.objects.get_or_create(
                    telegram_id=user_id,
                    defaults={
                        'full_name': full_name,
                        'phone': phone,
                        'status': 'active',
                        'rating': 5.0
                    }
                )
                if not created:
                    courier.full_name = full_name
                    courier.phone = phone
                    courier.save()
            print(f"✅ Kuryer Django orqali saqlandi: {full_name}")
        except Exception as e:
            logger.error(f"Django courier save error: {e}")
            # Emergency saqlash
            db_manager.add_courier(user_id, full_name, phone)
            print(f"✅ Kuryer emergency DB ga saqlandi: {full_name}")
    else:
        # Emergency saqlash
        db_manager.add_courier(user_id, full_name, phone)
        print(f"✅ Kuryer emergency DB ga saqlandi: {full_name}")
    
    await query.edit_message_text(
        "✅ **Muvaffaqiyatli ro'yxatdan o'tdingiz!**\n\n"
        "Endi siz kuryer sifatida ishlay olasiz.\n"
        "Buyurtmalarni qabul qilish uchun dashboardga o'ting.",
        parse_mode='Markdown'
    )
    
    # Dashboardga o'tish
    context.user_data['is_courier'] = True
    await show_courier_dashboard(update, context)
    return COURIER_DASHBOARD

async def show_courier_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kuryer dashboardini ko'rsatish"""
    user_id = context.user_data.get('user_id')
    
    # Buyurtmalarni olish
    pending_orders = []
    if DJANGO_AVAILABLE:
        try:
            pending_orders = await get_pending_orders()
        except:
            pending_orders = db_manager.get_pending_orders()
    else:
        pending_orders = db_manager.get_pending_orders()
    
    text = f"🚚 **Kuryer Dashboard**\n\n"
    text += f"📊 **Statistika:**\n"
    text += f"• Navbatdagi buyurtmalar: {len(pending_orders)}\n\n"
    
    if pending_orders:
        text += "🆕 **Yangi buyurtmalar:**\n"
        for i, order in enumerate(pending_orders[:3], 1):
            text += f"{i}. #{order.get('order_id', order.get('id'))} - {order.get('total_amount', 0)} so'm\n"
    else:
        text += "🔄 Hozirda yangi buyurtmalar yo'q\n"
    
    keyboard = []
    
    if pending_orders:
        keyboard.append([InlineKeyboardButton("📦 Buyurtma qabul qilish", callback_data='accept_order_list')])
    
    keyboard.append([InlineKeyboardButton("📊 Statistika", callback_data='courier_stats')])
    keyboard.append([InlineKeyboardButton("🔄 Yangilash", callback_data='refresh_dashboard')])
    keyboard.append([InlineKeyboardButton("🔙 Asosiy menyu", callback_data='back_to_main')])
    
    if hasattr(update, 'callback_query'):
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def get_pending_orders():
    """Navbatdagi buyurtmalarni olish"""
    if DJANGO_AVAILABLE:
        try:
            orders = Order.objects.filter(status='pending').order_by('-created_at')[:10]
            result = []
            for order in orders:
                result.append({
                    'id': order.id,
                    'order_id': getattr(order, 'order_number', str(order.id)),
                    'customer_name': getattr(order, 'customer_name', 'Noma\'lum'),
                    'total_amount': getattr(order, 'total_price', 0),
                    'address': getattr(order, 'delivery_address', 'Noma\'lum')
                })
            return result
        except Exception as e:
            logger.error(f"Django get orders error: {e}")
            return db_manager.get_pending_orders()
    
    # Emergency buyurtmalar
    return db_manager.get_pending_orders()

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin paneli"""
    query = update.callback_query
    await query.answer()
    
    # Adminlikni qayta tekshirish
    if not context.user_data.get('is_admin'):
        await query.edit_message_text(
            "❌ Siz admin emassiz!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Orqaga", callback_data='back_to_main')]
            ])
        )
        return MAIN_MENU
    
    # Statistika olish
    stats = await get_admin_statistics()
    
    text = "🔐 **Admin Panel**\n\n"
    text += f"📊 **Statistika:**\n"
    text += f"• Jami buyurtmalar: {stats.get('total_orders', 0)}\n"
    text += f"• Navbatdagi buyurtmalar: {stats.get('pending_orders', 0)}\n"
    text += f"• Faol kuryerlar: {stats.get('active_couriers', 0)}\n\n"
    text += "Quyidagi bo'limlardan birini tanlang:"
    
    keyboard = [
        [InlineKeyboardButton("📦 Buyurtmalar", callback_data='admin_orders')],
        [InlineKeyboardButton("🚚 Kuryerlar", callback_data='admin_couriers')],
        [InlineKeyboardButton("📊 Statistika", callback_data='full_stats')],
        [InlineKeyboardButton("🔙 Asosiy menyu", callback_data='back_to_main')]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    
    return ADMIN_PANEL

async def get_admin_statistics():
    """Admin statistikasini olish"""
    stats = {
        'total_orders': 0,
        'pending_orders': 0,
        'active_couriers': 0,
        'today_income': 0
    }
    
    if DJANGO_AVAILABLE:
        try:
            from django.db.models import Count, Sum
            from django.utils import timezone
            
            # Buyurtmalar
            stats['total_orders'] = Order.objects.count()
            stats['pending_orders'] = Order.objects.filter(status='pending').count()
            
            # Kuryerlar
            stats['active_couriers'] = Courier.objects.filter(status='active').count()
            
        except Exception as e:
            logger.error(f"Django stats error: {e}")
            # Emergency stats
            cursor = db_manager.conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM orders')
            stats['total_orders'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM orders WHERE status = "pending"')
            stats['pending_orders'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM couriers WHERE status = "active"')
            stats['active_couriers'] = cursor.fetchone()[0]
    else:
        # Emergency stats
        cursor = db_manager.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM orders')
        stats['total_orders'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM orders WHERE status = "pending"')
        stats['pending_orders'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM couriers WHERE status = "active"')
        stats['active_couriers'] = cursor.fetchone()[0]
    
    return stats

async def web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Web App orqali kelgan buyurtmani qabul qilish"""
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        logger.info(f"Web app data received: {data}")
        
        # Buyurtma ma'lumotlarini saqlash
        order_data = {
            'customer_name': data.get('name', ''),
            'customer_phone': data.get('phone', ''),
            'customer_address': data.get('address', ''),
            'items': data.get('items', []),
            'total_amount': data.get('total', 0),
            'order_id': f"ORD{int(datetime.now().timestamp())}"
        }
        
        print(f"📦 Yangi buyurtma: {order_data['order_id']}")
        
        # Django orqali saqlash
        order_id = None
        if DJANGO_AVAILABLE:
            try:
                order = Order.objects.create(
                    order_number=order_data['order_id'],
                    customer_name=order_data['customer_name'],
                    customer_phone=order_data['customer_phone'],
                    delivery_address=order_data['customer_address'],
                    order_items=json.dumps(order_data['items']),
                    total_price=order_data['total_amount'],
                    status='pending'
                )
                order_id = order.id
                print(f"✅ Buyurtma Django ga saqlandi: {order_id}")
            except Exception as e:
                logger.error(f"Django order save error: {e}")
                order_id = db_manager.add_order(order_data)
                print(f"✅ Buyurtma emergency DB ga saqlandi: {order_id}")
        else:
            order_id = db_manager.add_order(order_data)
            print(f"✅ Buyurtma emergency DB ga saqlandi: {order_id}")
        
        # Xabar yuborish
        await update.message.reply_text(
            f"✅ **Buyurtma qabul qilindi!**\n\n"
            f"🆔 Buyurtma raqami: {order_data['order_id']}\n"
            f"👤 Mijoz: {order_data['customer_name']}\n"
            f"📱 Telefon: {order_data['customer_phone']}\n"
            f"💰 Jami summa: {order_data['total_amount']} so'm\n\n"
            f"Kuryer tez orada siz bilan bog'lanadi.",
            parse_mode='Markdown'
        )
        
        # Adminlarga xabar yuborish
        global ADMIN_CHAT_ID
        if ADMIN_CHAT_ID:
            try:
                admin_text = f"🆕 **Yangi buyurtma!**\n\n"
                admin_text += f"ID: {order_data['order_id']}\n"
                admin_text += f"Mijoz: {order_data['customer_name']}\n"
                admin_text += f"Telefon: {order_data['customer_phone']}\n"
                admin_text += f"Manzil: {order_data['customer_address'][:50]}...\n"
                admin_text += f"Summa: {order_data['total_amount']} so'm\n"
                
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=admin_text,
                    parse_mode='Markdown'
                )
                print(f"📨 Adminga xabar yuborildi: {ADMIN_CHAT_ID}")
            except Exception as e:
                logger.error(f"Admin notification error: {e}")
        
        return MAIN_MENU
        
    except Exception as e:
        logger.error(f"Web app data processing error: {e}")
        await update.message.reply_text(
            "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=ReplyKeyboardRemove()
        )
        return MAIN_MENU

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asosiy menyuga qaytish"""
    query = update.callback_query
    await query.answer()
    
    # Asosiy menyuni ko'rsatish
    await start(update, context)
    return MAIN_MENU

async def cancel_courier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kuryer ro'yxatdan o'tishni bekor qilish"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "Ro'yxatdan o'tish bekor qilindi.",
        reply_markup=ReplyKeyboardRemove()
    )
    
    await start(update, context)
    return MAIN_MENU

async def refresh_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dashboardni yangilash"""
    query = update.callback_query
    await query.answer()
    
    await show_courier_dashboard(update, context)
    return COURIER_DASHBOARD

async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin uchun buyurtmalar ro'yxati"""
    query = update.callback_query
    await query.answer()
    
    # Buyurtmalarni olish
    orders = db_manager.get_pending_orders()
    
    text = "📦 **Buyurtmalar ro'yxati**\n\n"
    
    if orders:
        for i, order in enumerate(orders[:10], 1):
            text += f"{i}. #{order['order_id']}\n"
            text += f"   👤 {order['customer_name']}\n"
            text += f"   📱 {order['customer_phone']}\n"
            text += f"   💰 {order['total_amount']} so'm\n"
            text += f"   📍 {order['customer_address'][:30]}...\n\n"
    else:
        text += "📭 Hozirda buyurtmalar yo'q\n"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Yangilash", callback_data='admin_orders')],
        [InlineKeyboardButton("🔙 Admin panel", callback_data='admin_panel')]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xatolarni qayta ishlash"""
    logger.error(f"Xatolik yuz berdi: {context.error}")
    
    if update and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring."
            )
        except:
            pass

def main():
    """Botni ishga tushirish"""
    print("🤖 Bot ishga tushmoqda...")
    print(f"📞 Admin: @Defender_0925")
    print(f"🛍 Web App: https://azizbekkhakimov87.github.io/mubotmini/")
    print("=" * 50)
    
    # Bot ilovasini yaratish
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Xatolik handler
    application.add_error_handler(error_handler)
    
    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(contact_admin, pattern='^contact_admin$'),
                CallbackQueryHandler(courier_panel, pattern='^courier_panel$'),
                CallbackQueryHandler(admin_panel, pattern='^admin_panel$'),
                CallbackQueryHandler(back_to_main, pattern='^back_to_main$'),
                CallbackQueryHandler(confirm_courier_registration, pattern='^confirm_courier$'),
                CallbackQueryHandler(cancel_courier, pattern='^cancel_courier$'),
                CallbackQueryHandler(refresh_dashboard, pattern='^refresh_dashboard$'),
                CallbackQueryHandler(admin_orders, pattern='^admin_orders$'),
                CallbackQueryHandler(admin_panel, pattern='^admin_couriers$|^full_stats$'),
            ],
            COURIER_REGISTER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, courier_register_name),
                CallbackQueryHandler(back_to_main, pattern='^back_to_main$'),
            ],
            COURIER_PHONE: [
                MessageHandler(filters.CONTACT | filters.TEXT, courier_register_phone),
            ],
            COURIER_CONFIRM: [
                CallbackQueryHandler(confirm_courier_registration, pattern='^confirm_courier$'),
                CallbackQueryHandler(cancel_courier, pattern='^cancel_courier$'),
            ],
            COURIER_DASHBOARD: [
                CallbackQueryHandler(show_courier_dashboard, pattern='^courier_stats$'),
                CallbackQueryHandler(back_to_main, pattern='^back_to_main$'),
            ],
            ADMIN_PANEL: [
                CallbackQueryHandler(admin_orders, pattern='^admin_orders$'),
                CallbackQueryHandler(admin_panel, pattern='^admin_'),
                CallbackQueryHandler(back_to_main, pattern='^back_to_main$'),
            ],
        },
        fallbacks=[CommandHandler('start', start)],
    )
    
    # Web App data handler
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data))
    
    # Conversation handler
    application.add_handler(conv_handler)
    
    # Start bot
    print("✅ Bot muvaffaqiyatli ishga tushdi!")
    print("⏳ Yangi foydalanuvchilar kutilyapti...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()