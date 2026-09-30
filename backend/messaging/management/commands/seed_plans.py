from django.conf import settings
from django.core.management.base import BaseCommand

from messaging.models import SmsPlan

# GHS price -> whether to flag as the popular choice
STARTER_PRICES_GHS = [(20, False), (50, True), (100, False), (200, False), (500, False)]


class Command(BaseCommand):
    help = (
        "Create a starter set of SMS plans (GHS 20 to 500) priced at the current per-message rate. "
        "Does nothing if plans already exist, unless --force is given. Edit or retire them in /admin."
    )

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Add the starter plans even if plans already exist.")

    def handle(self, *args, force, **options):
        if SmsPlan.objects.exists() and not force:
            self.stdout.write("Plans already exist; nothing to do (use --force to add the starter set anyway).")
            return
        unit = settings.DEFAULT_PRICE_PER_SEGMENT_PESEWAS
        for order, (ghs, popular) in enumerate(STARTER_PRICES_GHS):
            pesewas = ghs * 100
            messages = pesewas // unit
            SmsPlan.objects.create(
                name=f"GHS {ghs} - {messages:,} Messages", price_pesewas=pesewas, message_count=messages,
                is_popular=popular, sort_order=order,
            )
        self.stdout.write(self.style.SUCCESS(f"Created {len(STARTER_PRICES_GHS)} plans."))
