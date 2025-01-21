from django.urls import path
from .telegram_bot import telegram_webhook

urlpatterns = [
    path('survey-webhook/', telegram_webhook, name='survey_webhook'),
]
