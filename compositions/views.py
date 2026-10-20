from html import unescape

from django.db.models import F, Prefetch, Q
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import strip_tags
from django.views.decorators.http import require_http_methods

from core.enquiries import deliver_enquiry
from core.forms import EnquiryForm
from core.seo import absolute_url, page_context, person_schema

from .forms import CatalogueFilterForm
from .models import Composition, CompositionImage


@require_http_methods(['GET'])
def catalogue(request):
    works = Composition.objects.published()
    filter_options = list(works.order_by().values_list('category', 'year_composed').distinct())
    categories = sorted({category for category, year in filter_options if category})
    years = sorted({year for category, year in filter_options if year is not None}, reverse=True)
    form = CatalogueFilterForm(request.GET, categories=categories, years=years)
    category = duration = query = ''
    selected_years = []
    sort = 'premiered_date'
    if form.is_valid():
        category = form.cleaned_data['category']
        duration = form.cleaned_data['duration']
        query = form.cleaned_data['q']
        selected_years = form.cleaned_data['years']
        sort = form.cleaned_data['sort'] or 'premiered_date'
        if query:
            works = works.filter(
                Q(title__icontains=query) | Q(category__icontains=query)
                | Q(instrumentation__icontains=query),
            )
        if selected_years:
            works = works.filter(year_composed__in=selected_years)
        if category:
            works = works.filter(category=category)
        if duration == 'short':
            works = works.filter(duration_seconds__lt=300)
        elif duration == 'medium':
            works = works.filter(duration_seconds__gte=300, duration_seconds__lte=600)
        elif duration == 'long':
            works = works.filter(duration_seconds__gt=600)
    if sort == 'alphabetical':
        works = works.order_by(Lower('title'), 'pk')
    elif sort == 'year_composed':
        works = works.order_by(
            F('year_composed').desc(nulls_last=True),
            F('premiered_date').desc(nulls_last=True), '-pk',
        )
    context = page_context(
        'Compositions - Thomas Alban',
        'Explore compositions by Thomas Alban, with recordings, score previews and score enquiries.',
        reverse('compositions:list'), 'compositions', noindex=bool(request.GET),
    )
    works = works.prefetch_related(Prefetch(
        'images', queryset=CompositionImage.objects.exclude(image='')[:1],
        to_attr='thumbnail_images',
    ))
    context.update(works=works, categories=categories, filter_form=form,
                   category=category, duration=duration,
                   has_filters=bool(category or duration or query or selected_years),
                   has_options=bool(request.GET))
    return render(request, 'compositions/list.html', context)


@require_http_methods(['GET', 'POST'])
def detail(request, slug):
    composition = get_object_or_404(
        Composition.objects.published().prefetch_related(
            'score_previews', 'listening_links', 'images',
        ), slug=slug,
    )
    form = EnquiryForm(request.POST if request.method == 'POST' else None)
    receipt_key = f'enquiry_sent_{composition.pk}'
    if request.method == 'POST' and form.is_valid():
        if deliver_enquiry(request, form, composition=composition):
            request.session[receipt_key] = True
            return redirect(composition.get_absolute_url())
    sent = request.session.pop(receipt_key, False) if request.method == 'GET' else False
    schema = {
        '@context': 'https://schema.org', '@type': 'MusicComposition',
        'name': composition.title,
        'url': absolute_url(composition.get_absolute_url()),
        'composer': {'@type': 'Person', 'name': 'Thomas Alban',
                     '@id': person_schema()['@id']},
    }
    if composition.instrumentation:
        schema['musicalInstrumentation'] = composition.instrumentation
    if composition.description:
        schema['description'] = ' '.join(
            unescape(strip_tags(composition.rendered_description)).split(),
        )
    breadcrumbs = [
        {'name': 'Home', 'url': reverse('core:home')},
        {'name': 'Compositions', 'url': reverse('compositions:list')},
        {'name': composition.title, 'url': composition.get_absolute_url()},
    ]
    breadcrumb_schema = {
        '@type': 'BreadcrumbList',
        'itemListElement': [
            {'@type': 'ListItem', 'position': position, 'name': crumb['name'],
             'item': absolute_url(crumb['url'])}
            for position, crumb in enumerate(breadcrumbs, start=1)
        ],
    }
    schema.pop('@context')
    schema = {'@context': 'https://schema.org', '@graph': [schema, breadcrumb_schema]}
    title = f'{composition.title} - Thomas Alban'
    instrumentation = f' for {composition.instrumentation}' if composition.instrumentation else ''
    description = (
        f'{composition.title} by Thomas Alban. '
        f'Explore this composition{instrumentation} and enquire about the score.'
    )
    image = next((image for image in composition.images.all() if image.image), None)
    context = page_context(
        title,
        composition.seo_description or description,
        composition.get_absolute_url(), 'compositions', schema=schema, image=image,
    )
    context.update(composition=composition, form=form, sent=sent, breadcrumbs=breadcrumbs)
    return render(request, 'compositions/detail.html', context)
