from django.db import models


class TelegramUser(models.Model):
    objects = None
    telegram_id = models.BigIntegerField(unique=True)
    # language хранит выбранный язык, например 'ru', 'uz', 'en', 'kk'
    language = models.CharField(max_length=2, default='ru')
    username = models.CharField(max_length=255, null=True, blank=True)
    current_question_index = models.IntegerField(default=0)  # <--- добавляем поле
    answers = models.JSONField(default=list)  # <--- храним ответы

    def __str__(self):
        return f"{self.username or self.telegram_id}"


class MChatQuestion(models.Model):
    objects = None
    question_number = models.PositiveIntegerField()
    question_text_ru = models.TextField()
    question_text_uz = models.TextField()
    question_text_en = models.TextField()
    question_text_kk = models.TextField()

    def __str__(self):
        return f"Q{self.question_number}"


class SurveyResult(models.Model):
    objects = None
    RISK_LEVEL_CHOICES = (
        ('LOW', 'Низкий риск'),
        ('MEDIUM', 'Средний риск'),
        ('HIGH', 'Высокий риск'),
    )
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE)
    result_score = models.PositiveIntegerField()
    risk_level = models.CharField(max_length=6, choices=RISK_LEVEL_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"SurveyResult (User: {self.user}, Score: {self.result_score})"


class BotSettings(models.Model):
    objects = None
    bot_token = models.CharField(max_length=200)

    # Приветственные сообщения
    welcome_message_ru = models.TextField(default="Здравствуйте! Добро пожаловать в M-CHAT-R бот.")
    welcome_message_uz = models.TextField(default="Salom! M-CHAT-R botiga xush kelibsiz.")
    welcome_message_en = models.TextField(default="Hello! Welcome to the M-CHAT-R bot.")
    welcome_message_kk = models.TextField(default="Sálem! M-CHAT-R botına xosh keldińiz.")

    # Если нужно хранить другие настройки, можете добавить поля

    def __str__(self):
        return "Bot Settings"
