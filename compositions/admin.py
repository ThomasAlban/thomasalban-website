from django.contrib import admin

from .admin_forms import ListeningLinkInlineForm, ListeningLinkInlineFormSet
from .models import Composition, CompositionImage, ListeningLink, ScorePreview


class ListeningLinkInline(admin.TabularInline):
    model = ListeningLink
    form = ListeningLinkInlineForm
    formset = ListeningLinkInlineFormSet
    extra = 0
    fields = ['label', 'url', 'credit', 'position', 'is_primary']


class ScorePreviewInline(admin.TabularInline):
    model = ScorePreview
    extra = 0
    fields = ['image', 'alt_text', 'position']


class CompositionImageInline(admin.TabularInline):
    model = CompositionImage
    extra = 0
    fields = ['image', 'alt_text', 'caption', 'position']


@admin.register(Composition)
class CompositionAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'category', 'year_composed', 'premiered_date',
        'is_published', 'is_featured',
    ]
    list_filter = ['is_published', 'is_featured', 'category']
    search_fields = ['title', 'description', 'instrumentation']
    prepopulated_fields = {'slug': ('title',)}
    inlines = [ScorePreviewInline, ListeningLinkInline, CompositionImageInline]

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == 'duration_seconds':
            field.label = 'Approximate duration (seconds)'
            field.help_text = 'Enter any positive whole number of seconds. Display is rounded to the nearest 30 seconds (at least c. 0:30); the stored value is unchanged.'
            field.widget.attrs['step'] = 1
            field.widget.attrs['min'] = 1
        return field
