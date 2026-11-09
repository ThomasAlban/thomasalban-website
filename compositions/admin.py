from django.contrib import admin

from django.db.models import Prefetch

from .admin_forms import ListeningLinkInlineForm, ListeningLinkInlineFormSet
from .models import Category, Composition, CompositionCategory, CompositionImage, ListeningLink, ScorePreview


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ['name']


class CompositionCategoryInline(admin.TabularInline):
    model = CompositionCategory
    extra = 0
    fields = ['category', 'position']


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
        'title', 'display_categories', 'year_composed', 'premiered_date',
        'is_published', 'is_featured',
    ]
    list_filter = ['is_published', 'is_featured', 'categories']
    search_fields = ['title', 'description', 'instrumentation']
    prepopulated_fields = {'slug': ('title',)}
    inlines = [CompositionCategoryInline, ScorePreviewInline, ListeningLinkInline, CompositionImageInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related(Prefetch(
            'category_memberships', queryset=CompositionCategory.objects.select_related('category'),
        ))

    @admin.display(description='Categories')
    def display_categories(self, obj):
        return obj.categories_display

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == 'duration_seconds':
            field.label = 'Approximate duration (seconds)'
            field.help_text = 'Enter any positive whole number of seconds. Display is rounded to the nearest 30 seconds (at least c. 0:30); the stored value is unchanged.'
            field.widget.attrs['step'] = 1
            field.widget.attrs['min'] = 1
        return field
