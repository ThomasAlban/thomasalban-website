from django.core.validators import FileExtensionValidator


# Keep in sync with the image formats served by deploy/nginx.conf.
IMAGE_EXTENSIONS = ('jpg', 'jpeg', 'png', 'gif', 'webp', 'avif')
IMAGE_HELP_TEXT = 'Upload a JPG/JPEG, PNG, GIF, WebP or AVIF image. Re-export other formats before uploading.'
validate_image_extension = FileExtensionValidator(
    allowed_extensions=IMAGE_EXTENSIONS,
    message='Unsupported image extension. Upload a JPG/JPEG, PNG, GIF, WebP or AVIF image.',
)
