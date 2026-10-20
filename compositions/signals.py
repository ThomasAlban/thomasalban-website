"""Track composition page changes without inventing dates for existing content.

Bulk writes bypass save signals; importers must explicitly maintain updated_at.
"""

from django.db.models.signals import post_delete, post_save, pre_save
from django.utils import timezone

from .models import Composition, CompositionImage, ListeningLink, ScorePreview


def remember_change(sender, instance, raw=False, using='default', update_fields=None, **kwargs):
    if raw:
        return
    fields = [
        field.attname for field in sender._meta.concrete_fields
        if not field.primary_key and field.name != 'updated_at'
        and (update_fields is None or field.name in update_fields or field.attname in update_fields)
    ]
    old = sender.objects.using(using).filter(pk=instance.pk).values().first()
    if sender is Composition and old and update_fields is None:
        # A related edit may have advanced the database timestamp since this
        # instance was loaded. Never overwrite it with a stale instance value.
        instance.updated_at = old['updated_at']
    instance._seo_changed = old is None or any(
        old[field] != getattr(instance, field) for field in fields
    )
    instance._seo_previous_composition = old.get('composition_id') if old else None


def record_change(sender, instance, raw=False, using='default', **kwargs):
    if raw or not getattr(instance, '_seo_changed', False):
        return
    now = timezone.now()
    if sender is Composition:
        ids = [instance.pk]
        instance.updated_at = now
    else:
        ids = [instance.composition_id, instance._seo_previous_composition]
    Composition.objects.using(using).filter(pk__in=ids).update(updated_at=now)


def record_deletion(sender, instance, using='default', **kwargs):
    Composition.objects.using(using).filter(pk=instance.composition_id).update(updated_at=timezone.now())


for model in (Composition, CompositionImage, ListeningLink, ScorePreview):
    pre_save.connect(remember_change, sender=model)
    post_save.connect(record_change, sender=model)
    if model is not Composition:
        post_delete.connect(record_deletion, sender=model)
