"""Morning push for today's Subway-style deal."""

from django.core.management.base import BaseCommand

from catalogue.push import send_daily_deal


class Command(BaseCommand):
    help = "Push today's daily deal to every subscribed device."

    def handle(self, *args, **options):
        deal, sent = send_daily_deal()
        if not deal:
            self.stdout.write("No active deal for today.")
            return
        self.stdout.write(f"Today's deal: {deal} — {sent} notification(s) sent.")
