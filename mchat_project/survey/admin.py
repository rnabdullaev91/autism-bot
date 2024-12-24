from django.contrib import admin
from .models import TelegramUser, SurveyResult, MChatQuestion, BotSettings

@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ('telegram_id', 'username', 'language')
    search_fields = ('telegram_id', 'username')

@admin.register(MChatQuestion)
class MChatQuestionAdmin(admin.ModelAdmin):
    list_display = ('question_number', )
    ordering = ('question_number',)

@admin.register(SurveyResult)
class SurveyResultAdmin(admin.ModelAdmin):
    list_display = ('user', 'result_score', 'risk_level', 'created_at')
    list_filter = ('risk_level', 'created_at')

@admin.register(BotSettings)
class BotSettingsAdmin(admin.ModelAdmin):
    list_display = ('bot_token',)

