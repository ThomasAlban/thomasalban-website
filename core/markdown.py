from django.utils.safestring import mark_safe
from markdown_it import MarkdownIt
import nh3


# Only the formatting needed for biography prose; raw HTML and images are disabled.
_parser = MarkdownIt('commonmark', {'html': False}).disable([
    'image', 'heading', 'lheading', 'blockquote', 'code', 'fence', 'hr', 'backticks',
])


def render_biography(text):
    html = _parser.render(text)
    cleaned = nh3.clean(
        html,
        tags={'p', 'br', 'em', 'strong', 'a', 'ul', 'ol', 'li'},
        attributes={'a': {'href', 'title'}, 'ol': {'start'}},
        url_schemes={'http', 'https', 'mailto'},
        link_rel='noopener noreferrer',
    )
    # Only sanitised output may bypass Django's template autoescaping.
    return mark_safe(cleaned)
