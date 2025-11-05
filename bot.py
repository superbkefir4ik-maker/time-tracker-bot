import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
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

if not API_TOKEN:
    logger.error("❌ BOT_TOKEN not found in environment variables")
    sys.exit(1)

logger.info("✅ Environment variables loaded successfully")

# Инициализация бота
bot = telebot.TeleBot(API_TOKEN)

# Хранилище в памяти (вместо базы данных)
user_data = {}

# Состояния для FSM (Finite State Machine)
user_states = {}

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С ДАННЫМИ ==========
def init_user(user_id: int, username: str):
    """Инициализация пользователя"""
    if user_id not in user_data:
        user_data[user_id] = {
            'username': username,
            'current_activity': None,
            'activity_start': None,
            'activities_history': [],
            'session_start': datetime.now(),
            'streak': 1
        }

def save_activity(user_id: int, activity_name: str, start_time: datetime, end_time: datetime):
    """Сохранение активности в память"""
    if user_id not in user_data:
        return False
    
    duration = end_time - start_time
    
    user_data[user_id]['activities_history'].append({
        'activity': activity_name,
        'start': start_time,
        'end': end_time,
        'duration': duration
    })
    
    logger.info(f"✅ Activity saved: {activity_name} for user {user_id}")
    return True

def update_user_session(user_id: int, current_activity: str = None, activity_start: datetime = None):
    """Обновление сессии пользователя"""
    if user_id not in user_data:
        return False
    
    user_data[user_id]['current_activity'] = current_activity
    user_data[user_id]['activity_start'] = activity_start
    
    return True

def get_user_session(user_id: int):
    """Получение сессии пользователя"""
    return user_data.get(user_id)

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

# ========== ОСНОВНОЙ ФУНКЦИОНАЛ БОТА ==========
def handle_activity_start(message, activity_name: str):
    """Обработчик начала активности"""
    user_id = message.from_user.id
    current_time = datetime.now()
    
    # Инициализируем пользователя если нужно
    init_user(user_id, message.from_user.username)
    
    # Получаем текущую сессию
    session = get_user_session(user_id)
    
    # Если есть текущая активность, сохраняем ее
    if session and session['current_activity']:
        previous_start = session['activity_start']
        if previous_start:
            save_activity(user_id, session['current_activity'], previous_start, current_time)
            
            # Отправляем сообщение о завершении
            duration = current_time - previous_start
            minutes = int(duration.total_seconds() // 60)
            seconds = int(duration.total_seconds() % 60)
            
            bot.send_message(
                message.chat.id, 
                f"✅ Завершено: {session['current_activity']}\n⏰ Время: {minutes}м {seconds}с"
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
        KeyboardButton("🚽 В туалет"),
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
    init_user(user_id, message.from_user.username)
    
    welcome_text = (
        "🏠 Привет! Я бот для учета твоего времени.\n\n"
        "✅ Теперь я работаю 24/7!\n"
        "📝 Есть кнопка 'Другое' для своих активностей!\n"
        "📊 Вся статистика сохраняется!\n\n"
        "Выбирай раздел и начинай отслеживать!"
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
    
    if user_id not in user_data or not user_data[user_id]['activities_history']:
        bot.send_message(message.chat.id, "📊 Сегодня еще нет активностей")
        return
    
    # Статистика по категориям за сегодня
    activities_history = user_data[user_id]['activities_history']
    
    # Группируем по категориям
    category_totals = {}
    
    for activity in activities_history:
        category = get_activity_category(activity['activity'])
        if category not in category_totals:
            category_totals[category] = timedelta()
        category_totals[category] += activity['duration']
    
    stats_text = "📊 **Статистика за сегодня:**\n\n"
    total_seconds = 0
    
    for category, total_time in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
        seconds = total_time.total_seconds()
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
    other_activities = {}
    for activity in activities_history:
        if activity['activity'].startswith("Другое:"):
            name = activity['activity']
            if name not in other_activities:
                other_activities[name] = timedelta()
            other_activities[name] += activity['duration']
    
    if other_activities:
        stats_text += "\n\n**📝 Свои активности:**\n"
        for activity_name, duration in sorted(other_activities.items(), key=lambda x: x[1], reverse=True):
            seconds = duration.total_seconds()
            minutes = int(seconds // 60)
            clean_name = activity_name.replace("Другое: ", "")
            stats_text += f"• {clean_name}: {minutes}м\n"
    
    bot.send_message(message.chat.id, stats_text)

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
        # Убираем эмодзи для сохранения в память
        clean_activity = act.split(' ', 1)[1] if ' ' in act else act
        handle_activity_start(message, clean_activity)

# ========== ЗАПУСК БОТА ==========
def run_bot():
    """Запуск бота с переподключением при ошибках"""
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