import logging

from asgiref.sync import sync_to_async
from django.conf import settings
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

from .models import TelegramUser, MChatQuestion, SurveyResult, BotSettings
from .utils import calculate_mchat_score, get_risk_level

# ---------------------------------------------------------------------
#                 CONSTANTS: STATES FOR CONVERSATION HANDLER
# ---------------------------------------------------------------------
LANG_CHOICE, ASKING_QUESTION = range(2)
# После окончания опроса мы используем ConversationHandler.END

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ---------------------------------------------------------------------
#                 ASYNC WRAPPERS ДЛЯ ОПЕРАЦИЙ С БД
# ---------------------------------------------------------------------
@sync_to_async
def async_get_bot_settings():
    return BotSettings.objects.first()

@sync_to_async
def async_get_or_create_telegram_user(telegram_id, username, lang):
    tg_user, created = TelegramUser.objects.get_or_create(
        telegram_id=telegram_id,
        defaults={'username': username, 'language': lang}
    )
    if not created:
        tg_user.username = username
        tg_user.language = lang
        tg_user.save()
    return tg_user

@sync_to_async
def async_get_telegram_user(telegram_id):
    return TelegramUser.objects.get(telegram_id=telegram_id)

@sync_to_async
def async_order_questions():
    """Возвращает список вопросов (list) в нужном порядке."""
    return list(MChatQuestion.objects.order_by('question_number'))

@sync_to_async
def async_create_survey_result(tg_user, score, risk_level):
    return SurveyResult.objects.create(
        user=tg_user,
        result_score=score,
        risk_level=risk_level
    )

# ---------------------------------------------------------------------
#                     ФУНКЦИИ-ОБРАБОТЧИКИ
# ---------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /start — приветствие и предложение выбрать язык.
    """
    keyboard = [
        ["Русский (ru)", "O'zbek (uz)"],
        ["English (en)", "Qaraqalpaqsha (kk)"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    await update.message.reply_text(
        "Пожалуйста, выберите язык / Iltimos, tilni tanlang / Please choose a language / Тілді таңдаңыз:",
        reply_markup=reply_markup
    )
    # Переходим в состояние LANG_CHOICE
    return LANG_CHOICE


async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка выбранного языка + приветственное сообщение.
    После выбора языка сразу переходим к задаванию вопросов (ASKING_QUESTION).
    """
    text = update.message.text.lower()
    user = update.message.from_user

    if "ru" in text:
        lang = 'ru'
    elif "uz" in text:
        lang = 'uz'
    elif "en" in text:
        lang = 'en'
    else:
        lang = 'kk'

    # Создаём/обновляем пользователя
    tg_user = await async_get_or_create_telegram_user(
        telegram_id=user.id,
        username=user.username,
        lang=lang
    )

    # Получаем настройки бота
    bot_settings = await async_get_bot_settings()
    if bot_settings:
        if lang == 'ru':
            welcome_msg = bot_settings.welcome_message_ru
        elif lang == 'uz':
            welcome_msg = bot_settings.welcome_message_uz
        elif lang == 'en':
            welcome_msg = bot_settings.welcome_message_en
        else:
            welcome_msg = bot_settings.welcome_message_kk
    else:
        welcome_msg = "Welcome! No settings found."

    await update.message.reply_text(welcome_msg)

    # Загружаем вопросы
    questions = await async_order_questions()
    context.user_data['questions'] = questions
    context.user_data['answers'] = []
    context.user_data['current_index'] = 0

    # Сразу задаём первый вопрос
    await ask_next_question(update, context)
    # Переходим в состояние ASKING_QUESTION
    return ASKING_QUESTION


async def ask_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Задаём текущий вопрос (если остались вопросы).
    Вызывается из choose_language (первый вопрос) и handle_user_answer (следующие вопросы).
    """
    questions = context.user_data.get('questions', [])
    current_index = context.user_data.get('current_index', 0)

    if current_index >= len(questions):
        # Вопросы закончились — завершаем
        return await finish_survey(update, context)

    question = questions[current_index]

    # Узнаём язык пользователя (из БД)
    tg_user = await async_get_telegram_user(update.message.from_user.id)
    lang = tg_user.language

    # Текст вопроса
    if lang == 'ru':
        q_text = question.question_text_ru
    elif lang == 'uz':
        q_text = question.question_text_uz
    elif lang == 'en':
        q_text = question.question_text_en
    else:
        q_text = question.question_text_kk

    # Кнопки "Да"/"Нет"
    keyboard = [["Да", "Нет"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)

    await update.message.reply_text(
        f"Вопрос {question.question_number}: {q_text}",
        reply_markup=reply_markup
    )
    # Остаёмся в состоянии ASKING_QUESTION, ждём ответа
    return ASKING_QUESTION


async def handle_user_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Принимаем ответ пользователя на текущий вопрос,
    сохраняем в user_data, переходим к следующему вопросу.
    """
    questions = context.user_data.get('questions', [])
    current_index = context.user_data.get('current_index', 0)
    answers = context.user_data.get('answers', [])

    if current_index < len(questions):
        answer_text = update.message.text
        question_number = questions[current_index].question_number

        # Сохраняем «yes»/«no» в зависимости от ответа
        if answer_text.strip().lower().startswith('д'):  # "да"
            user_answer = 'yes'
        else:
            user_answer = 'no'

        answers.append((question_number, user_answer))
        context.user_data['answers'] = answers
        context.user_data['current_index'] = current_index + 1

    # Переходим к задаче следующего вопроса
    return await ask_next_question(update, context)


async def finish_survey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Завершаем опрос: подсчитываем результат, сохраняем в БД, выводим пользователю.
    """
    answers = context.user_data.get('answers', [])
    score = calculate_mchat_score(answers)
    risk_level = get_risk_level(score)

    tg_user = await async_get_telegram_user(update.message.from_user.id)
    await async_create_survey_result(tg_user, score, risk_level)

    if risk_level == 'LOW':
        msg = f"Ваш результат: {score}. Низкий риск."
    elif risk_level == 'MEDIUM':
        msg = f"Ваш результат: {score}. Средний риск."
    else:
        msg = f"Ваш результат: {score}. Высокий риск."

    await update.message.reply_text(msg)
    return ConversationHandler.END


def run_telegram_bot():
    """
    Запуск бота. Обычно вызывается, например, из django custom command
    или скриптом manage.py (если написать custom command).
    """
    # Здесь мы ещё не в асинхронном контексте, ORM можно вызывать без sync_to_async,
    # но при желании это тоже можно обернуть в sync_to_async, если нужно.
    bot_settings = BotSettings.objects.first()
    if not bot_settings:
        print("BotSettings not found! Please add them via admin.")
        return

    # Создаём приложение
    application = ApplicationBuilder().token(bot_settings.bot_token).build()

    # Создаём ConversationHandler с двумя основными состояниями
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_command)],
        states={
            LANG_CHOICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_language),
            ],
            ASKING_QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_answer),
            ],
        },
        fallbacks=[CommandHandler('start', start_command)],
    )

    application.add_handler(conv_handler)
    application.run_polling()
