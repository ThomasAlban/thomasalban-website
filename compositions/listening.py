import re
from urllib.parse import parse_qs, urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


def validate_listening_url(value):
    """Accept absolute HTTP(S) links without credentials or ambiguous syntax."""
    try:
        if not isinstance(value, str) or any(
            char.isspace() or ord(char) < 32 or ord(char) == 127 or char == '\\'
            for char in value
        ):
            raise ValueError
        URLValidator(schemes=['http', 'https'])(value)
        parts = urlsplit(value)
        if parts.username is not None or parts.password is not None:
            raise ValueError
        # Accessing port also rejects out-of-range ports.
        parts.port
        if parts.netloc.endswith(':'):
            raise ValueError
    except (ValidationError, ValueError, TypeError):
        raise ValidationError(
            'Enter a valid HTTP or HTTPS URL without credentials.', code='invalid',
        )


def safe_listening_url(value):
    """Validate again at display time: imports may bypass model validation."""
    try:
        validate_listening_url(value)
    except ValidationError:
        return ''
    return value


MAX_AUDIO_FILE_SIZE = 50 * 1024 * 1024


def validate_audio_file_size(value):
    if value.size > MAX_AUDIO_FILE_SIZE:
        raise ValidationError('Audio files must be no larger than 50 MiB.', code='file_too_large')


def listening_embed_url(url):
    """Return a fixed-provider embed URL, or '' for an external-only link."""
    if not safe_listening_url(url):
        return ''
    try:
        parts = urlsplit(url)
        if (
            parts.scheme not in {'http', 'https'}
            or parts.username is not None
            or parts.password is not None
            or parts.port is not None
            or parts.netloc.lower() != parts.hostname
        ):
            return ''
    except (ValueError, TypeError):
        return ''

    host = parts.hostname
    video_id = None
    if host in {'youtube.com', 'www.youtube.com', 'm.youtube.com'}:
        if parts.path == '/watch':
            values = parse_qs(parts.query).get('v', [])
            if len(values) == 1:
                video_id = values[0]
        else:
            match = re.fullmatch(r'/(?:shorts|embed)/([A-Za-z0-9_-]{11})', parts.path)
            if match:
                video_id = match[1]
    elif host == 'youtu.be':
        match = re.fullmatch(r'/([A-Za-z0-9_-]{11})', parts.path)
        if match:
            video_id = match[1]
    elif host == 'open.spotify.com':
        match = re.fullmatch(r'/(track|album|playlist|episode|show)/([A-Za-z0-9]+)', parts.path)
        if match:
            return f'https://open.spotify.com/embed/{match[1]}/{match[2]}?theme=0'

    if video_id and re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        return f'https://www.youtube-nocookie.com/embed/{video_id}'
    return ''
