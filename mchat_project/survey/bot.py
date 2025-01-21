import json
import logging

from asgiref.sync import sync_to_async
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes
)

from .models import TelegramUser, MChatQuestion, SurveyResult, BotSettings
from .utils import calculate_mchat_score, get_risk_level

# ---------------------------------------------------------------------------------------
# CONSTANTS: STATES FOR CONVERSATION HANDLER
# ---------------------------------------------------------------------------------------
LANG_CHOICE, START_SURVEY, ASKING_QUESTION = range(3)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


# ---------------------------------------------------------------------------------------
# ASYNC WRAPPERS ДЛЯ ОПЕРАЦИЙ С БД (sync_to_async)
# ---------------------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------------------
# Локализация текстов (пример)
# ---------------------------------------------------------------------------------------
def get_localized_text(lang, text_type):
    texts = {
        "question": {
            "ru": "Вопрос", "uz": "Савол", "en": "Question", "kk": "Сұрақ"
        },
        "survey_cancelled": {
            "ru": "Опрос был прерван.", "uz": "Сўров тухтатилди.",
            "en": "The survey was cancelled.", "kk": "Сауалнама тоқтатылды."
        },
        "survey_start_button": {
            "ru": "Нажмите 'Начать', чтобы начать опрос.",
            "uz": "Сўровни бошлаш учун 'Сўров' тугмасини босинг",
            "en": "Press the 'Start' button to start survey",
            "kk": "Сураўды бастаў үшін «Бастаў» дегенге басыңыз."
        },
        "finish_result_text": {
            "ru": "Ваш результат:", "uz": "Сизнинг натижангиз:",
            "en": "Your result:", "kk": "Сиздиң натийжеңіз:"
        },
        "finish_result_low": {
            "ru": "Низкий риск", "uz": "Кам хавф",
            "en": "Low risk", "kk": "Аз қауып"
        },
        "finish_result_medium": {
            "ru": "Средний риск", "uz": "Ўртача хавф",
            "en": "Medium risk", "kk": "Орташа қауып"
        },
        "finish_result_high": {
            "ru": "Высокий риск", "uz": "Юқори хавф",
            "en": "High risk", "kk": "Жоғары қауып"
        }
    }
    return texts[text_type][lang]


def get_localized_buttons(lang, button_type):
    buttons = {
        "yes": {"ru": "Да", "uz": "Ха", "en": "Yes", "kk": "Иә"},
        "no": {"ru": "Нет", "uz": "Йўк", "en": "No", "kk": "Жоқ"},
        "start": {"ru": "Начать", "uz": "Бошлаш", "en": "Start", "kk": "Бастау"},
        "restart": {"ru": "Завершить", "uz": "Якунлаш", "en": "Finish", "kk": "Аяқтау"}
    }
    return buttons[button_type][lang]


# ---------------------------------------------------------------------------------------
# Хэндлеры: start_command, choose_language, start_survey, ask_next_question, handle_user_answer, finish_survey
# ---------------------------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /start — приветствие и предложение выбрать язык.
    """
    keyboard = [
        ["Русский (ru)", "Ўзбек (uz)"],
        ["English (en)", "Qaraqalpaqsha (kk)"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    await update.message.reply_text(
        "Пожалуйста, выберите язык / Илтимос, тилни танланг / Please choose a language / Тілді таңдаңыз:",
        reply_markup=reply_markup
    )
    return LANG_CHOICE


async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка выбранного языка и вывод кнопки "Начать".
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

    tg_user = await async_get_or_create_telegram_user(
        telegram_id=user.id,
        username=user.username,
        lang=lang
    )

    context.user_data['language'] = lang
    start_button = get_localized_buttons(lang, "start")
    keyboard = [[start_button]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)

    survey_button_text = get_localized_text(lang, "survey_start_button")

    await update.message.reply_text(survey_button_text, reply_markup=reply_markup)
    return START_SURVEY


async def start_survey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Начинает опрос, загружает вопросы и переходит к первому вопросу.
    """
    questions = await async_order_questions()
    context.user_data['questions'] = questions
    context.user_data['answers'] = []
    context.user_data['current_index'] = 0

    await ask_next_question(update, context)
    return ASKING_QUESTION


async def ask_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Задаёт текущий вопрос и добавляет кнопку "Завершить".
    """
    questions = context.user_data.get('questions', [])
    current_index = context.user_data.get('current_index', 0)

    if current_index >= len(questions):
        return await finish_survey(update, context)

    question = questions[current_index]
    lang = context.user_data.get('language')

    if lang == 'ru':
        q_text = question.question_text_ru
    elif lang == 'uz':
        q_text = question.question_text_uz
    elif lang == 'en':
        q_text = question.question_text_en
    else:
        q_text = question.question_text_kk

    question_label = get_localized_text(lang, "question")
    yes_button = get_localized_buttons(lang, "yes")
    no_button = get_localized_buttons(lang, "no")
    restart_button = get_localized_buttons(lang, "restart")

    keyboard = [[yes_button, no_button], [restart_button]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)

    await update.message.reply_text(
        f"{question_label} {question.question_number}: {q_text}",
        reply_markup=reply_markup
    )
    return ASKING_QUESTION


async def handle_user_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает ответы пользователя.
    """
    answer_text = update.message.text
    lang = context.user_data.get('language')

    if answer_text == get_localized_buttons(lang, "restart"):
        # Пользователь нажал "Завершить" (или аналог)
        context.user_data.clear()  # Сбрасываем состояние
        await update.message.reply_text(
            "Возвращаемся к выбору языка...",
            reply_markup=ReplyKeyboardMarkup([[
                "Русский (ru)", "Ўзбек (uz)"
            ], [
                "English (en)", "Qaraqalpaqsha (kk)"
            ]], one_time_keyboard=True)
        )
        return LANG_CHOICE

    questions = context.user_data.get('questions', [])
    current_index = context.user_data.get('current_index', 0)
    answers = context.user_data.get('answers', [])

    if current_index < len(questions):
        question_number = questions[current_index].question_number
        yes_button = get_localized_buttons(lang, "yes")
        user_answer = 'yes' if answer_text == yes_button else 'no'
        answers.append((question_number, user_answer))

        context.user_data['answers'] = answers
        context.user_data['current_index'] = current_index + 1

    return await ask_next_question(update, context)


async def finish_survey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Завершает опрос, подсчитывает результат и сохраняет его в БД.
    """
    answers = context.user_data.get('answers', [])
    score = calculate_mchat_score(answers)
    risk_level = get_risk_level(score)

    tg_user = await async_get_telegram_user(update.message.from_user.id)
    await async_create_survey_result(tg_user, score, risk_level)

    lang = context.user_data.get('language')
    finish_result_risk = get_localized_text(lang, "finish_result_text")
    finish_result_low = get_localized_text(lang, "finish_result_low")
    finish_result_medium = get_localized_text(lang, "finish_result_medium")
    finish_result_high = get_localized_text(lang, "finish_result_high")

    if risk_level == 'LOW':
        msg = f"{finish_result_risk} {score}. {finish_result_low}."
    elif risk_level == 'MEDIUM':
        msg = f"{finish_result_risk} {score}. {finish_result_medium}."
    else:
        msg = f"{finish_result_risk} {score}. {finish_result_high}."

    restart_button = get_localized_buttons(lang, "restart")
    keyboard = [[restart_button]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)

    await update.message.reply_text(msg, reply_markup=reply_markup)

    # Сбрасываем данные пользователя
    context.user_data.clear()

    await update.message.reply_text(
        "Возвращаемся к выбору языка...",
        reply_markup=ReplyKeyboardMarkup([[
            "Русский (ru)", "Ўзбек (uz)"
        ], [
            "English (en)", "Qaraqалpaqsha (kk)"
        ]], one_time_keyboard=True)
    )
    return LANG_CHOICE


# ---------------------------------------------------------------------------------------
# Создаём само приложение (Application) и регистрируем хэндлеры
# ---------------------------------------------------------------------------------------
application = Application.builder().token(settings.TELEGRAM_TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start_command)],
    states={
        LANG_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_language)],
        START_SURVEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, start_survey)],
        ASKING_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_answer)]
    },
    fallbacks=[],
)
application.add_handler(conv_handler)


# ---------------------------------------------------------------------------------------
# Django view для приёма вебхуков
# ---------------------------------------------------------------------------------------
@csrf_exempt
async def telegram_webhook(request):
    """
    Основная view-функция, которая будет принимать POST-запросы от Telegram.
    """
    if request.method == "POST":
        # Считываем JSON-данные из body
        update_data = json.loads(request.body.decode("utf-8"))
        # Превращаем их в объект Update
        update = Update.de_json(update_data, application.bot)
        # Передаём апдейты в приложение Telegram
        await application.process_update(update)
        return HttpResponse("OK")
    else:
        return HttpResponse("Method not allowed", status=405)
