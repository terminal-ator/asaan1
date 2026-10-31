from django.core.management.base import BaseCommand

from catalogue.models import Product


class Command(BaseCommand):
    help = (
        "Hide every active product from the shop app so the catalogue can be "
        "rebuilt from best sellers. Nothing is deleted: orders keep their "
        "copies, and Console → Products → Quick add can restore any SKU."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Archive for real. Without it the command only reports the count.",
        )

    def handle(self, *args, **options):
        active = Product.objects.filter(active=True)
        count = active.count()
        if not options["yes"]:
            self.stdout.write(
                f"{count} active product(s) would be archived. Re-run with --yes to do it."
            )
            return
        active.update(active=False)
        self.stdout.write(self.style.SUCCESS(f"Archived {count} product(s)."))
