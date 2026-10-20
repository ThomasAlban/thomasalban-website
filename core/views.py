from django.db.models import Prefetch
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from compositions.models import Composition, CompositionImage

from .enquiries import deliver_enquiry
from .forms import EnquiryForm
from .models import Biography, BiographyPhoto
from .seo import absolute_url, homepage_schema, page_context, person_schema


@require_http_methods(['GET'])
def home(request):
    works = Composition.objects.published().prefetch_related(Prefetch(
        'images', queryset=CompositionImage.objects.exclude(image='')[:1],
        to_attr='thumbnail_images',
    ))
    featured = works.filter(slug='nunc-dimittis').first() or works.filter(is_featured=True).first()
    context = page_context(
        'Thomas Alban - Composer',
        'Discover music by composer Thomas Alban. Explore compositions, recordings and score previews, and enquire about scores.',
        reverse('core:home'), 'home', schema=homepage_schema(),
        image=BiographyPhoto.objects.exclude(image='').first(),
    )
    context.update(featured=featured, recent_works=works[:6])
    return render(request, 'core/home.html', context)


@require_http_methods(['GET'])
def about(request):
    context = page_context(
        'About - Thomas Alban', 'Thomas Alban, composer. Explore his music and get in touch.',
        reverse('core:about'), 'about', schema=person_schema(),
        image=BiographyPhoto.objects.exclude(image='').first(),
    )
    context['biography'] = Biography.objects.first()
    context['photos'] = BiographyPhoto.objects.all()
    return render(request, 'core/about.html', context)


@require_http_methods(['GET', 'POST'])
def contact(request):
    form = EnquiryForm(
        request.POST if request.method == 'POST' else None, include_copy_count=False,
    )
    if request.method == 'POST' and form.is_valid():
        if deliver_enquiry(request, form):
            request.session['contact_sent'] = True
            return redirect('core:contact')
    sent = request.session.pop('contact_sent', False) if request.method == 'GET' else False
    context = page_context(
        'Contact - Thomas Alban', 'Contact Thomas Alban about his compositions and scores.',
        reverse('core:contact'), 'contact',
    )
    context.update(form=form, sent=sent)
    return render(request, 'core/contact.html', context)


def csrf_failure(request, reason=''):
    # Do not expose security diagnostics or submitted data to visitors.
    return render(request, '403.html', {'csrf_failure': True}, status=403)


@require_http_methods(['GET'])
def robots(request):
    return HttpResponse(
        'User-agent: *\nAllow: /\nDisallow: /admin/\n\n'
        f'Sitemap: {absolute_url(reverse("sitemap"))}\n',
        content_type='text/plain',
    )
