from django.contrib import admin

from .models import Biography, BiographyPhoto


@admin.register(Biography)
class BiographyAdmin(admin.ModelAdmin):
    fields = ['body']

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not Biography.objects.exists()


@admin.register(BiographyPhoto)
class BiographyPhotoAdmin(admin.ModelAdmin):
    list_display = ['alt_text', 'position', 'caption']
    list_editable = ['position']
    search_fields = ['alt_text', 'caption']
    fields = ['image', 'alt_text', 'caption', 'position']
