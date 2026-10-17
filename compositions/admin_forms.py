from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms.models import BaseInlineFormSet, ModelForm

from .listening import validate_listening_url
from .models import ListeningLink


class ListeningLinkInlineForm(ModelForm):
    # Require an explicit scheme rather than URLField's automatic HTTPS prefix.
    url = forms.CharField(
        max_length=500, strip=False, widget=forms.URLInput,
        validators=[validate_listening_url],
    )

    class Meta:
        model = ListeningLink
        fields = ['label', 'url', 'credit', 'position', 'is_primary']

    def validate_constraints(self):
        # The formset validates the final primary selection; checking this FK
        # against current database rows would reject a legitimate switch.
        exclude = self._get_validation_exclusions() | {'composition'}
        try:
            self.instance.validate_constraints(exclude=exclude)
        except ValidationError as error:
            self._update_errors(error)


class ListeningLinkInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        primaries = [
            form for form in self.forms
            if form.cleaned_data.get('is_primary')
            and not form.cleaned_data.get('DELETE')
        ]
        if len(primaries) > 1:
            raise ValidationError('Choose at most one primary listening link per composition.')

    def save(self, commit=True):
        if not commit:
            return super().save(commit=False)
        # Demote before promoting, regardless of inline ordering. Deleted primary
        # rows also need demoting before Django saves changed/new rows.
        demoted_ids = [
            form.instance.pk for form in self.initial_forms
            if form.instance.pk and (
                form.cleaned_data.get('DELETE')
                or not form.cleaned_data.get('is_primary')
            )
        ]
        database = self.get_queryset().db
        with transaction.atomic(using=database):
            self.get_queryset().filter(pk__in=demoted_ids, is_primary=True).update(is_primary=False)
            return super().save(commit=True)
