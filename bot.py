import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import psycopg2
from datetime import datetime, timedelta
import os
import logging
import time
import sys

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

# Получение переменных окружения
API_TOKEN = os.environ.get('BOT_TOKEN')
DATABASE_URL = os.environ.get('DATABASE_URL')

if not API_TOKEN:
    logger.error("❌ BOT_TOKEN not found in environment variables")
    sys.exit(1)

if not DATABASE_URL:
    logger.error("❌ DATABASE_URL not found in environment variables")
    sys.exit(1)

logger.info("✅ Environment variables loaded successfully")

# Инициализация бота
bot = telebot.TeleBot(API_TOKEN)

# Состояния для FSM (Finite State Machine)
user_states = {}

def get_db_connection():
    """Установка соединения с PostgreSQL"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        logger.error(f"❌ Database connection error: {e}")
        return None

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = get_db_connection()
    if not conn:
        logger.error("❌ Cannot initialize database - no connection")
        return
        
    cur = conn.cursor()
    
    try:
        # Таблица пользователей
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(100),
                first_day_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица активностей
        cur.execute('''
            CREATE TABLE IF NOT EXISTS activities (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                activity_name VARCHAR(100),
                category VARCHAR(50),
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                duration INTERVAL,
                day_number INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица сессий
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id BIGINT PRIMARY KEY,
                current_activity VARCHAR(100),
                activity_start TIMESTAMP,
                last_activity VARCHAR(100),
                session_start TIMESTAMP
            )
        ''')
        
        # Таблица стриков
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_streaks (
                user_id BIGINT PRIMARY KEY,
                current_streak INTEGER DEFAULT 0,
                longest_streak INTEGER DEFAULT 0,
                last_activity_date DATE,
                total_days INTEGER DEFAULT 0
            )
        ''')
        
        conn.commit()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С ДАННЫМИ ==========
def register_user(user_id: int, username: str):
    conn = get_db_connection()
    if not conn:
        return False
        
    cur = conn.cursor()
    try:
        cur.execute('''
            INSERT INTO users (user_id, username) 
            VALUES (%s, %s) 
            ON CONFLICT (user_id) DO NOTHING
        ''', (user_id, username))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error registering user: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def save_activity(user_id: int, activity_name: str, start_time: datetime, end_time: datetime):
    conn = get_db_connection()
    if not conn:
        logger.error("❌ No database connection for save_activity")
        return False
        
    cur = conn.cursor()
    try:
        # Определяем категорию
        if activity_name.startswith("Другое:"):
            category = "Другое"
        else:
            category = get_activity_category(activity_name)
        
        duration = end_time - start_time
        day_number = 1  # Упрощенно для примера
        
        cur.execute('''
            INSERT INTO activities (user_id, activity_name, category, start_time, end_time, duration, day_number)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (user_id, activity_name, category, start_time, end_time, duration, day_number))
        
        conn.commit()
        logger.info(f"✅ Activity saved: {activity_name} for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Error saving activity: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

def get_activity_category(activity_name: str) -> str:
    """Определяет категорию активности"""
    categories = {
        # Утренние
        "Проснулся": "Сон",
        "Полистал ленту": "Развлечения", 
        "В туалет": "Гигиена",
        "Гигиена": "Гигиена",
        "Завтрак": "Еда",
        "Одеваюсь": "Подготовка",
        "Домой": "Переход",
        
        # Дневные
        "Сесть за комп": "Компьютер",
        "Игры": "Игры",
        "Учеба/ДЗ": "Учеба", 
        "Обед/Ужин": "Еда",
        "Отдых": "Развлечения",
        "Уборка": "Бытовые",
        
        # Вечерние
        "Вечерняя гигиена": "Гигиена",
        "Лег в кровать": "Отдых",
        "Вечерний серфинг": "Развлечения", 
        "Спать": "Сон"
    }
    
    return categories.get(activity_name, "Другое")

def update_user_session(user_id: int, current_activity: str = None, activity_start: datetime = None):
    conn = get_db_connection()
    if not conn:
        return False
        
    cur = conn.cursor()
    try:
        cur.execute('SELECT * FROM user_sessions WHERE user_id = %s', (user_id,))
        existing = cur.fetchone()
        
        if existing:
            cur.execute('''
                UPDATE user_sessions 
                SET current_activity = %s, activity_start = %s, last_activity = %s
                WHERE user_id = %s
            ''', (current_activity, activity_start, current_activity, user_id))
        else:
            cur.execute('''
                INSERT INTO user_sessions (user_id, current_activity, activity_start, last_activity, session_start)
                VALUES (%s, %s, %s, %s, %s)
            ''', (user_id, current_activity, activity_start, current_activity, datetime.now()))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating session: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def get_user_session(user_id: int):
    conn = get_db_connection()
    if not conn:
        return None
        
    cur = conn.cursor()
    try:
        cur.execute('SELECT * FROM user_sessions WHERE user_id = %s', (user_id,))
        return cur.fetchone()
    except Exception as e:
        logger.error(f"Error getting session: {e}")
        return None
    finally:
        cur.close()
        conn.close()

# ========== ОСНОВНОЙ ФУНКЦИОНАЛ БОТА ==========
def handle_activity_start(message, activity_name: str):
    """Обработчик начала активности"""
    user_id = message.from_user.id
    current_time = datetime.now()
    
    # Регистрируем пользователя если нужно
    register_user(user_id, message.from_user.username)
    
    # Получаем текущую сессию
    session = get_user_session(user_id)
    
    # Если есть текущая активность, сохраняем ее
    if session and session[1]:  # session[1] = current_activity
        previous_start = session[2]  # session[2] = activity_start
        if previous_start:
            save_activity(user_id, session[1], previous_start, current_time)
            
            # Отправляем сообщение о завершении
            duration = current_time - previous_start
            minutes = int(duration.total_seconds() // 60)
            seconds = int(duration.total_seconds() % 60)
            
            bot.send_message(
                message.chat.id, 
                f"✅ Завершено: {session[1]}\n⏰ Время: {minutes}м {seconds}с"
            )
    
    # Начинаем новую активность
    update_user_session(user_id, activity_name, current_time)
    
    bot.send_message(
        message.chat.id, 
        f"🔄 Начато: {activity_name}\n🕐 {current_time.strftime('%H:%M:%S')}",
        reply_markup=main_menu_keyboard()
    )

# ========== КЛАВИАТУРЫ ==========
def main_menu_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("🌅 Утро"),
        KeyboardButton("💻 День"), 
        KeyboardButton("🌙 Вечер"),
        KeyboardButton("📊 Статистика")
    )
    return keyboard

def morning_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("⏰ Проснулся"),
        KeyboardButton("📱 Полистал ленту"),
        KeyboardButton("🚽 В туалet"),
        KeyboardButton("🚿 Гигиена"),
        KeyboardButton("🍳 Завтрак"),
        KeyboardButton("👔 Одеваюсь"),
        KeyboardButton("🏠 Домой")
    )
    keyboard.add(KeyboardButton("📝 Другое"))
    keyboard.add(KeyboardButton("📋 Главное меню"))
    return keyboard

def day_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("💻 Сесть за комп"),
        KeyboardButton("🎮 Игры"),
        KeyboardButton("📚 Учеба/ДЗ"),
        KeyboardButton("🍽️ Обед/Ужин"),
        KeyboardButton("📺 Отдых"),
        KeyboardButton("🧹 Уборка")
    )
    keyboard.add(KeyboardButton("📝 Другое"))
    keyboard.add(KeyboardButton("📋 Главное меню"))
    return keyboard

def evening_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("🚿 Вечерняя гигиена"),
        KeyboardButton("🛏️ Лег в кровать"), 
        KeyboardButton("📱 Вечерний серфинг"),
        KeyboardButton("💤 Спать")
    )
    keyboard.add(KeyboardButton("📝 Другое"))
    keyboard.add(KeyboardButton("📋 Главное меню"))
    return keyboard

def other_activity_keyboard():
    """Клавиатура для отмены ввода своей активности"""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("❌ Отмена"))
    return keyboard

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    register_user(user_id, message.from_user.username)
    
    welcome_text = (
        "🏠 Привет! Я бот для учета твоего времени.\n\n"
        "Я работаю 24/7 и сохраняю все в базу данных! 💾\n"
        "Выбирай раздел и начинай отслеживать свое время!\n\n"
        "✨ Есть кнопка 'Другое' для своих активностей!"
    )
    
    bot.send_message(message.chat.id, welcome_text, reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda message: message.text == "📋 Главное меню")
def main_menu(message):
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]  # Сбрасываем состояние
    bot.send_message(message.chat.id, "📋 Главное меню:", reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda message: message.text == "🌅 Утро")
def morning_menu(message):
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]  # Сбрасываем состояние
    bot.send_message(message.chat.id, "🌅 Утренние активности:", reply_markup=morning_keyboard())

@bot.message_handler(func=lambda message: message.text == "💻 День")
def day_menu(message):
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]  # Сбрасываем состояние
    bot.send_message(message.chat.id, "💻 Дневные активности:", reply_markup=day_keyboard())

@bot.message_handler(func=lambda message: message.text == "🌙 Вечер")
def evening_menu(message):
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]  # Сбрасываем состояние
    bot.send_message(message.chat.id, "🌙 Вечерние активности:", reply_markup=evening_keyboard())

@bot.message_handler(func=lambda message: message.text == "📝 Другое")
def other_activity(message):
    """Обработчик кнопки Другое"""
    user_id = message.from_user.id
    user_states[user_id] = "waiting_for_activity"
    
    bot.send_message(
        message.chat.id,
        "📝 Напиши свою активность текстом:\n\n"
        "Например: 'Читал книгу', 'Готовил ужин', 'Занимался спортом'\n"
        "Или нажми '❌ Отмена' чтобы вернуться назад",
        reply_markup=other_activity_keyboard()
    )

@bot.message_handler(func=lambda message: message.text == "❌ Отмена")
def cancel_other_activity(message):
    """Отмена ввода своей активности"""
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]
    
    bot.send_message(
        message.chat.id,
        "❌ Ввод активности отменен",
        reply_markup=main_menu_keyboard()
    )

@bot.message_handler(func=lambda message: message.from_user.id in user_states and user_states[message.from_user.id] == "waiting_for_activity")
def handle_custom_activity(message):
    """Обработчик введенной пользователем активности"""
    user_id = message.from_user.id
    custom_activity = message.text.strip()
    
    if len(custom_activity) > 100:
        bot.send_message(
            message.chat.id,
            "❌ Слишком длинное название активности (максимум 100 символов)\nПопробуй еще раз:",
            reply_markup=other_activity_keyboard()
        )
        return
    
    # Форматируем активность
    formatted_activity = f"Другое: {custom_activity}"
    
    # Удаляем состояние
    del user_states[user_id]
    
    # Обрабатываем как обычную активность
    handle_activity_start(message, formatted_activity)

@bot.message_handler(func=lambda message: message.text == "📊 Статистика")
def show_statistics(message):
    user_id = message.from_user.id
    conn = get_db_connection()
    if not conn:
        bot.send_message(message.chat.id, "❌ Ошибка базы данных")
        return
        
    cur = conn.cursor()
    try:
        # Статистика по категориям за сегодня
        cur.execute('''
            SELECT category, SUM(duration) as total_time
            FROM activities 
            WHERE user_id = %s AND DATE(start_time) = CURRENT_DATE
            GROUP BY category 
            ORDER BY total_time DESC
        ''', (user_id,))
        
        stats = cur.fetchall()
        
        if not stats:
            bot.send_message(message.chat.id, "📊 Сегодня еще нет активностей")
            return
        
        stats_text = "📊 **Статистика за сегодня:**\n\n"
        total_seconds = 0
        
        for category, duration in stats:
            if duration:
                seconds = duration.total_seconds()
                minutes = int(seconds // 60)
                hours = int(minutes // 60)
                remaining_minutes = minutes % 60
                total_seconds += seconds
                
                if hours > 0:
                    stats_text += f"• **{category}**: {hours}ч {remaining_minutes}м\n"
                else:
                    stats_text += f"• **{category}**: {minutes}м\n"
        
        total_minutes = int(total_seconds // 60)
        total_hours = int(total_minutes // 60)
        remaining_minutes = total_minutes % 60
        
        if total_hours > 0:
            total_time_str = f"{total_hours}ч {remaining_minutes}м"
        else:
            total_time_str = f"{total_minutes}м"
            
        stats_text += f"\n🕐 **Всего времени**: {total_time_str}"
        
        # Показываем отдельно активности из категории "Другое"
        cur.execute('''
            SELECT activity_name, SUM(duration) as total_time
            FROM activities 
            WHERE user_id = %s AND category = 'Другое' AND DATE(start_time) = CURRENT_DATE
            GROUP BY activity_name 
            ORDER BY total_time DESC
        ''', (user_id,))
        
        other_activities = cur.fetchall()
        
        if other_activities:
            stats_text += "\n\n**📝 Свои активности:**\n"
            for activity, duration in other_activities:
                if duration:
                    seconds = duration.total_seconds()
                    minutes = int(seconds // 60)
                    activity_name = activity.replace("Другое: ", "")
                    stats_text += f"• {activity_name}: {minutes}м\n"
        
        bot.send_message(message.chat.id, stats_text)
        
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка при получении статистики")
    finally:
        cur.close()
        conn.close()

# ========== ОБРАБОТЧИКИ СТАНДАРТНЫХ АКТИВНОСТЕЙ ==========
activities = [
    "⏰ Проснулся", "📱 Полистал ленту", "🚽 В туалет", "🚿 Гигиена", 
    "🍳 Завтрак", "👔 Одеваюсь", "🏠 Домой", "💻 Сесть за комп",
    "🎮 Игры", "📚 Учеба/ДЗ", "🍽️ Обед/Ужин", "📺 Отдых", "🧹 Уборка",
    "🚿 Вечерняя гигиена", "🛏️ Лег в кровать", "📱 Вечерний серфинг", "💤 Спать"
]

for activity in activities:
    @bot.message_handler(func=lambda message, act=activity: message.text == act)
    def activity_handler(message, act=activity):
        # Убираем эмодзи для сохранения в БД
        clean_activity = act.split(' ', 1)[1] if ' ' in act else act
        handle_activity_start(message, clean_activity)

# ========== ЗАПУСК БОТА ==========
def run_bot():
    """Запуск бота с переподключением при ошибках"""
    logger.info("🔄 Initializing database...")
    init_db()
    
    logger.info("🚀 Starting Time Tracker Bot 24/7...")
    
    while True:
        try:
            logger.info("🤖 Bot polling started...")
            bot.polling(none_stop=True, interval=1, timeout=60)
        except Exception as e:
            logger.error(f"❌ Bot error: {e}")
            logger.info("🔄 Restarting bot in 10 seconds...")
            time.sleep(10)

if __name__ == "__main__":
    run_bot()