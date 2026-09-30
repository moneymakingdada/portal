from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Organization, Wallet


@receiver(post_save, sender=Organization)
def create_wallet(sender, instance, created, **kwargs):
    """Every organization gets exactly one wallet, however it was created."""
    if created:
        Wallet.objects.get_or_create(organization=instance)
