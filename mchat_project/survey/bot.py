import json
import logging
import asyncio

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes
)

from asgiref.sync import sync_to_async
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from telegram import Update, ReplyKeyboardMarkup

from .models import BotSettings, TelegramUser, MChatQuestion, SurveyResult
from .utils import calculate_mchat_score, get_risk_level

logging.basicConfig(level=logging.INFO)

# -----------------------------------------------------------
# STATES
# -----------------------------------------------------------
LANG_CHOICE, START_SURVEY, ASKING_QUESTION = range(3)


class TelegramBotApplication:
    """Синглтон для безопасной инициализации Telegram Application."""
    _application = None
    _lock = asyncio.Lock()

    @staticmethod
    async def get_application():
        async with TelegramBotApplication._lock:
            if TelegramBotApplication._application is None:
                logging.info("Initializing Telegram Application...")
                token = await TelegramBotApplication.get_bot_token()
                if not token:
                    raise ValueError("Bot token not found in BotSettings!")

                app = Application.builder().token(token).read_timeout(30).write_timeout(30).build()
                TelegramBotApplication._setup_handlers(app)

                await app.initialize()
                TelegramBotApplication._application = app
                logging.info("Telegram Application initialized successfully!")

            return TelegramBotApplication._application

    @staticmethod
    @sync_to_async
    def get_bot_token():
        bot_settings = BotSettings.objects.first()
        return bot_settings.bot_token if bot_settings else None

    @staticmethod
    def _setup_handlers(app):
        """Добавление хендлеров для ConversationHandler."""
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start_command)],
            states={
                LANG_CHOICE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, choose_language)
                ],
                START_SURVEY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, start_survey)
                ],
                ASKING_QUESTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_answer)
                ],
            },
            fallbacks=[],
        )
        app.add_handler(conv_handler)


# -----------------------------------------------------------
# ASYNC WRAPPERS DB
# -----------------------------------------------------------
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
    return list(MChatQuestion.objects.order_by('question_number'))


@sync_to_async
def async_create_survey_result(tg_user, score, risk_level):
    return SurveyResult.objects.create(
        user=tg_user,
        result_score=score,
        risk_level=risk_level
    )


# -----------------------------------------------------------
# Локализация
# -----------------------------------------------------------
def get_localized_text(lang, text_type):
    texts = {
        "question": {"ru": "Вопрос", "uz": "Савол", "en": "Question", "kk": "Сұрақ"},
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
            "ru": "Низкий риск", "uz": "Кам хавф", "en": "Low risk", "kk": "Аз қауып"
        },
        "finish_result_medium": {
            "ru": "Средний риск", "uz": "Ўртача хавф", "en": "Medium risk", "kk": "Орташа қауып"
        },
        "finish_result_high": {
            "ru": "Высокий риск", "uz": "Юқори хавф", "en": "High risk", "kk": "Жоғары қауып"
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


# -----------------------------------------------------------
# Хендлеры (Conversation)
# -----------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["Русский (ru)", "Ўзбек (uz)"],
        ["English (en)", "Qaraqалpaqша (kk)"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    await update.message.reply_text(
        "Пожалуйста, выберите язык / Илтимос, тилни танланг / Please choose a language / Тілді таңдаңыз:",
        reply_markup=reply_markup
    )
    return LANG_CHOICE


async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    user = update.message.from_user

    lang = "ru" if "ru" in text else "uz" if "uz" in text else "en" if "en" in text else "kk"
    await async_get_or_create_telegram_user(
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
    questions = await async_order_questions()
    context.user_data['questions'] = questions
    context.user_data['answers'] = []
    context.user_data['current_index'] = 0

    await ask_next_question(update, context)
    return ASKING_QUESTION


async def ask_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    questions = context.user_data.get('questions', [])
    current_index = context.user_data.get('current_index', 0)

    if current_index >= len(questions):
        return await finish_survey(update, context)

    question = questions[current_index]
    lang = context.user_data.get('language', 'ru')
    q_text = getattr(question, f"question_text_{lang}", question.question_text_ru)

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
    answer_text = update.message.text
    lang = context.user_data.get('language', 'ru')

    if answer_text == get_localized_buttons(lang, "restart"):
        context.user_data.clear()
        return await start_command(update, context)

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
    answers = context.user_data.get('answers', [])
    score = calculate_mchat_score(answers)
    risk_level = get_risk_level(score)

    tg_user = await async_get_telegram_user(update.message.from_user.id)
    await async_create_survey_result(tg_user, score, risk_level)

    lang = context.user_data.get('language', 'ru')
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

    await update.message.reply_text(msg)
    return await start_command(update, context)


@csrf_exempt
async def telegram_webhook(request):
    if request.method == "POST":
        update_data = json.loads(request.body.decode("utf-8"))
        app = await TelegramBotApplication.get_application()
        update = Update.de_json(update_data, app.bot)
        await app.process_update(update)
        return HttpResponse("OK")
    return HttpResponse("Method not allowed", status=405)
