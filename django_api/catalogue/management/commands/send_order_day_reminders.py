"""Morning nudge for shops whose order day is today."""

from django.core.management.base import BaseCommand

from catalogue.push import send_order_day_reminders


class Command(BaseCommand):
    help = "Push 'today is your order day' to shops scheduled for today."

    def handle(self, *args, **options):
        shops, sent = send_order_day_reminders()
        self.stdout.write(
            f"{shops} shop(s) scheduled today, {sent} notification(s) sent."
        )
