from django.db import models

from .markdown import render_prose
from .validators import IMAGE_HELP_TEXT, validate_image_extension


class Biography(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    body = models.TextField(
        help_text=(
            'Markdown supported: *italics*, **bold**, [link text](https://example.com) '
            'or [compositions](/compositions/). Use blank lines between paragraphs '
            'and start list items with "- ". Raw HTML and images are not supported.'
        ),
    )

    class Meta:
        verbose_name_plural = 'biography'
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name='core_biography_singleton'),
        ]

    @property
    def rendered_body(self):
        return render_prose(self.body)

    def __str__(self):
        return 'Biography'


class BiographyPhoto(models.Model):
    image = models.ImageField(
        upload_to='biography_photos/%Y/%m/',
        validators=[validate_image_extension], help_text=IMAGE_HELP_TEXT,
    )
    alt_text = models.CharField(
        max_length=250, help_text='Describe this biography photo for screen readers.',
    )
    caption = models.CharField(
        max_length=500, blank=True, help_text='Optional caption or photographer credit.',
    )
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'pk']

    def __str__(self):
        return self.alt_text
