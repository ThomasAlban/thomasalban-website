from django.utils.safestring import mark_safe
from markdown_it import MarkdownIt
import nh3


# Only simple prose formatting; raw HTML and images are disabled.
_parsers = {
    breaks: MarkdownIt('commonmark', {'html': False, 'breaks': breaks}).disable([
        'image', 'heading', 'lheading', 'blockquote', 'code', 'fence', 'hr', 'backticks',
    ])
    for breaks in (False, True)
}


def render_prose(text, *, preserve_line_breaks=False):
    html = _parsers[preserve_line_breaks].render(text)
    cleaned = nh3.clean(
        html,
        tags={'p', 'br', 'em', 'strong', 'a', 'ul', 'ol', 'li'},
        attributes={'a': {'href', 'title'}, 'ol': {'start'}},
        url_schemes={'http', 'https', 'mailto'},
        link_rel='noopener noreferrer',
    )
    # Only sanitised output may bypass Django's template autoescaping.
    return mark_safe(cleaned)
