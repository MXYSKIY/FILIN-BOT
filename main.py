import os
import sqlite3
from datetime import datetime, timedelta
import random
import string
import asyncio
import io
import base64
import logging
import traceback
import aiohttp  
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
from gradio_client import Client
from together import Together

TOKEN = "7973116563:AAHJd6px8fO1FI9G2RttubRG3aG7b1UnnuA"
CHANNEL_ID = "-1002709054893"
CHANNEL_URL = "https://t.me/filin_ai"
PAYMENT_URL = "https://t.me/filin_ai"
HUGGINGFACE_SPACE_TTS = "k2-fsa/text-to-speech"
QWEN_SPACE_NAME = "Qwen/Qwen2-72B-Instruct"
HUGGINGFACE_SPACE_IMAGE = "black-forest-labs/FLUX.1-schnell"
ADMIN_ID = [6318995328]

os.environ["TOGETHER_API_KEY"] = "255e65744f3d5b0e15adb6919de869bc41067a96d3ceaff23f1146e73ff1799c"

# ИСПРАВЛЕНИЕ 2: Правильная инициализация Together client с API ключом
client = Together(api_key=os.environ["TOGETHER_API_KEY"])

conn = sqlite3.connect('user_data.db', check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS users
             (user_id INTEGER PRIMARY KEY,
              balance REAL DEFAULT 0,
              crystals INTEGER DEFAULT 3,
              is_premium BOOLEAN DEFAULT FALSE,
              premium_expiry TIMESTAMP,
              join_date TIMESTAMP,
              referral_code TEXT,
              referrer_id INTEGER,
              images_generated INTEGER DEFAULT 0,
              texts_voiced INTEGER DEFAULT 0,
              invited_users INTEGER DEFAULT 0,
              spent_crystals INTEGER DEFAULT 0,
              last_daily_reward TIMESTAMP)''')

c.execute('''CREATE TABLE IF NOT EXISTS promo_codes
             (code TEXT PRIMARY KEY,
              type TEXT,
              amount INTEGER,
              max_uses INTEGER)''')

c.execute('''CREATE TABLE IF NOT EXISTS used_promo_codes
             (user_id INTEGER,
              promo_code TEXT,
              used_at TIMESTAMP,
              PRIMARY KEY (user_id, promo_code))''')

c.execute('''CREATE TABLE IF NOT EXISTS bot_stats
             (id INTEGER PRIMARY KEY,
              total_users INTEGER DEFAULT 0,
              new_users_24h INTEGER DEFAULT 0,
              messages_processed INTEGER DEFAULT 0,
              commands_executed INTEGER DEFAULT 0,
              images_generated INTEGER DEFAULT 0,
              voices_generated INTEGER DEFAULT 0,
              videos_downloaded INTEGER DEFAULT 0)''')

conn.commit()

# Initialize clients with error handling
image_client = None
tts_client = None
qwen_client = None
fluxdev_client = None

# Try to initialize clients, but don't crash if they fail
try:
    image_client = Client(HUGGINGFACE_SPACE_IMAGE)
    print("Successfully connected to image generation space")
except Exception as e:
    print(f"Error connecting to image generation space: {e}")

try:
    tts_client = Client(HUGGINGFACE_SPACE_TTS)
    print("Successfully connected to text-to-speech space")
except Exception as e:
    print(f"Error connecting to text-to-speech space: {e}")

try:
    qwen_client = Client(QWEN_SPACE_NAME)
    print("Successfully connected to Qwen chat space")
except Exception as e:
    print(f"Error connecting to Qwen chat space: {e}")

try:
    # Updated client to use the Rooc space that hosts multiple FLUX.1-schnell models
    fluxdev_client = Client("Rooc/FLUX.1-schnell")
    print("Successfully connected to FLUX.1-schnell space")
except Exception as e:
    print(f"Error connecting to FLUX.1-schnell space: {e}")

ОЖИДАНИЕ_ПРОМПТА, ОЖИДАНИЕ_ТЕКСТА_ДЛЯ_ОЗВУЧКИ, ОЖИДАНИЕ_ПРОМОКОДА, ОЖИДАНИЕ_СООБЩЕНИЯ_ПОДДЕРЖКИ, ОЖИДАНИЕ_CHATGPT, ОЖИДАНИЕ_ВЫБОРА_ГОЛОСА, ОЖИДАНИЕ_ВЫБОРА_ДЕЙСТВИЯ = range(7)

async def handle_voice_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_choice = update.message.text
    if user_choice == "⬅️ Назад":
        context.user_data['state'] = None
        return await start(update, context)
    elif user_choice in ["👤Дмитрий", "👤Иван"]:
        context.user_data['selected_voice'] = "csukuangfj/vits-piper-ru_RU-ruslan-medium" if user_choice == "👤Дмитрий" else "csukuangfj/vits-piper-ru_RU-dmitri-medium"
        await update.message.reply_text(
            f"🎙Выбран голос: {user_choice}\n"
            "Пожалуйста, напишите текст для озвучки:"
        )
        context.user_data['state'] = ОЖИДАНИЕ_ТЕКСТА_ДЛЯ_ОЗВУЧКИ
        return ОЖИДАНИЕ_ТЕКСТА_ДЛЯ_ОЗВУЧКИ
    else:
        await update.message.reply_text("❌ Пожалуйста, используйте кнопки.")
        return ОЖИДАНИЕ_ВЫБОРА_ГОЛОСА

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    context.user_data['state'] = None
    await check_daily_reward(user_id)
    
    # ИСПРАВЛЕНИЕ 3: Добавляем обработку реферальной ссылки
    if context.args and len(context.args[0]) == 8:
        await обработка_реферальной_ссылки(update, context)
    
    if await проверка_подписки(user_id, context):
        crystals, balance, is_premium, _, _, _ = получить_кристаллы(user_id)
        keyboard = [
            [KeyboardButton("🎨 Нейросети")],
            [KeyboardButton("💎 Магазин"), KeyboardButton("🎟️ Промокод")],
            [KeyboardButton("👤 Профиль"), KeyboardButton("👨‍💻 Поддержка")],
            [KeyboardButton("👑 Premium")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        photo_path = "path_to_your_image.jpg"
        
        caption = (
            "🏠 ВашБот - Главнoe мeню\n\n"
            "🤖 Я — бот для творчества и автоматизации:\n"
            "  • 🎨 Генерация изображений — создавайте картинки.\n"
            "  • 🎙 Озвучка текста — превращайте текст в голос.\n"
            "  • 🧠 Текстовый чат-бот — общение, или создание промпта.\n\n"
            "📌 Выберите команду из меню для начала работы:"
        )
        
        with open(photo_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)
        
        return ConversationHandler.END
    else:
        keyboard = [
            [InlineKeyboardButton("✨Подписаться", url=CHANNEL_URL)],
            [InlineKeyboardButton("✅Проверить", callback_data="check_subscription")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        photo_path = "path_to_your_image.jpg"
        
        caption = (
            "👋 Приветствуем в ВашБот\n\n"
            "Мои функции:\n"
            "  • 🎨 Генерация изображений — создавайте картинки.\n"
            "  • 🎙 Озвучка текста — превращайте текст в голос.\n"
            "  • 🧠 Текстовый чат-бот — общение, или создание промпта.\n\n"
            "✨ Перед использованием бота, пожалуйста подпишитесь на наш канал ниже и не отписывайтесь!"
        )
        
        with open(photo_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)
        
        return ConversationHandler.END

async def check_daily_reward(user_id: int):
    c.execute("SELECT last_daily_reward, crystals, is_premium, balance FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    if result:
        last_reward, current_crystals, is_premium, balance = result
        if last_reward:
            last_reward = datetime.fromisoformat(last_reward)
            if datetime.now() - last_reward > timedelta(hours=24):
                max_crystals = 30 if is_premium else 3
                if current_crystals < max_crystals:
                    crystals_to_add = max_crystals - current_crystals
                    rubles_to_add = 2.5 if is_premium else 0
                    c.execute("UPDATE users SET crystals = ?, balance = balance + ?, last_daily_reward = ? WHERE user_id = ?", 
                              (max_crystals, rubles_to_add, datetime.now().isoformat(), user_id))
                    conn.commit()
        else:
            c.execute("UPDATE users SET last_daily_reward = ? WHERE user_id = ?", 
                      (datetime.now().isoformat(), user_id))
            conn.commit()

async def проверка_подписки(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        chat_member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        print(f"Ошибка при проверке подписки: {e}")
        return False

async def обработка_текстового_ввода(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text

    if context.user_data.get('state') == ОЖИДАНИЕ_ВЫБОРА_ДЕЙСТВИЯ:
        if text == "🎙Озвучить ещё":
            return await text_to_speech_handler(update, context)
        elif text == "⬅️ Назад":
            context.user_data['state'] = None
            return await start(update, context)
        else:
            await update.message.reply_text("❌ Пожалуйста, используйте кнопки.")
            return ОЖИДАНИЕ_ВЫБОРА_ДЕЙСТВИЯ

    if not await проверка_подписки(user_id, context):
        keyboard = [
            [InlineKeyboardButton("✨Подписаться", url=CHANNEL_URL)],
            [InlineKeyboardButton("✅Проверить", callback_data="check_subscription")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        photo_path = "path_to_your_image.jpg"
        
        caption = (
            "👋 Приветствуем в ВашБот\n\n"
            "Мои функции:\n"
            "  • 🎨 Генерация изображений — создавайте картинки.\n"
            "  • 🎙 Озвучка текста — превращайте текст в голос.\n"
            "  • 🧠 Текстовый чат-бот — общение, или создание промпта.\n\n"
            "✨ Перед использованием бота, пожалуйста подпишитесь на наш канал ниже и не отписывайтесь!"
        )
        
        with open(photo_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)
        
        return ConversationHandler.END

    if context.user_data.get('state') == ОЖИДАНИЕ_ПРОМОКОДА:
        return await обработка_промокода(update, context)

    if context.user_data.get('state') == ОЖИДАНИЕ_СООБЩЕНИЯ_ПОДДЕРЖКИ:
        return await обработка_сообщения_поддержки(update, context)

    if context.user_data.get('state') == ОЖИДАНИЕ_CHATGPT:
        return await handle_chatgpt_message(update, context)

    if context.user_data.get('state') == ОЖИДАНИЕ_ПРОМПТА:
        return await генерация_изображения(update, context)

    if context.user_data.get('state') == ОЖИДАНИЕ_ВЫБОРА_ГОЛОСА:
        return await handle_voice_selection(update, context)

    if context.user_data.get('state') == ОЖИДАНИЕ_ТЕКСТА_ДЛЯ_ОЗВУЧКИ:
        return await handle_text_to_speech(update, context)

    if context.user_data.get('state') == ОЖИДАНИЕ_ВЫБОРА_ДЕЙСТВИЯ:
        if text == "🎙Озвучить ещё":
            return await text_to_speech_handler(update, context)
        elif text == "⬅️ Назад":
            context.user_data['state'] = None
            return await start(update, context)
        else:
            await update.message.reply_text("❌ Пожалуйста, используйте кнопки.")
            return ОЖИДАНИЕ_ВЫБОРА_ДЕЙСТВИЯ

    if text == "⬅️ Назад":
        context.user_data['state'] = None
        return await start(update, context)

    if text in ["⬆️ Назад", "Назад"]:
        return await start(update, context)

    if text == "🎨 Нейросети":
        photo_path = "path_to_neuronet_image.jpg"
        caption = (
            "🎨 Выберите нейросеть\n"
            "Нейросети - главный приоритет бота\n\n"
            "📌Пожалуйста, используйте кнопки для выбора:"
        )
        keyboard = [
            [KeyboardButton("🧠 ChatGPT-4")], [KeyboardButton("🔬 Flux.Dev")],
            [KeyboardButton("🎨 Flux.Schnell")],  [KeyboardButton("🎤 Озвучка текста")],
            [KeyboardButton("⬅️ Назад")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        with open(photo_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)
        return ConversationHandler.END

    elif text == "🧠 ChatGPT-4":
        return await chatgpt_handler(update, context)

    elif text == "🎨 Flux.Schnell":
        return await generate_image_handler(update, context)

    elif text == "🔬 Flux.Dev":
        return await fluxdev_handler(update, context)

    elif text == "🎤 Озвучка текста":
        return await text_to_speech_handler(update, context)

    elif text == "🎟️ Промокод":
        photo_path = "path_to_promo_image.jpg"
        
        caption = (
            "🎟️ Промокоды\n\n"
            "⚠️ Важно:\n"
            " • Промокоды можно использовать только один раз.\n"
            " • Если код недействителен, вы получите уведомление.\n\n"
            "🔎 Пожалуйста, введите промокод:"
        )
        
        keyboard = [[KeyboardButton("⬅️ Назад")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        with open(photo_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)
        
        context.user_data['state'] = ОЖИДАНИЕ_ПРОМОКОДА
        return ОЖИДАНИЕ_ПРОМОКОДА

    elif text == "💎 Магазин":
        await команда_магазина(update, context)
        return ConversationHandler.END

    elif text == "👤 Профиль":
        await показать_профиль(update, context)
        return ConversationHandler.END

    elif text == "👨‍💻 Поддержка":
        await команда_поддержки(update, context)
        return ConversationHandler.END

    elif text == "✅ Проверить подписку":
        if await проверка_подписки(user_id, context):
            return await start(update, context)
        else:
            await update.message.reply_text("❌Пожалуйста, подпишитесь на канал, и не отписывайтесь!")
            return ConversationHandler.END

    elif text == "💸 Пополнить":
        await оплата(update, context)
        return ConversationHandler.END

    elif text == "🔗 Рефералка":
        await показать_информацию_о_реферальной_программе(update, context)
        return ConversationHandler.END

    elif text == "💎 Купить кристаллы":
        await купить_кристаллы(update, context)
        return ConversationHandler.END

    elif text == "👑 Купить PREMIUM":
        await купить_премиум(update, context)
        return ConversationHandler.END

    elif text in ["20₽ = 20💎", "50₽ = 50💎", "100₽ = 100💎"]:
        amount = int(text.split("₽")[0])
        keyboard = [
            [InlineKeyboardButton("Подтвердить✅", callback_data=f"buy_crystals_{amount}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"💎 Магазин\n"
            f"Пожалуйста, подтвердите покупку\n\n"
            f"💰Вы покупаете: {amount}💎 за {amount}₽",
            reply_markup=reply_markup
        )
        return ConversationHandler.END

    elif text in ["50💎 за Premium на 2 недели", "100💎 за Premium на 1 месяц"]:
        amount = 50 if "2 недели" in text else 100
        duration = 14 if "2 недели" in text else 30
        keyboard = [
            [InlineKeyboardButton("Подтвердить✅", callback_data=f"buy_premium_{duration}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"💎 Магазин\n"
            f"Пожалуйста, подтвердите покупку\n\n"
            f"💰 Вы покупаете: Premium на {'2 недели' if duration == 14 else '1 месяц'} за {amount}💎",
            reply_markup=reply_markup
        )
        return ConversationHandler.END

    elif text == "👑 Premium":
        await показать_премиум_инфо(update, context)
        return ConversationHandler.END

    elif text == "👑Активировать PREMIUM":
        await activate_premium(update, context)
        return ConversationHandler.END

    elif text == "✍️Написать":
        await update.message.reply_text(
            "👨‍💻Поддержка\n"
            "Пожалуйста, напишите ваш вопрос:\n"
        )
        context.user_data['state'] = ОЖИДАНИЕ_СООБЩЕНИЯ_ПОДДЕРЖКИ
        return ОЖИДАНИЕ_СООБЩЕНИЯ_ПОДДЕРЖКИ

    else:
        await update.message.reply_text("❌Не понимаю этого, лучше используй кнопки.")
        return await start(update, context)

async def chatgpt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    crystals, _, _, _, _, _ = получить_кристаллы(user_id)
    
    # Check if Qwen client is available
    if qwen_client is None:
        await update.message.reply_text("❌ Извините, сервис ChatGPT временно недоступен. Пожалуйста, попробуйте позже.")
        return await start(update, context)
    
    # Initialize empty chat history when starting a new chat
    context.user_data['chat_history'] = []
    
    photo_path = "chatgpt_path_message.png"
    caption = (
        "🧠 Ваш идеальный собеседник – ChatGPT\n"
        "Общение на любой вкус: поможет, поддержит и всегда рядом!\n\n"
        "✨ Создавайте промпты, идеи и решения любой сложности!\n"
        "✏️ Модель: ChatGPT (Новейшая версия)\n"
        "📄 Формат: От коротких сообщений до крупных проектов\n"
        "⚡️ Результат: Мгновенно\n"
        f"💎 Стоимость одного сообщения: 0.5 кристаллов\n"
        f"💰 Ваш баланс: {crystals}💎\n\n"
        "📌 Просто начните разговор и наслаждайтесь лёгким общением!"
    )
    keyboard = [[KeyboardButton("⬅️ Назад")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    with open(photo_path, 'rb') as photo:
        await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)
    context.user_data['state'] = ОЖИДАНИЕ_CHATGPT
    return ОЖИДАНИЕ_CHATGPT

async def handle_chatgpt_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message.text
    chat_id = update.message.chat_id

    if message == "⬅️ Назад":
        context.user_data['state'] = None
        return await start(update, context)

    if message.startswith('/') or message in ["🎨 Нейросети", "🎟️ Промокод", "💎Магазин", "👤Профиль", "👨‍💻Поддержка", "👑Premium"]:
        context.user_data['state'] = None
        return await start(update, context)

    crystals, _, _, _, _, _ = получить_кристаллы(user_id)
    if crystals < 0.5:
        await update.message.reply_text("❌У вас закончились кристаллы.")
        return await start(update, context)

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    # Check if Qwen client is available
    if qwen_client is None:
        await update.message.reply_text("❌ Извините, сервис ChatGPT временно недоступен. Пожалуйста, попробуйте позже.")
        return await start(update, context)

    try:
        # ИСПРАВЛЕНИЕ 4: Используем правильные параметры для Qwen
        result = qwen_client.predict(
            message,  # query parameter
            context.user_data.get('chat_history', []),  # history
            "Вы - полезный помощник.",  # system
            api_name="/model_chat"
        )

        # The response format is different from ChatGPT
        # result[1] contains the updated chat history
        context.user_data['chat_history'] = result[1]
        
        # Extract the bot's response from the result
        # The last message in the history is the bot's response
        bot_response = result[1][-1][1] if result[1] and len(result[1]) > 0 else "No response generated."

        await update.message.reply_text(bot_response)

        обновить_кристаллы(user_id, crystals - 0.5)
        await update.message.reply_text(f"💎 За одно сообщение снято 0.5 кристаллов\n💰 Текущий баланс: {crystals - 0.5}💎")
    except Exception as e:
        print(f"Error: {e}")
        await update.message.reply_text("❌Произошла ошибка при ответе. Пожалуйста отправьте это сообщение в поддержку. /help")

    return ОЖИДАНИЕ_CHATGPT

async def clear_chat_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check if Qwen client is available
    if qwen_client is None:
        await update.message.reply_text("❌ Извините, сервис ChatGPT временно недоступен. Пожалуйста, попробуйте позже.")
        return await start(update, context)
    
    try:
        # Clear chat history using the API
        result = qwen_client.predict(api_name="/clear_session")
        context.user_data['chat_history'] = []
        
        await update.message.reply_text("✅ История чата очищена.")
    except Exception as e:
        print(f"Error clearing chat history: {e}")
        await update.message.reply_text("❌ Произошла ошибка при очистке истории чата.")
    
    return ОЖИДАНИЕ_CHATGPT

async def generate_image_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    crystals, _, _, _, _, _ = получить_кристаллы(user_id)
    
    # Check if image generation is available
    if client is None:
        await update.message.reply_text("❌ Извините, сервис генерации изображений Flux.Schnell временно недоступен. Пожалуйста, попробуйте позже или выберите другую нейросеть.")
        return await start(update, context)
    
    photo_path = "flux_generation.png"
    caption = (
        "🎨 Генерация изображений используя Flux.Schnell\n"
        "Напишите свой промпт и получите изображение:_\n\n"
        "✏️ Модель: Flux.Schnell\n"
        "🖼 Размер: 1024x1024\n"
        "🔞 Не поддерживает 18+\n"
        "⚡️ Мгновенный результат\n\n"
        f"💰 Ваш баланс: {crystals} 💎\n\n"    
        "📌 Пожалуйста, формулируйте промпт чётко и на английском языке."
    )
    keyboard = [[KeyboardButton("⬅️Назад")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    with open(photo_path, 'rb') as photo:
        await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)
    context.user_data['state'] = ОЖИДАНИЕ_ПРОМПТА
    context.user_data['image_generated'] = False
    context.user_data['current_model'] = 'flux'
    return ОЖИДАНИЕ_ПРОМПТА

async def fluxdev_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    crystals, _, _, _, _, _ = получить_кристаллы(user_id)
    
    # Check if fluxdev client is available
    if fluxdev_client is None:
        await update.message.reply_text("❌ Извините, сервис генерации изображений Flux.Dev временно недоступен. Пожалуйста, попробуйте позже или выберите другую нейросеть.")
        return await start(update, context)
    
    photo_path = "fluxdev_generation.png"
    caption = (
        "🎨 Генерация изображений используя Flux.Dev\n"
        "Напишите свой промпт и получите изображение:_\n\n"
        "✏️ Модель: Flux.Dev\n"
        "🖼 Размер: 1024x1024\n"
        "🔞 Не поддерживает 18+\n"
        "⚡️ Мгновенный результат\n\n"
        f"💰 Ваш баланс: {crystals} 💎\n\n"    
        "📌 Пожалуйста, формулируйте промпт чётко и на английском языке."
    )
    keyboard = [[KeyboardButton("⬅️Назад")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    with open(photo_path, 'rb') as photo:
        await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)
    context.user_data['state'] = ОЖИДАНИЕ_ПРОМПТА
    context.user_data['image_generated'] = False
    context.user_data['current_model'] = 'fluxdev'
    return ОЖИДАНИЕ_ПРОМПТА

async def генерация_изображения(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    prompt = update.message.text
    crystals, _, _, _, _, _ = получить_кристаллы(user_id)

    if prompt == "⬅️Назад":
        context.user_data['state'] = None
        return await start(update, context)

    if prompt == "🎨Сгенерировать ещё":
        context.user_data['image_generated'] = False
        if context.user_data.get('current_model') == 'fluxdev':
            return await fluxdev_handler(update, context)
        else:
            return await generate_image_handler(update, context)

    if context.user_data.get('image_generated', False):
        await update.message.reply_text("❌ Пожалуйста используйте кнопки.")
        return ОЖИДАНИЕ_ПРОМПТА

    if crystals >= 1:
        # Send a message that we're generating the image
        processing_message = await update.message.reply_text("⏳ Генерирую изображение, пожалуйста подождите...")
        
        try:
            if context.user_data.get('current_model') == 'fluxdev':
                # Check if fluxdev client is available
                if fluxdev_client is None:
                    await update.message.reply_text("❌ Извините, сервис генерации изображений Flux.Dev временно недоступен. Пожалуйста, попробуйте позже или выберите другую нейросеть.")
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=processing_message.message_id)
                    return await start(update, context)
                
                image_data = await generate_fluxdev_image(prompt)
                model_name = "Flux.Dev"
            else:
                # Check if Together client is available
                if client is None:
                    await update.message.reply_text("❌ Извините, сервис генерации изображений Flux.Schnell временно недоступен. Пожалуйста, попробуйте позже или выберите другую нейросеть.")
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=processing_message.message_id)
                    return await start(update, context)
    
                image_data = await generate_image(prompt)
                model_name = "Flux.Schnell"

            # Delete the processing message
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=processing_message.message_id)

            if image_data:
                caption = (
                    "✅ Генерация успешно завершена!\n"
                    f"✏️ Модель: {model_name}\n\n"
                    f"✨ Использованный промпт: <code>{prompt}</code>\n\n"
                    f"👤Ваш баланс кристаллов: {crystals - 1}💎 (-1)\n\n"
                    f"👑Сгенерировано в боте @Ejejhaieud_bot"
                )
                keyboard = [
                    [KeyboardButton("🎨Сгенерировать ещё")],
                    [KeyboardButton("⬅️Назад")]
                ]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=image_data,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
                обновить_кристаллы(user_id, crystals - 1)
                обновить_статистику_пользователя(user_id, 'images_generated')
                обновить_статистику_бота('images_generated')
                context.user_data['image_generated'] = True
            else:
                raise ValueError("❌Не удалось сгенерировать изображение")
        except Exception as e:
            print(f"❌Ошибка при генерации изображения: {e}")
            # Make sure to delete the processing message if there was an error
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=processing_message.message_id)
            except:
                pass
            await update.message.reply_text("❌Произошла ошибка при генерации изображения. Пожалуйста, сообщите это в поддержку. /support")
    else:
        await update.message.reply_text("❌У вас закончились кристаллы.")

    return ОЖИДАНИЕ_ПРОМПТА

# ИСПРАВЛЕНИЕ 5: Исправляем функцию генерации изображений
async def generate_image(prompt: str) -> io.BytesIO:
    try:
        # Используем правильный метод Together API
        response = await asyncio.to_thread(
            client.images.generate,
            prompt=prompt,
            model="black-forest-labs/FLUX.1-schnell",
            width=1024,
            height=1024,
            steps=4,
            seed=random.randint(1, 1000000),
            n=1,
            response_format="b64_json"
        )
        image_data = base64.b64decode(response.data[0].b64_json)
        return io.BytesIO(image_data)
    except Exception as e:
        print(f"Error generating image with Together API: {e}")
        traceback_str = traceback.format_exc()
        print(f"Traceback: {traceback_str}")
        return None

# ИСПРАВЛЕНИЕ 6: Исправляем функцию для Flux.Dev
async def generate_fluxdev_image(prompt: str) -> io.BytesIO:
    try:
        # Используем правильный метод Together API для Flux.Dev
        response = await asyncio.to_thread(
            client.images.generate,
            prompt=prompt,
            model="black-forest-labs/FLUX.1-dev",
            width=1024,
            height=1024,
            steps=20,  # Больше шагов для лучшего качества
            seed=random.randint(1, 1000000),
            n=1,
            response_format="b64_json"
        )
        image_data = base64.b64decode(response.data[0].b64_json)
        return io.BytesIO(image_data)
    except Exception as e:
        print(f"Error generating Flux.Dev image with Together API: {e}")
        traceback_str = traceback.format_exc()
        print(f"Traceback: {traceback_str}")
        
        # Если Together API не сработал, пробуем альтернативный метод
        try:
            print("Attempting fallback to direct API call")
            
            # Используем прямой запрос к API вместо Gradio client
            # Это обходит проблему с Gradio client
            headers = {
                "Authorization": f"Bearer {os.environ['TOGETHER_API_KEY']}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "black-forest-labs/FLUX.1-dev",
                "prompt": prompt,
                "width": 1024,
                "height": 1024,
                "steps": 20,
                "seed": random.randint(1, 1000000),
                "n": 1,
                "response_format": "b64_json"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.together.xyz/v1/images/generations",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        image_data = base64.b64decode(result["data"][0]["b64_json"])
                        return io.BytesIO(image_data)
                    else:
                        error_text = await response.text()
                        print(f"API error: {response.status}, {error_text}")
                        return None
        except Exception as fallback_error:
            print(f"Fallback also failed: {fallback_error}")
            return None

async def handle_text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    selected_voice = context.user_data.get('selected_voice')

    if text == "⬅️ Назад":
        context.user_data['state'] = None
        return await start(update, context)

    if text == "🎙Озвучить ещё":
        return await text_to_speech_handler(update, context)

    crystals, balance, is_premium, premium_expiry, referral_code, referrer_id = получить_кристаллы(user_id)
    if crystals < 1:
        await update.message.reply_text("❌У вас недостаточно кристаллов.")
        context.user_data['state'] = None
        return await start(update, context)

    # Check if TTS client is available
    if tts_client is None:
        await update.message.reply_text("❌ Извините, сервис озвучки текста временно недоступен. Пожалуйста, попробуйте позже.")
        return await start(update, context)

    # Send a message that we're processing the audio
    processing_message = await update.message.reply_text("⏳ Генерирую аудио, пожалуйста подождите...")

    try:
        result = tts_client.predict(
            "Russian",
            selected_voice,
            text,
            "0",
            1,
            api_name="/process"
        )
        
        audio_path = result[0]
        
        # Delete the processing message
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=processing_message.message_id)
        
        caption = (
            "✅ Озвучка успешно завершена!\n"
            f"🎙 Голос: {'👤Дмитрий' if selected_voice == 'csukuangfj/vits-piper-ru_RU-ruslan-medium' else '👤Иван'}\n\n"
            f"✨ Использованный текст: {text}\n\n"
            f"👤Ваш баланс кристаллов: {crystals - 1}💎 (-1)\n\n"
            "👑 Озвучено в боте @GenixNeuron_bot"
        )
        
        with open(audio_path, 'rb') as audio_file:
            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=audio_file,
                caption=caption,
                title="@GenixNeuron_bot"
            )
        
        обновить_кристаллы(user_id, crystals - 1)
        обновить_статистику_пользователя(user_id, 'texts_voiced')
        обновить_статистику_бота('voices_generated')

        keyboard = [
            [KeyboardButton("🎙Озвучить ещё")],
            [KeyboardButton("⬅️ Назад")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        # Removed the "Выберите действие:" message
        
        context.user_data['state'] = ОЖИДАНИЕ_ВЫБОРА_ДЕЙСТВИЯ
    except Exception as e:
        print(f"Error in text-to-speech: {e}")
        # Make sure to delete the processing message if there was an error
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=processing_message.message_id)
        except:
            pass
        await update.message.reply_text("❌Произошла ошибка при озвучке текста. Пожалуйста, сообщите об этом в поддержку. /support")

    return ОЖИДАНИЕ_ВЫБОРА_ДЕЙСТВИЯ

async def text_to_speech_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if TTS client is available
    if tts_client is None:
        await update.message.reply_text("❌ Извините, сервис озвучки текста временно недоступен. Пожалуйста, попробуйте позже.")
        return await start(update, context)
        
    photo_path = "path_to_text_to_speech_image.jpg"
    caption = (
        "🎙Озвучка текста\n"
        "Реалистичная озвучка текста\n\n"
        " •🗣 Реалистичные голоса\n"
        " •⚡️ Мгновенный результат\n\n"
        "🎤 Пожалуйста, сначала выберите голос для озвучки:"
    )
    keyboard = [
        [KeyboardButton("👤Дмитрий"), KeyboardButton("👤Иван")],
        [KeyboardButton("⬅️ Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    with open(photo_path, 'rb') as photo:
        await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)
    context.user_data['state'] = ОЖИДАНИЕ_ВЫБОРА_ГОЛОСА
    return ОЖИДАНИЕ_ВЫБОРА_ГОЛОСА

async def обработка_промокода(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    promo_code = update.message.text.strip().upper()
    user_id = update.effective_user.id

    if promo_code == "⬅️ НАЗАД":
        context.user_data['state'] = None
        return await start(update, context)

    c.execute("SELECT * FROM promo_codes WHERE UPPER(code) = ?", (promo_code,))
    promo = c.fetchone()

    if not promo:
        await update.message.reply_text("❌ Такого промокода не существует.")
        context.user_data['state'] = None
        return await start(update, context)

    code, type, amount, max_uses = promo

    c.execute("SELECT COUNT(*) FROM used_promo_codes WHERE promo_code = ?", (code,))
    uses = c.fetchone()[0]

    if max_uses != -1 and uses >= max_uses:
        await update.message.reply_text("❌ Этот промокод больше не действителен.")
        context.user_data['state'] = None
        return await start(update, context)

    c.execute("SELECT * FROM used_promo_codes WHERE user_id = ? AND promo_code = ?", (user_id, code))
    if c.fetchone():
        await update.message.reply_text("❌ Вы уже использовали этот промокод.")
        context.user_data['state'] = None
        return await start(update, context)
    
    if type == "diamond":
        c.execute("UPDATE users SET crystals = crystals + ? WHERE user_id = ?", (amount, user_id))
        await update.message.reply_text(
            f"✅ Промокод активирован.\n"
            f"💰 Вы получили: {amount}💎\n"
        )
    elif type == "rubles":
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await update.message.reply_text(
            f"✅ Промокод активирован.\n"
            f"💰 Вы получили: {amount}₽\n"
        )
    elif type == "premium":
        установить_премиум(user_id, True, amount)
        await update.message.reply_text(
            f"✅ Промокод активирован.\n"
            f"👑 Вы получили: Premium на {amount} {'день' if amount == 1 else 'дня' if amount < 5 else 'дней'}\n"
        )
        await send_premium_activation_message(context, user_id)
    
    c.execute("INSERT INTO used_promo_codes (user_id, promo_code, used_at) VALUES (?, ?, ?)",
              (user_id, code, datetime.now().isoformat()))
    conn.commit()
    
    crystals, balance, _, _, _, _ = получить_кристаллы(user_id)
    
    if type != "premium":
        await update.message.reply_text(f"💸 Теперь у вас: {crystals}💎 и {balance}₽")
    
    context.user_data['state'] = None
    return await start(update, context)

def получить_кристаллы(user_id):
    c.execute("SELECT crystals, balance, is_premium, premium_expiry, referral_code, referrer_id FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    
    if result is None:
        referral_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        c.execute("INSERT INTO users (user_id, crystals, join_date, referral_code) VALUES (?, ?, ?, ?)", 
                  (user_id, 3, datetime.now().isoformat(), referral_code))
        conn.commit()
        обновить_статистику_бота('total_users')
        обновить_статистику_бота('new_users_24h')
        return 3, 0, False, None, referral_code, None
    
    return result

def обновить_кристаллы(user_id, new_value):
    c.execute("UPDATE users SET crystals = ? WHERE user_id = ?", (new_value, user_id))
    conn.commit()

def установить_премиум(user_id, is_premium, duration):
    expiry = (datetime.now() + timedelta(days=duration)).isoformat() if is_premium else None
    c.execute("UPDATE users SET is_premium = ?, premium_expiry = ? WHERE user_id = ?", 
              (is_premium, expiry, user_id))
    conn.commit()
    
    if is_premium:
        c.execute("SELECT crystals FROM users WHERE user_id = ?", (user_id,))
        current_crystals = c.fetchone()[0]
        crystals_to_add = max(0, 30 - current_crystals)
        c.execute("UPDATE users SET crystals = ?, balance = balance + 2.5 WHERE user_id = ?", (30, user_id))
        conn.commit()

async def rubl_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_ID:
        await update.message.reply_text("❌Доступ к этой команде запрещён.")
        return await start(update, context)

    try:
        action, user_id, amount = context.args
        user_id = int(user_id)
        amount = float(amount)

        if action not in ['set', 'add', 'remove']:
            raise ValueError("Неверное действие. Используйте 'set', 'add' или 'remove'.")

        c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        current_balance = c.fetchone()

        if current_balance is None:
            await update.message.reply_text(f"Пользователь с ID {user_id} не найден.")
            return

        current_balance = current_balance[0]

        if action == 'set':
            new_balance = amount
        elif action == 'add':
            new_balance = current_balance + amount
        else:  # action == 'remove'
            new_balance = current_balance - amount
            if new_balance < 0:
                new_balance = 0

        c.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
        conn.commit()

        if action == 'add':
            await update.message.reply_text(
                f"✅ Баланс пользователя успешно обновлен!\n"
                f"💸 Текущий баланс пользователя: {new_balance}₽."
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ Ваш баланс успешно пополнен!\n"
                     f"💸 Текущий баланс: {new_balance}₽.\n"
                     f"💰 Спасибо за покупку!"
            )
        elif action == 'remove':
            await update.message.reply_text(
                f"✅ Вы успешно сняли {amount}₽ у пользователя {user_id}.\n"
                f"💰 Теперь у пользователя: {new_balance}₽"
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📌 Администрация сняла с вашего аккаунта {amount}₽\n"
                     f"💰 Теперь у вас: {new_balance}₽"
            )
        else:  # action == 'set'
            await update.message.reply_text(
                f"✅ Вы успешно установили новый баланс пользователю\n"
                f"💰 Теперь его баланс: {new_balance}₽"
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📌 Администрация установила вам новый баланс.\n"
                     f"💰 Теперь ваш новый баланс: {new_balance}₽"
            )

    except (ValueError, IndexError):
        await update.message.reply_text("Использование: /rubl <set/add/remove> <user_id> <amount>")

async def diamond_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_ID:
        await update.message.reply_text("❌Доступ к этой команде запрещён.")
        return await start(update, context)

    try:
        action, user_id, amount = context.args
        user_id = int(user_id)
        amount = int(amount)

        if action not in ['set', 'add', 'remove']:
            raise ValueError("Неверное действие. Используйте 'set', 'add' или 'remove'.")

        c.execute("SELECT crystals FROM users WHERE user_id = ?", (user_id,))
        current_crystals = c.fetchone()

        if current_crystals is None:
            await update.message.reply_text(f"Пользователь с ID {user_id} не найден.")
            return

        current_crystals = current_crystals[0]

        if action == 'set':
            new_crystals = amount
        elif action == 'add':
            new_crystals = current_crystals + amount
        else:  # action == 'remove'
            new_crystals = current_crystals - amount
            if new_crystals < 0:
                new_crystals = 0

        c.execute("UPDATE users SET crystals = ? WHERE user_id = ?", (new_crystals, user_id))
        conn.commit()

        if action == 'add':
            await update.message.reply_text(
                f"✅ Баланс пользователя успешно обновлен!\n"
                f"💸 Текущий баланс пользователя: {new_crystals}💎."
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅Ваш баланс успешно пополнен!\n"
                     f"💸Текущий баланс: {new_crystals}💎\n"
                     f"💰Спасибо за покупку!"
            )
        elif action == 'remove':
            await update.message.reply_text(
                f"✅Вы успешно сняли {amount}💎\n"
                f"💰Теперь баланс пользователя: {new_crystals}💎"
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📌Администрация сняла с вашего аккаунта {amount}💎\n"
                     f"💰Теперь у вас: {new_crystals}💎"
            )
        else:  # action == 'set'
            await update.message.reply_text(
                f"✅Вы успешно установили новый баланс пользователю {user_id}.\n"
                f"💰Теперь его баланс: {new_crystals}💎"
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📌Администрация установила вам новый баланс.\n"
                     f"💰Теперь ваш баланс: {new_crystals}💎"
            )

    except (ValueError, IndexError):
        await update.message.reply_text("Использование: /diamond <set/add/remove> <user_id> <amount>")

async def prem_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_ID:
        await update.message.reply_text("❌Доступ к этой команде запрещён.")
        return await start(update, context)

    try:
        action, user_id, days = context.args
        user_id = int(user_id)
        days = int(days)

        if action not in ['give', 'remove']:
            raise ValueError("Неверное действие. Используйте 'give' или 'remove'.")

        crystals, balance, is_premium, _, _, _ = получить_кристаллы(user_id)

        if action == 'give':
            if is_premium:
                await update.message.reply_text("❌У этого пользователя уже активирован премиум.")
                return
            установить_премиум(user_id, True, days)
            await send_admin_premium_activation_message(context, user_id, days)
            await update.message.reply_text(f"Премиум статус успешно выдан пользователю {user_id} на {days} дней.")
        else:  # action == 'remove'
            установить_премиум(user_id, False, 0)
            await send_premium_deactivation_message(update, context, user_id)

    except (ValueError, IndexError):
        await update.message.reply_text("Использование: /prem <give/remove> <user_id> <days>")

async def send_admin_premium_activation_message(context: ContextTypes.DEFAULT_TYPE, user_id: int, days: int):
    photo_path = "path_to_premium_activation_image.jpg"
    caption = (
        "👑Администрация активировала вам PREMIUM\n\n"
        f"🔓Конец действия срока через: {days} дней\n"
        f"Теперь вам доступны все преимущества бота:\n"
        f"• 30💎 ежедневно\n"
        f"• 2.5₽ ежедневно на баланс\n"
        f"• Доступ к эксклюзивным функциям\n\n"
        f"📌Наслаждайтесь использованием бота на полную! :)"
    )

    with open(photo_path, 'rb') as photo:
        await context.bot.send_photo(chat_id=user_id, photo=photo, caption=caption)

async def send_premium_deactivation_message(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    photo_path = "path_to_premium_deactivation_image.jpg"
    caption = (
        "🫤Время действия Premium закончилось.\n\n"
        "✨Теперь вам доступны обычные функции:\n"
        "•  3💎 на 24 часа.\n"
        "•  Доступ к обычным нейросетям.\n\n"
        "👑 Для продления Premium подписки напишите /premium"
    )
    with open(photo_path, 'rb') as photo:
        await context.bot.send_photo(chat_id=user_id, photo=photo, caption=caption)
    await update.message.reply_text(f"Премиум статус успешно убран у пользователя {user_id}.")

async def команда_магазина(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [KeyboardButton("💎 Купить кристаллы")],
        [KeyboardButton("👑 Купить PREMIUM")],
        [KeyboardButton("⬆️ Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    photo_path = "path_to_shop_image.jpg"
    
    caption = (
        "💎 Магазин\n"
        "Что будем покупать?\n\n"
        "💸 Пополняйте баланс в /profile.\n"
    )
    with open(photo_path, 'rb') as photo:
        await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)

async def купить_кристаллы(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [KeyboardButton("20₽ = 20💎")],
        [KeyboardButton("50₽ = 50💎")],
        [KeyboardButton("100₽ = 100💎")],
        [KeyboardButton("⬅️ Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "💎 Магазин\nВыберите количество кристаллов:",
        reply_markup=reply_markup
    )

async def купить_премиум(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    crystals, _, is_premium, premium_expiry, _, _ = получить_кристаллы(user_id)
    
    if is_premium:
        photo_path = "premium_is_activated.png"
        expiry_date = datetime.fromisoformat(premium_expiry)
        days_left = (expiry_date - datetime.now()).days
        caption = (
            "👑 Premium уже активирован!\n"
            f"👤 До конца срока действия: {days_left} дней.\n\n"
            "✨ Вам доступны следующие функции:\n"
            "• 30💎 ежедневно\n"
            "• 2.5₽ ежедневно на баланс\n"
            "• Доступ к эксклюзивным функциям\n\n"
            "📌Наслаждайтесь использованием бота на полную!"
        )
        with open(photo_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=caption)
        return

    keyboard = [
        [KeyboardButton("50💎 за Premium на 2 недели")],
        [KeyboardButton("100💎 за Premium на 1 месяц")],
        [KeyboardButton("⬅️ Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    photo_path = "path_to_premium_info_image.jpg"
    caption = (
        "👑Premium\n"
        "Пожалуйста, выберите тариф:"
    )
    
    with open(photo_path, 'rb') as photo:
        await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)

async def оплата(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    inline_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Администратор", url="https://t.me/ваш телеграм")]
    ])
    
    photo_path = "path_to_payment_image.jpg"
    
    caption = (
        "💸 Пополнение баланса\n"
        "Пополняйте баланс для покупки уникальных функций в магазине!\n\n"
        "💡 Важно:\n"
        " • Курс: 1₽ = 1💎\n"
        " • Пополненные средства не подлежат возврату. \n"
        "Подробнее — раздел /help.\n\n"
        "📌После оплаты администрация выдаст вам товар.\n\n"
        "👇Для перехода нажмите на кнопку ниже:"
    )
    
    with open(photo_path, 'rb') as photo:
        await update.message.reply_photo(photo=photo, caption=caption, reply_markup=inline_keyboard)

async def обработка_подтверждения_покупки(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data.split("_")
    
    if data[0] == "buy":
        if data[1] == "crystals":
            amount = int(data[2])
            crystals, balance, _, _, _, _ = получить_кристаллы(user_id)
            if balance >= amount:
                c.execute("UPDATE users SET balance = balance - ?, crystals = crystals + ? WHERE user_id = ?", 
                          (amount, amount, user_id))
                conn.commit()
                await query.answer(f"✅Успешная покупка!")
                await query.edit_message_text(
                    f"💎 Магазин\n"
                    f"Успешная покупка!\n\n"
                    f"✅Вы успешно купили {amount}💎 за {amount}₽"
                )
                await process_referral_bonus(context, user_id, amount)
            else:
                await query.answer("❌Недостаточно средств.", show_alert=True)
        elif data[1] == "premium":
            duration = int(data[2])
            amount = 50 if duration == 14 else 100
            crystals, _, _, _, _, _ = получить_кристаллы(user_id)
            if crystals >= amount:
                c.execute("UPDATE users SET crystals = crystals - ? WHERE user_id = ?", (amount, user_id))
                установить_премиум(user_id, True, duration)
                conn.commit()
                await query.answer(f"✅Успешная покупка!")
                await query.edit_message_text(
                    f"💎 Магазин\n"
                    f"Успешная покупка!\n\n"
                    f"✅Вы успешно купили Premium за {amount}💎 на {duration} дней."
                )
                await send_premium_activation_message(context, user_id)
                await process_referral_bonus(context, user_id, amount)
            else:
                await query.answer("❌У вас недостаточно кристаллов.", show_alert=True)

async def process_referral_bonus(context, user_id: int, amount: int):
    c.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))
    referrer = c.fetchone()
    if referrer and referrer[0]:
        bonus = int(amount * 0.05)  # 5% bonus
        c.execute("UPDATE users SET crystals = crystals + ? WHERE user_id = ?", (bonus, referrer[0]))
        conn.commit()
        await context.bot.send_message(
            chat_id=referrer[0],
            text=f"🎉 Поздравляем! Вы получили {bonus}💎 за покупку вашего реферала!"
        )

async def обработка_реферальной_ссылки(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if args and len(args[0]) == 8:
        referral_code = args[0].upper()
        user_id = update.effective_user.id
        
        c.execute("SELECT user_id FROM users WHERE referral_code = ?", (referral_code,))
        referrer = c.fetchone()
        
        if referrer and referrer[0] != user_id:
            referrer_id = referrer[0]
            c.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))
            existing_referrer = c.fetchone()
            
            if not existing_referrer or existing_referrer[0] is None:
                c.execute("UPDATE users SET referrer_id = ?, crystals = crystals + 5 WHERE user_id = ?", (referrer_id, user_id))
                c.execute("UPDATE users SET crystals = crystals + 5, invited_users = invited_users + 1 WHERE user_id = ?", (referrer_id,))
                conn.commit()
                
                await update.message.reply_text("🎉 Поздравляем! Вы получили 5💎 за регистрацию по реферальной ссылке!")
                
                crystals, _, _, _, _, _ = получить_кристаллы(referrer_id)
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=f"✅ Кто-то зашёл по вашей ссылке! Вы получили 5💎\n💰 Ваш баланс: {crystals}💎"
                )

async def показать_профиль(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # ИСПРАВЛЕНИЕ 8: Исправляем запрос к базе данных
    c.execute("SELECT balance, crystals, is_premium, premium_expiry, referral_code, join_date FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    
    if result:
        balance, crystals, is_premium, premium_expiry, referral_code, join_date = result
        
        c.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
        invited_users = c.fetchone()[0]
        
        c.execute("SELECT images_generated, texts_voiced, spent_crystals FROM users WHERE user_id = ?", (user_id,))
        stats = c.fetchone()
        images_generated, texts_voiced, spent_crystals = stats if stats else (0, 0, 0)
        
        if is_premium and premium_expiry:
            expiry_date = datetime.fromisoformat(premium_expiry)
            days_left = (expiry_date - datetime.now()).days
            premium_status = f"Активен ({days_left} дней)"
        else:
            premium_status = "Неактивен"
        
        join_date_formatted = datetime.fromisoformat(join_date).strftime("%d.%m.%Y") if join_date else "Неизвестно"
        
        photo_path = "path_to_profile_image.jpg"
        
        caption = (
            "👤 Профиль\n\n"
            f"🆔 ID: {user_id}\n"
            f"💰 Баланс: {balance}₽\n"
            f"💎 Кристаллы: {crystals}💎\n"
            f"👑 Premium: {premium_status}\n"
            f"📅 Дата регистрации: {join_date_formatted}\n\n"
            f"📊 Статистика:\n"
            f"🎨 Изображений создано: {images_generated}\n"
            f"🎙 Текстов озвучено: {texts_voiced}\n"
            f"👥 Приглашено: {invited_users} человек\n"
            f"💸 Потрачено кристаллов: {spent_crystals}\n\n"
            f"🔗 Реферальный код: {referral_code}\n\n"
            "📌 Хотите больше возможностей?\n"
            "• 💎 Пополните баланс кристаллов. /shop\n"
            "• 👑 Активируйте Premium статус. /premium\n\n"
            "❓ Выберите действие:"
        )
        
        keyboard = [
            [KeyboardButton("🔗 Рефералка")], [KeyboardButton("💸 Пополнить")],
            [KeyboardButton("⬅️ Назад")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        with open(photo_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)
    else:
        await update.message.reply_text("❌Пожалуйста, перезайдите в профиль через /start")
    context.user_data['last_command'] = 'профиль'

async def показать_информацию_о_реферальной_программе(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    c.execute("SELECT referral_code FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    if result:
        referral_code = result[0]
        referral_link = f"https://t.me/{context.bot.username}?start={referral_code}"
        
        c.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
        referral_count = c.fetchone()[0]
        
        c.execute("SELECT invited_users FROM users WHERE user_id = ?", (user_id,))
        invited_users_result = c.fetchone()
        invited_users = invited_users_result[0] if invited_users_result else 0
        
        photo_path = "path_to_referral_image.jpg"
        
        caption = (
            "🔗 Реферальная программа\n"
            "Приглашайте друзей и получайте бонусы!\n\n"
            "🎁 Бонусы:\n"
            "• За каждого приглашенного друга: +5💎\n"
            "• Ваш друг получает: +5💎 бонус\n"
            "• 5% от всех покупок вашего реферала\n\n"
            f"👥 Приглашено пользователей: {referral_count}\n"
            f"💎 Заработано кристаллов: {referral_count * 5}\n\n"
            f"🔗 Ваша реферальная ссылка:\n{referral_link}\n\n"
            "📌 Как это работает:\n"
            "• Вы получаете 5💎 за каждого приглашенного друга\n"
            "• Ваш друг получает 5💎 при регистрации\n"
            "• Вы получаете 5% от всех покупок вашего реферала\n\n"
            "📌 Поделитесь ссылкой с друзьями и получайте награды!"
        )
        
        with open(photo_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=caption)
    else:
        await update.message.reply_text("❌Пожалуйста, перезайдите в рефералку через /start")
    
    context.user_data['last_command'] = 'рефералка'

async def показать_премиум_инфо(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    crystals, _, is_premium, premium_expiry, _, _ = получить_кристаллы(user_id)
    
    if is_premium and premium_expiry:
        expiry_date = datetime.fromisoformat(premium_expiry)
        days_left = (expiry_date - datetime.now()).days
        premium_status = f"Активен (осталось {days_left} дней)"
    else:
        premium_status = "Неактивен"
    
    photo_path = "path_to_premium_info_image.jpg"
    
    caption = (
        "👑 Premium\n\n"
        f"👤Ваш статус: {premium_status}\n\n"
        "🔓 Преимущества Premium:\n"
        "• 30💎 ежедневно\n"
        "• 2.5₽ ежедневно на баланс\n"
        "• Приоритетная поддержка\n"
        "• Доступ к эксклюзивным функциям\n\n"
        "💎 Стоимость:\n"
        "• 2 недели: 50💎\n"
        "• 1 месяц: 100💎\n\n"
        "🔥 Активируйте Premium прямо сейчас!"
    )
    
    keyboard = [
        [KeyboardButton("👑Активировать PREMIUM")],
        [KeyboardButton("⬅️ Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    with open(photo_path, 'rb') as photo:
        await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)

async def activate_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    crystals, _, is_premium, premium_expiry, _, _ = получить_кристаллы(user_id)
    
    if is_premium:
        photo_path = "premium_is_activated.png"
        expiry_date = datetime.fromisoformat(premium_expiry)
        days_left = (expiry_date - datetime.now()).days
        caption = (
            "👑 Premium уже активирован!\n"
            f"👤 До конца срока действия: {days_left} дней.\n\n"
            "✨ Вам доступны следующие функции:\n"
            "• 30💎 ежедневно\n"
            "• 2.5₽ ежедневно на баланс\n"
            "• Доступ к эксклюзивным функциям\n\n"
            "📌Наслаждайтесь использованием бота на полную!"
        )
        with open(photo_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=caption)
        return

    photo_path = "path_to_premium_info_image.jpg"
    caption = (
        "👑Premium\n"
        "Пожалуйста, выберите тариф:"
    )
    keyboard = [
        [KeyboardButton("50💎 за Premium на 2 недели")],
        [KeyboardButton("100💎 за Premium на 1 месяц")],
        [KeyboardButton("⬅️ Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    with open(photo_path, 'rb') as photo:
        await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)

async def activate_premium_for_user(user_id: int, duration: int, context: ContextTypes.DEFAULT_TYPE):
    установить_премиум(user_id, True, duration)
    crystals, _, _, _, _, _ = получить_кристаллы(user_id)
    amount = 50 if duration == 14 else 100
    c.execute("UPDATE users SET crystals = crystals - ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    await send_premium_activation_message(context, user_id)

async def send_premium_activation_message(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    photo_path = "path_to_premium_activation_image.jpg"
    caption = (
        "👑 Premium успешно активирован!\n\n"
        "✨ Теперь вам доступны следующие функции:\n"
        "• 30💎 ежедневно\n"
        "• 2.5₽ ежедневно на баланс\n"
        "• Приоритетная поддержка\n"
        "• Доступ к эксклюзивным функциям\n\n"
        "📌Наслаждайтесь использованием бота на полную!"
    )
    with open(photo_path, 'rb') as photo:
        await context.bot.send_photo(chat_id=user_id, photo=photo, caption=caption)

async def обработка_сообщения_поддержки(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    message = update.message.text
    username = update.effective_user.username or "Без никнейма"

    if message == "⬅️ Назад":
        context.user_data['state'] = None
        return await start(update, context)

    for admin_id in ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"📨 Новое сообщение в поддержку:\n"
                     f"От: {username} (ID: {user_id})\n"
                     f"Сообщение: {message}"
            )
        except Exception as e:
            print(f"[Ошибка] Не удалось отправить админу {admin_id}: {e}")

    await update.message.reply_text("✅ Ваше сообщение отправлено в поддержку.")
    context.user_data['state'] = None
    return await start(update, context)

async def команда_поддержки(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    photo_path = "path_to_support_image.jpg"
    caption = (
        "👨‍💻Поддержка\n"
        "Если у вас возникли вопросы, мы всегда готовы помочь!\n\n"
        "📌 Если у вас возникли:\n"
        "• Проблемы или ошибки в работе системы.\n"
        "• Вопросы, пожелания или предложения.\n\n"
        "❗️ Обратите внимание:\n"
        "• Мы не отвечаем на сообщения не по теме.\n"
        "• За спам предусмотрено наказание.\n\n"
        "✍️ Нажмите кнопку 'Написать', чтобы отправить сообщение в поддержку."
    )
    keyboard = [
        [KeyboardButton("✍️Написать")],
        [KeyboardButton("⬅️ Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    with open(photo_path, 'rb') as photo:
        await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)

async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_ID:
        await update.message.reply_text("❌Доступ к этой команде запрещён.")
        return await start(update, context)

    try:
        message = ' '.join(context.args)
        if not message:
            raise ValueError("Сообщение не может быть пустым")

        c.execute("SELECT user_id FROM users")
        users = c.fetchall()

        success_count = 0
        for user in users:
            try:
                await context.bot.send_message(chat_id=user[0], text=message)
                success_count += 1
            except Exception as e:
                print(f"Не удалось отправить сообщение пользователю {user[0]}: {e}")

        await update.message.reply_text(f"✅Рассылка завершена. Успешно отправлено {success_count} пользователям.")

    except (ValueError, IndexError):
        await update.message.reply_text("Использование: /post <сообщение>")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_ID:
        await update.message.reply_text("❌Доступ к этой команде запрещён.")
        return await start(update, context)

    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM users WHERE join_date >= datetime('now', '-1 day')")
    new_users_24h = c.fetchone()[0]

    c.execute("SELECT SUM(images_generated) FROM users")
    total_images = c.fetchone()[0] or 0

    c.execute("SELECT SUM(texts_voiced) FROM users")
    total_voices = c.fetchone()[0] or 0

    c.execute("SELECT * FROM bot_stats WHERE id = 1")
    bot_stats = c.fetchone()

    if bot_stats:
        messages_processed, commands_executed = bot_stats[3], bot_stats[4]
    else:
        messages_processed, commands_executed = 0, 0

    stats_message = (
        "📊 Статистика бота:\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🆕 Новых пользователей за 24 часа: {new_users_24h}\n"
        f"🖼 Всего сгенерировано изображений: {total_images}\n"
        f"🎤 Всего озвучено текстов: {total_voices}\n"
        f"💬 Обработано сообщений: {messages_processed}\n"
        f"🔧 Выполнено команд: {commands_executed}"
    )

    await update.message.reply_text(stats_message)

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if user_id in ADMIN_ID:
        try:
            target_user_id, message = context.args[0], ' '.join(context.args[1:])
            target_user_id = int(target_user_id)
            if not message:
                raise ValueError("Сообщение не может быть пустым")
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"📩 Ответ от поддержки:\n{message}"
            )
            await update.message.reply_text(f"✅ Сообщение отправлено пользователю {target_user_id}.")
        except (ValueError, IndexError):
            await update.message.reply_text("Использование: /support <user_id> <сообщение>")
    else:
        photo_path = "path_to_support_image.jpg"
        caption = ("👨‍💻Поддержка\n"
                   "Если у вас возникли вопросы, мы всегда готовы помочь!\n"
                   "✍️ Нажмите кнопку 'Написать', чтобы отправить сообщение в поддержку.")
        keyboard = [[KeyboardButton("✍️Написать")], [KeyboardButton("⬅️ Назад")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        with open(photo_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    crystals, _, _, _, _, _ = получить_кристаллы(user_id)
    
    photo_path = "path_to_help.jpg"
    
    caption = (
        "🧠 Помощь по боту ВашБот\n\n"
        "Мои функции:\n"
        "• 🎨 Генерация изображений.\n"
        "• 🎙 Озвучка текста.\n"
        "• 🧠 Чат-бот (ChatGPT).\n"
        "• 🎟 Промокоды и реферальная система.\n"
        "• 💰 Баланс и премиум-статус.\n"
        "• 🤝 Поддержка.\n\n"
        "Дополнительная информация:\n"
        "• Кристаллы используются для генерации изображений и озвучки текста.\n"
        "• Premium статус дает дополнительные преимущества и бонусы.\n"
        "• Реферальная программа позволяет зарабатывать дополнительные кристаллы.\n\n"
        f"✨ У вас {crystals} 💎\n\n"
        "👇 Для подробной информации, политики конфиденциальности, и договора оферты нажмите кнопку ниже"
    )
    
    keyboard = [
        [InlineKeyboardButton("Помощь по боту", url="https://telegra.ph/Pomoshch-po-botu-ChatGpt-ChatGpt-bot-05-25")],
        [InlineKeyboardButton("Политика конфиденциальности, договор оферты", url="https://telegra.ph/Politika-konfidencialnosti-i-dogovor-oferty-05-25")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    with open(photo_path, 'rb') as photo:
        await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)

async def promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_ID:
        await update.message.reply_text("❌Доступ к этой команде запрещён.")
        return await start(update, context)

    try:
        action = context.args[0].lower()
        
        if action == "create":
            code, promo_type, amount, max_uses = context.args[1:5]
            amount = int(amount)
            max_uses = int(max_uses)
            
            c.execute("INSERT INTO promo_codes (code, type, amount, max_uses) VALUES (?, ?, ?, ?)",
                      (code, promo_type, amount, max_uses))
            conn.commit()
            
            await update.message.reply_text(f"✅Промокод {code} успешно создан.")
        
        elif action == "delete":
            code = context.args[1]
            
            c.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
            conn.commit()
            
            if c.rowcount > 0:
                await update.message.reply_text(f"✅Промокод {code} успешно удален.")
            else:
                await update.message.reply_text(f"❌Промокод {code} не найден.")
        
        elif action == "list":
            c.execute("""
                SELECT p.code, p.type, p.amount, p.max_uses, COUNT(u.promo_code) as uses
                FROM promo_codes p
                LEFT JOIN used_promo_codes u ON p.code = u.promo_code
                GROUP BY p.code
            """)
            promo_codes = c.fetchall()
            
            if promo_codes:
                response = "📋 Список промокодов:\n\n"
                for code, promo_type, amount, max_uses, uses in promo_codes:
                    response += f"Код: {code}\n"
                    response += f"Тип: {promo_type}\n"
                    response += f"Количество: {amount}\n"
                    response += f"Макс. использований: {max_uses}\n"
                    response += f"Использовано: {uses}\n\n"
            else:
                response = "Нет активных промокодов."
            
            await update.message.reply_text(response)
        
        else:
            raise ValueError("Неверное действие")

    except (ValueError, IndexError):
        await update.message.reply_text(
            "Использование:\n"
            "/promo create <code> <type> <amount> <max_uses>\n"
            "/promo delete <code>\n"
            "/promo list"
        )

async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id

    if await проверка_подписки(user_id, context):
        await query.answer("✅ Подписка подтверждена!")
        await query.message.delete()
        photo_path = "path_to_your_image.jpg"
        caption = (
            "🏠 ВашБот - Главнoe мeню\n\n"
            "🤖 Я — бот для творчества и автоматизации:\n"
            "  • 🎨 Генерация изображений — создавайте картинки.\n"
            "  • 🎙 Озвучка текста — превращайте текст в голос.\n"
            "  • 🧠 Текстовый чат-бот — общение, или создание промпта.\n\n"
            "📌 Выберите команду из меню для начала работы:"
        )
        keyboard = [
            [KeyboardButton("🎨 Нейросети")],
            [KeyboardButton("🎟️ Промокод"), KeyboardButton("💎 Магазин")],
            [KeyboardButton("👤 Профиль"), KeyboardButton("👨‍💻 Поддержка")],
            [KeyboardButton("👑 Premium")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        with open(photo_path, 'rb') as photo:
            await context.bot.send_photo(chat_id=user_id, photo=photo, caption=caption, reply_markup=reply_markup)
    else:
        await query.answer("❌ Вы не подписались на канал.", show_alert=True)

def обновить_статистику_пользователя(user_id, field):
    c.execute(f"UPDATE users SET {field} = {field} + 1 WHERE user_id = ?", (user_id,))
    conn.commit()

def обновить_статистику_бота(field):
    c.execute("SELECT COUNT(*) FROM bot_stats WHERE id = 1")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO bot_stats (id) VALUES (1)")
    c.execute(f"UPDATE bot_stats SET {field} = {field} + 1 WHERE id = 1")
    conn.commit()

def main() -> None:
    # Initialize bot_stats if it doesn't exist
    c.execute("SELECT COUNT(*) FROM bot_stats")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO bot_stats DEFAULT VALUES")
        conn.commit()
        
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("profile", показать_профиль))
    application.add_handler(CommandHandler("shop", команда_магазина))
    application.add_handler(CommandHandler("premium", показать_премиум_инфо))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("rubl", rubl_command))
    application.add_handler(CommandHandler("diamond", diamond_command))
    application.add_handler(CommandHandler("prem", prem_command))
    application.add_handler(CommandHandler("post", post_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("support", support_command))
    application.add_handler(CommandHandler("promo", promo_command))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, обработка_текстового_ввода))
    application.add_handler(CallbackQueryHandler(обработка_подтверждения_покупки, pattern=r'^buy_'))
    application.add_handler(CallbackQueryHandler(check_subscription_callback, pattern='^check_subscription$'))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
