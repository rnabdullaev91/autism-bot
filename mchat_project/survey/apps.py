from django.apps import AppConfig


class SurveyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'survey'

    # метод ready() можно вовсе не определять
    # (или оставить пустым, если хотите)
    def ready(self):
        pass
