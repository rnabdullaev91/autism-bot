from django.urls import path
from .bot import telegram_webhook

urlpatterns = [
    path('webhook/', telegram_webhook, name='webhook'),
]
