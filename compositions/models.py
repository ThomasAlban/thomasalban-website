from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models

from core.markdown import render_prose
from core.validators import IMAGE_HELP_TEXT, validate_image_extension

from .listening import (
    listening_embed_url, safe_listening_url, validate_audio_file_size,
    validate_listening_url,
)


class CompositionQuerySet(models.QuerySet):
    def published(self):
        return self.filter(is_published=True)


class Composition(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(
        blank=True,
        help_text=(
            'Markdown supported: *italics*, **bold**, [link text](https://example.com) '
            'or [compositions](/compositions/). Use blank lines between paragraphs '
            'and start list items with "- ". Raw HTML and images are not supported.'
        ),
    )
    text = models.TextField(
        blank=True,
        help_text=(
            'Optional sung text for choral or vocal compositions, in any language. '
            'Markdown supported: *italics*, **bold**, [source](https://example.com). '
            'Single line breaks are preserved; use blank lines between verses or paragraphs. '
            'Include any translation here and tick Has translation below; '
            'add italics yourself if wanted. Raw HTML and images are not supported.'
        ),
    )
    has_translation = models.BooleanField(
        default=False,
        help_text='Tick if the Text field includes a translation. Changes the heading to "Text and translation".',
    )
    year_composed = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1), MaxValueValidator(9999)],
    )
    premiered_date = models.DateField(blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, db_index=True)
    instrumentation = models.CharField(max_length=200, blank=True)
    duration_seconds = models.PositiveIntegerField(
        blank=True, null=True, validators=[MinValueValidator(1)],
    )
    audio_file = models.FileField(
        upload_to='audio/%Y/%m/',
        blank=True,
        validators=[
            FileExtensionValidator(['mp3', 'wav', 'ogg', 'm4a']),
            validate_audio_file_size,
        ],
        help_text='MP3, WAV, OGG or M4A; maximum 50 MiB. Extension and size checks do not verify file content.',
    )
    audio_credit = models.CharField(
        max_length=500, blank=True,
        help_text='Optional credit for this uploaded recording. Enter only verified information.',
    )
    is_published = models.BooleanField(default=False, db_index=True)
    is_featured = models.BooleanField(default=False)
    seo_description = models.CharField(max_length=300, blank=True)

    objects = CompositionQuerySet.as_manager()

    class Meta:
        # Dated premieres first; undated works fall back to year, then insertion order.
        ordering = [
            models.F('premiered_date').desc(nulls_last=True),
            models.F('year_composed').desc(nulls_last=True),
            '-pk',
        ]

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('compositions:detail', kwargs={'slug': self.slug})

    @property
    def rendered_description(self):
        return render_prose(self.description)

    @property
    def rendered_text(self):
        return render_prose(self.text, preserve_line_breaks=True)

    @property
    def safe_listening_links(self):
        return [link for link in self.listening_links.all() if link.safe_url]

    @property
    def duration_display(self):
        if not self.duration_seconds:
            return ''
        approximate_seconds = max(30, ((self.duration_seconds + 15) // 30) * 30)
        minutes, seconds = divmod(approximate_seconds, 60)
        return f'c. {minutes}:{seconds:02d}'

    def __str__(self):
        return self.title


class ListeningLink(models.Model):
    composition = models.ForeignKey(
        Composition, on_delete=models.CASCADE, related_name='listening_links',
    )
    label = models.CharField(max_length=200)
    url = models.URLField(max_length=500, validators=[validate_listening_url])
    credit = models.CharField(
        max_length=500, blank=True,
        help_text='Optional credit for this recording. Enter only verified information.',
    )
    position = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ['position', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['composition'],
                condition=models.Q(is_primary=True),
                name='unique_primary_listening_link',
                violation_error_message='Choose at most one primary listening link per composition.',
            ),
        ]

    @property
    def safe_url(self):
        return safe_listening_url(self.url)

    @property
    def embed_url(self):
        return listening_embed_url(self.url)

    def __str__(self):
        return self.label


class CompositionImage(models.Model):
    composition = models.ForeignKey(
        Composition, on_delete=models.CASCADE, related_name='images',
    )
    image = models.ImageField(
        upload_to='composition_images/%Y/%m/',
        validators=[validate_image_extension], help_text=IMAGE_HELP_TEXT,
    )
    alt_text = models.CharField(
        max_length=250, help_text='Describe this composition image for screen readers.',
    )
    caption = models.CharField(max_length=500, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'pk']

    def __str__(self):
        return f'{self.composition.title} - image {self.position}'


class ScorePreview(models.Model):
    composition = models.ForeignKey(
        Composition, on_delete=models.CASCADE, related_name='score_previews',
    )
    image = models.ImageField(
        upload_to='score_previews/%Y/%m/',
        validators=[validate_image_extension], help_text=IMAGE_HELP_TEXT,
    )
    alt_text = models.CharField(
        max_length=250, help_text='Describe this score preview for screen readers.',
    )
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'pk']

    def __str__(self):
        return f'{self.composition.title} - preview {self.position}'
