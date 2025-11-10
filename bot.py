import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import sqlite3
from datetime import datetime, timedelta
import os
import logging
import time
import threading
from flask import Flask, request, jsonify
import pytz
import requests

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Получение переменных окружения
API_TOKEN = os.environ.get('BOT_TOKEN')
PORT = int(os.environ.get('PORT', 10000))
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')

if not API_TOKEN:
    logger.error("❌ BOT_TOKEN not found")
    exit(1)

logger.info("✅ Bot token loaded")

# Московский часовой пояс
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Инициализация бота и Flask
bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__)

# Состояния для FSM
user_states = {}

# ========== БАЗА ДАННЫХ ==========
def get_db_connection():
    try:
        conn = sqlite3.connect('/tmp/time_tracker.db', check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error(f"❌ Database error: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if not conn: return
        
    cur = conn.cursor()
    try:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                activity_name TEXT,
                category TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                duration INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER PRIMARY KEY,
                current_activity TEXT,
                activity_start TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database init error: {e}")
    finally:
        cur.close()
        conn.close()

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С ДАННЫМИ ==========
def get_moscow_time():
    """Возвращает текущее московское время"""
    return datetime.now(MOSCOW_TZ)

def format_moscow_time(dt=None):
    """Форматирует время в московский формат"""
    if dt is None:
        dt = get_moscow_time()
    elif dt.tzinfo is None:
        dt = MOSCOW_TZ.localize(dt)
    return dt.strftime('%H:%M:%S')

def format_time_short(dt):
    """Форматирует время в короткий формат (ЧЧ:ММ)"""
    if dt.tzinfo is None:
        dt = MOSCOW_TZ.localize(dt)
    return dt.strftime('%H:%M')

def parse_time_input(time_str):
    """Парсит ввод времени пользователя"""
    try:
        # Пробуем разные форматы времени
        time_formats = ['%H:%M', '%H:%M:%S', '%H.%M', '%H.%M.%S']
        
        for fmt in time_formats:
            try:
                # Создаем naive datetime с сегодняшней датой
                naive_dt = datetime.strptime(time_str, fmt)
                # Добавляем московский часовой пояс
                localized_dt = MOSCOW_TZ.localize(naive_dt.replace(
                    year=get_moscow_time().year,
                    month=get_moscow_time().month, 
                    day=get_moscow_time().day
                ))
                return localized_dt
            except ValueError:
                continue
                
        return None
    except Exception as e:
        logger.error(f"Time parse error: {e}")
        return None

def register_user(user_id: int, username: str):
    conn = get_db_connection()
    if not conn: return False
    cur = conn.cursor()
    try:
        cur.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
        conn.commit()
        return True
    except: return False
    finally: cur.close(); conn.close()

def save_activity(user_id: int, activity_name: str, start_time: datetime, end_time: datetime):
    conn = get_db_connection()
    if not conn: return False
    cur = conn.cursor()
    try:
        category = "Другое" if activity_name.startswith("Другое:") else get_activity_category(activity_name)
        duration = int((end_time - start_time).total_seconds())
        cur.execute('INSERT INTO activities (user_id, activity_name, category, start_time, end_time, duration) VALUES (?, ?, ?, ?, ?, ?)', 
                   (user_id, activity_name, category, start_time, end_time, duration))
        conn.commit()
        logger.info(f"✅ Saved: {activity_name} - {duration}s")
        return True
    except Exception as e:
        logger.error(f"Save error: {e}")
        return False
    finally: cur.close(); conn.close()

def get_activity_category(activity_name: str) -> str:
    categories = {
        "Проснулся": "Сон", "Полистал ленту": "Развлечения", "В туалет": "Гигиена",
        "Гигиена": "Гигиена", "Завтрак": "Еда", "Одеваюсь": "Подготовка", "Домой": "Переход",
        "Сесть за комп": "Компьютер", "Игры": "Игры", "Учеба/ДЗ": "Учеба", 
        "Обед/Ужин": "Еда", "Отдых": "Развлечения", "Уборка": "Бытовые",
        "Вечерняя гигиена": "Гигиена", "Лег в кровать": "Отдых", 
        "Вечерний серфинг": "Развлечения", "Спать": "Сон",
        "Выхожу на учебу": "Учеба", "Иду гулять": "Отдых", "Время с близкими": "Социальное"
    }
    return categories.get(activity_name, "Другое")

def update_user_session(user_id: int, current_activity: str = None, activity_start: datetime = None):
    conn = get_db_connection()
    if not conn: return False
    cur = conn.cursor()
    try:
        cur.execute('SELECT * FROM user_sessions WHERE user_id = ?', (user_id,))
        if cur.fetchone():
            cur.execute('UPDATE user_sessions SET current_activity = ?, activity_start = ? WHERE user_id = ?', 
                       (current_activity, activity_start, user_id))
        else:
            cur.execute('INSERT INTO user_sessions (user_id, current_activity, activity_start) VALUES (?, ?, ?)', 
                       (user_id, current_activity, activity_start))
        conn.commit()
        return True
    except: return False
    finally: cur.close(); conn.close()

def get_user_session(user_id: int):
    conn = get_db_connection()
    if not conn: return None
    cur = conn.cursor()
    try:
        cur.execute('SELECT * FROM user_sessions WHERE user_id = ?', (user_id,))
        return cur.fetchone()
    except: return None
    finally: cur.close(); conn.close()

def get_detailed_statistics(user_id: int):
    """Получает детальную статистику с промежутками времени"""
    conn = get_db_connection()
    if not conn: return None
    
    cur = conn.cursor()
    try:
        # Получаем все активности за сегодня с временными промежутками
        cur.execute('''
            SELECT activity_name, start_time, end_time, duration 
            FROM activities 
            WHERE user_id = ? AND DATE(start_time) = DATE("now", "localtime")
            ORDER BY start_time
        ''', (user_id,))
        
        activities = cur.fetchall()
        
        # Получаем общее время
        cur.execute('''
            SELECT SUM(duration) as total_time 
            FROM activities 
            WHERE user_id = ? AND DATE(start_time) = DATE("now", "localtime")
        ''', (user_id,))
        
        total_time = cur.fetchone()['total_time'] or 0
        
        return activities, total_time
        
    except Exception as e:
        logger.error(f"Detailed stats error: {e}")
        return None, 0
    finally: 
        cur.close()
        conn.close()

def format_detailed_statistics(user_id: int):
    """Форматирует детальную статистику для отправки"""
    activities, total_time = get_detailed_statistics(user_id)
    
    if not activities:
        return "📊 За сегодня еще нет активностей"
    
    # Текущая дата
    today = get_moscow_time().strftime('%d.%m.%Y')
    
    stats_text = f"📊 **Детальная статистика за {today}**\n\n"
    
    # Группируем активности по имени для суммарного времени
    activity_totals = {}
    for activity in activities:
        name = activity['activity_name'].replace("Другое: ", "")
        if name not in activity_totals:
            activity_totals[name] = 0
        activity_totals[name] += activity['duration']
    
    # Выводим суммарное время по активностям
    stats_text += "**🕐 Суммарное время:**\n"
    for activity_name, total_duration in sorted(activity_totals.items(), key=lambda x: x[1], reverse=True):
        minutes = int(total_duration // 60)
        hours = int(minutes // 60)
        remaining_minutes = minutes % 60
        
        if hours > 0:
            time_str = f"{hours}ч {remaining_minutes}м"
        else:
            time_str = f"{minutes}м"
            
        stats_text += f"• {activity_name}: {time_str}\n"
    
    stats_text += "\n**📅 Детали по промежуткам:**\n"
    
    # Выводим детальные промежутки
    current_date = None
    for activity in activities:
        start_time = datetime.fromisoformat(activity['start_time'])
        end_time = datetime.fromisoformat(activity['end_time'])
        
        # Форматируем время
        start_str = format_time_short(start_time)
        end_str = format_time_short(end_time)
        
        activity_name = activity['activity_name'].replace("Другое: ", "")
        duration_minutes = int(activity['duration'] // 60)
        
        stats_text += f"• {start_str} - {end_str}: {activity_name} ({duration_minutes}м)\n"
    
    # Общее время
    total_minutes = int(total_time // 60)
    total_hours = int(total_minutes // 60)
    remaining_minutes = total_minutes % 60
    
    if total_hours > 0:
        total_time_str = f"{total_hours}ч {remaining_minutes}м"
    else:
        total_time_str = f"{total_minutes}м"
    
    stats_text += f"\n**🎯 Итого за день: {total_time_str}**"
    
    return stats_text

# ========== КЛАВИАТУРЫ ==========
def main_menu_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("🌅 Утро"), KeyboardButton("💻 День"), 
        KeyboardButton("🌙 Вечер"), KeyboardButton("📊 Статистика"),
        KeyboardButton("⏰ Добавить прошлое действие")
    )
    return keyboard

def morning_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("⏰ Проснулся"), KeyboardButton("📱 Полистал ленту"),
        KeyboardButton("🚽 В туалет"), KeyboardButton("🚿 Гигиена"),
        KeyboardButton("🍳 Завтрак"), KeyboardButton("👔 Одеваюсь"),
        KeyboardButton("🎒 Выхожу на учебу"), KeyboardButton("🏠 Домой"))
    keyboard.add(KeyboardButton("📝 Другое"), KeyboardButton("📋 Главное меню"))
    return keyboard

def day_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("💻 Сесть за комп"), KeyboardButton("🎮 Игры"),
        KeyboardButton("📚 Учеба/ДЗ"), KeyboardButton("🍽️ Обед/Ужин"),
        KeyboardButton("📺 Отдых"), KeyboardButton("🧹 Уборка"),
        KeyboardButton("🚶 Иду гулять"), KeyboardButton("👨‍👩‍👧‍👦 Время с близкими"))
    keyboard.add(KeyboardButton("📝 Другое"), KeyboardButton("📋 Главное меню"))
    return keyboard

def evening_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("🚿 Вечерняя гигиена"), KeyboardButton("🛏️ Лег в кровать"), 
        KeyboardButton("📱 Вечерний серфинг"), KeyboardButton("💤 Спать"))
    keyboard.add(KeyboardButton("📝 Другое"), KeyboardButton("📋 Главное меню"))
    return keyboard

def other_activity_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("❌ Отмена"))

def past_activity_keyboard():
    """Клавиатура для выбора действия при добавлении прошлого действия"""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("⏰ Проснулся"), KeyboardButton("📱 Полистал ленту"),
        KeyboardButton("🚽 В туалет"), KeyboardButton("🚿 Гигиена"),
        KeyboardButton("🍳 Завтрак"), KeyboardButton("👔 Одеваюсь"),
        KeyboardButton("🎒 Выхожу на учебу"), KeyboardButton("🏠 Домой"),
        KeyboardButton("💻 Сесть за комп"), KeyboardButton("🎮 Игры"),
        KeyboardButton("📚 Учеба/ДЗ"), KeyboardButton("🍽️ Обед/Ужин"),
        KeyboardButton("📺 Отдых"), KeyboardButton("🧹 Уборка"),
        KeyboardButton("🚶 Иду гулять"), KeyboardButton("👨‍👩‍👧‍👦 Время с близкими"),
        KeyboardButton("🚿 Вечерняя гигиена"), KeyboardButton("🛏️ Лег в кровать"), 
        KeyboardButton("📱 Вечерний серфинг"), KeyboardButton("💤 Спать")
    )
    keyboard.add(KeyboardButton("📝 Другое"), KeyboardButton("❌ Отмена"))
    return keyboard

# ========== ОСНОВНОЙ ФУНКЦИОНАЛ ==========
def handle_activity_start(message, activity_name: str, custom_start_time=None):
    user_id = message.from_user.id
    current_time = get_moscow_time() if custom_start_time is None else custom_start_time
    
    register_user(user_id, message.from_user.username)
    session = get_user_session(user_id)
    
    # Если есть текущая активность, сохраняем ее
    if session and session['current_activity'] and session['activity_start']:
        previous_start = datetime.fromisoformat(session['activity_start'])
        save_activity(user_id, session['current_activity'], previous_start, current_time)
        duration = current_time - previous_start
        minutes = int(duration.total_seconds() // 60)
        seconds = int(duration.total_seconds() % 60)
        bot.send_message(message.chat.id, f"✅ Завершено: {session['current_activity']}\n⏰ Время: {minutes}м {seconds}с")
    
    # Начинаем новую активность
    update_user_session(user_id, activity_name, current_time)
    
    time_display = format_moscow_time(current_time)
    if custom_start_time:
        bot.send_message(message.chat.id, f"🔄 Добавлено прошлое действие: {activity_name}\n🕐 Начало: {time_display}", reply_markup=main_menu_keyboard())
    else:
        bot.send_message(message.chat.id, f"🔄 Начато: {activity_name}\n🕐 {time_display}", reply_markup=main_menu_keyboard())

def handle_sleep_activity(message):
    """Обработка кнопки Спать с отправкой статистики"""
    user_id = message.from_user.id
    current_time = get_moscow_time()
    
    register_user(user_id, message.from_user.username)
    session = get_user_session(user_id)
    
    # Если есть текущая активность, сохраняем ее
    if session and session['current_activity'] and session['activity_start']:
        previous_start = datetime.fromisoformat(session['activity_start'])
        save_activity(user_id, session['current_activity'], previous_start, current_time)
        duration = current_time - previous_start
        minutes = int(duration.total_seconds() // 60)
        seconds = int(duration.total_seconds() % 60)
        bot.send_message(message.chat.id, f"✅ Завершено: {session['current_activity']}\n⏰ Время: {minutes}м {seconds}с")
    
    # Начинаем активность "Спать"
    update_user_session(user_id, "Спать", current_time)
    
    time_display = format_moscow_time(current_time)
    bot.send_message(message.chat.id, f"💤 Начато: Спать\n🕐 {time_display}")
    
    # Отправляем детальную статистику за день
    stats_text = format_detailed_statistics(user_id)
    bot.send_message(message.chat.id, stats_text)

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@bot.message_handler(commands=['start', 'help'])
def start_command(message):
    register_user(message.from_user.id, message.from_user.username)
    current_time = format_moscow_time()
    bot.send_message(message.chat.id, 
        f"🏠 Привет! Я бот для учета времени.\n\n"
        f"✅ Работаю 24/7 стабильно!\n"
        f"📝 Есть кнопка 'Другое' для своих активностей!\n"
        f"⏰ Можно добавлять действия задним числом!\n"
        f"📊 При нажатии 'Спать' получишь детальную статистику за день!\n"
        f"🕐 Текущее время: {current_time} МСК\n\n"
        f"Выбирай раздел и начинай отслеживать!",
        reply_markup=main_menu_keyboard()
    )

@bot.message_handler(func=lambda message: message.text == "📋 Главное меню")
def main_menu(message):
    if message.from_user.id in user_states:
        del user_states[message.from_user.id]
    bot.send_message(message.chat.id, "📋 Главное меню:", reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda message: message.text in ["🌅 Утро", "💻 День", "🌙 Вечер"])
def time_menu(message):
    user_id = message.from_user.id
    if user_id in user_states: 
        del user_states[user_id]
    if message.text == "🌅 Утро": 
        bot.send_message(message.chat.id, "🌅 Утренние активности:", reply_markup=morning_keyboard())
    elif message.text == "💻 День": 
        bot.send_message(message.chat.id, "💻 Дневные активности:", reply_markup=day_keyboard())
    else: 
        bot.send_message(message.chat.id, "🌙 Вечерние активности:", reply_markup=evening_keyboard())

@bot.message_handler(func=lambda message: message.text == "⏰ Добавить прошлое действие")
def add_past_activity(message):
    """Добавление действия с указанием времени начала"""
    user_states[message.from_user.id] = "waiting_for_past_activity"
    current_time = format_moscow_time()
    bot.send_message(message.chat.id,
        f"⏰ **Добавление действия задним числом**\n\n"
        f"Сначала выбери действие из списка ниже.\n"
        f"Потом я спрошу во сколько ты его начал.\n\n"
        f"🕐 Текущее время: {current_time} МСК\n\n"
        f"Выбери действие:",
        reply_markup=past_activity_keyboard()
    )

@bot.message_handler(func=lambda message: message.text == "📝 Другое")
def other_activity(message):
    user_id = message.from_user.id
    if user_states.get(user_id) == "waiting_for_past_activity":
        user_states[user_id] = "waiting_for_past_custom_activity"
    else:
        user_states[user_id] = "waiting_for_activity"
        
    bot.send_message(message.chat.id,
        "📝 Напиши свою активность текстом:\nПример: 'Читал книгу', 'Готовил ужин'\nИли '❌ Отмена' для отмены",
        reply_markup=other_activity_keyboard()
    )

@bot.message_handler(func=lambda message: message.text == "❌ Отмена")
def cancel_other_activity(message):
    user_id = message.from_user.id
    if user_id in user_states: 
        del user_states[user_id]
    bot.send_message(message.chat.id, "❌ Отменено", reply_markup=main_menu_keyboard())

# Обработка выбора действия для прошлого времени
@bot.message_handler(func=lambda message: message.from_user.id in user_states and user_states[message.from_user.id] == "waiting_for_past_activity")
def handle_past_activity_selection(message):
    user_id = message.from_user.id
    activity_name = message.text.split(' ', 1)[1] if ' ' in message.text else message.text
    user_states[user_id] = f"waiting_for_past_time:{activity_name}"
    
    current_time = format_moscow_time()
    bot.send_message(message.chat.id,
        f"🕐 **Во сколько ты начал '{activity_name}'?**\n\n"
        f"Формат: ЧЧ:ММ или ЧЧ:ММ:СС\n"
        f"Пример: 14:30 или 14:30:00\n\n"
        f"Текущее время: {current_time} МСК\n\n"
        f"Напиши время начала:",
        reply_markup=other_activity_keyboard()
    )

# Обработка ввода времени для прошлого действия
@bot.message_handler(func=lambda message: message.from_user.id in user_states and "waiting_for_past_time:" in user_states[message.from_user.id])
def handle_past_activity_time(message):
    user_id = message.from_user.id
    state = user_states[user_id]
    activity_name = state.split(':', 1)[1]
    
    # Парсим введенное время
    start_time = parse_time_input(message.text)
    
    if start_time is None:
        bot.send_message(message.chat.id,
            "❌ Неверный формат времени!\n\n"
            "Попробуй еще раз:\n"
            "• 14:30\n• 14:30:00\n• 14.30\n\n"
            "Напиши время начала:",
            reply_markup=other_activity_keyboard()
        )
        return
    
    current_time = get_moscow_time()
    
    # Проверяем что время не в будущем
    if start_time > current_time:
        bot.send_message(message.chat.id,
            "❌ Время не может быть в будущем!\n\n"
            f"Текущее время: {format_moscow_time()}\n"
            "Напиши корректное время начала:",
            reply_markup=other_activity_keyboard()
        )
        return
    
    # Сохраняем активность
    del user_states[user_id]
    handle_activity_start(message, activity_name, start_time)

# Обработка кастомной активности для прошлого времени
@bot.message_handler(func=lambda message: message.from_user.id in user_states and user_states[message.from_user.id] == "waiting_for_past_custom_activity")
def handle_past_custom_activity(message):
    user_id = message.from_user.id
    custom_activity = message.text.strip()
    
    if len(custom_activity) > 100:
        bot.send_message(message.chat.id, "❌ Слишком длинное название", reply_markup=other_activity_keyboard())
        return
    
    formatted_activity = f"Другое: {custom_activity}"
    user_states[user_id] = f"waiting_for_past_time:{formatted_activity}"
    
    current_time = format_moscow_time()
    bot.send_message(message.chat.id,
        f"🕐 **Во сколько ты начал '{custom_activity}'?**\n\n"
        f"Формат: ЧЧ:ММ или ЧЧ:ММ:СС\n"
        f"Пример: 14:30 или 14:30:00\n\n"
        f"Текущее время: {current_time} МСК\n\n"
        f"Напиши время начала:",
        reply_markup=other_activity_keyboard()
    )

# Обработка обычной кастомной активности
@bot.message_handler(func=lambda message: message.from_user.id in user_states and user_states[message.from_user.id] == "waiting_for_activity")
def handle_custom_activity(message):
    user_id = message.from_user.id
    custom_activity = message.text.strip()
    
    if len(custom_activity) > 100:
        bot.send_message(message.chat.id, "❌ Слишком длинное название", reply_markup=other_activity_keyboard())
        return
    
    formatted_activity = f"Другое: {custom_activity}"
    del user_states[user_id]
    handle_activity_start(message, formatted_activity)

@bot.message_handler(func=lambda message: message.text == "📊 Статистика")
def show_statistics(message):
    """Показывает детальную статистику по запросу"""
    user_id = message.from_user.id
    stats_text = format_detailed_statistics(user_id)
    bot.send_message(message.chat.id, stats_text)

# Обработчики стандартных активностей
activities = [
    "⏰ Проснулся", "📱 Полистал ленту", "🚽 В туалет", "🚿 Гигиена", 
    "🍳 Завтрак", "👔 Одеваюсь", "🎒 Выхожу на учебу", "🏠 Домой", 
    "💻 Сесть за комп", "🎮 Игры", "📚 Учеба/ДЗ", "🍽️ Обед/Ужин", 
    "📺 Отдых", "🧹 Уборка", "🚶 Иду гулять", "👨‍👩‍👧‍👦 Время с близкими",
    "🚿 Вечерняя гигиена", "🛏️ Лег в кровать", "📱 Вечерний серфинг"
]

for activity in activities:
    @bot.message_handler(func=lambda message, act=activity: message.text == act)
    def activity_handler(message, act=activity):
        # Проверяем не в режиме ли добавления прошлого действия
        user_id = message.from_user.id
        if user_states.get(user_id) == "waiting_for_past_activity":
            # Это выбор действия для прошлого времени - обрабатывается в другом обработчике
            return
        
        clean_activity = act.split(' ', 1)[1] if ' ' in act else act
        handle_activity_start(message, clean_activity)

# Специальный обработчик для кнопки "Спать"
@bot.message_handler(func=lambda message: message.text == "💤 Спать")
def sleep_handler(message):
    handle_sleep_activity(message)

# ========== FLASK СЕРВЕР ДЛЯ RENDER ==========
@app.route('/')
def home():
    return "🤖 Time Tracker Bot is running!"

@app.route('/health')
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})

@app.route('/ping')
def ping():
    """Специальный endpoint для пинга"""
    return jsonify({"status": "pong", "timestamp": datetime.now().isoformat()})

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    return 'Invalid content type', 400

def set_webhook():
    """Устанавливает webhook для бота"""
    if WEBHOOK_URL:
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
            logger.info(f"✅ Webhook set to: {WEBHOOK_URL}/webhook")
        except Exception as e:
            logger.error(f"❌ Webhook setup error: {e}")

def keep_alive_ping():
    """Фоновая задача для пинга сервиса каждые 5 минут"""
    # Ждем 30 секунд после запуска чтобы сервер точно поднялся
    time.sleep(30)
    
    while True:
        try:
            if WEBHOOK_URL:
                response = requests.get(f"{WEBHOOK_URL}/ping", timeout=10)
                logger.info(f"✅ Keep-alive ping sent: {response.status_code}")
            else:
                # Если нет WEBHOOK_URL, пингуем health endpoint
                import socket
                host = socket.gethostname()
                local_url = f"http://{host}:{PORT}/health"
                try:
                    response = requests.get(local_url, timeout=5)
                    logger.info(f"🔄 Local health check: {response.status_code}")
                except:
                    logger.info("🔧 Service starting up...")
        except Exception as e:
            logger.error(f"❌ Keep-alive ping failed: {e}")
        
        # Ждем 4 минуты (240 секунд) до следующего пинга
        time.sleep(240)

def run_flask():
    """Запускает Flask сервер"""
    logger.info(f"🌐 Starting Flask server on port {PORT}...")
    init_db()
    set_webhook()
    
    # Запускаем фоновую задачу для keep-alive пингов
    ping_thread = threading.Thread(target=keep_alive_ping, daemon=True)
    ping_thread.start()
    logger.info("✅ Keep-alive ping thread started")
    
    app.run(host='0.0.0.0', port=PORT, debug=False)

if __name__ == "__main__":
    # На Render используем только webhook режим
    run_flask()