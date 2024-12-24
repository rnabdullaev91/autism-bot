import sys
from django.core.management.base import BaseCommand
from survey.bot import run_telegram_bot

class Command(BaseCommand):
    help = 'Runs the Telegram bot'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting Telegram Bot..."))
        try:
            run_telegram_bot()
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Bot stopped by user."))
            sys.exit(0)
