from django import forms


class CatalogueFilterForm(forms.Form):
    q = forms.CharField(
        label='Search', required=False, max_length=200,
        widget=forms.TextInput(attrs={
            'type': 'search',
            'placeholder': 'Title, category or instrumentation',
        }),
    )
    sort = forms.ChoiceField(
        label='Sort by', required=False,
        choices=[
            ('premiered_date', 'Date premiered (newest first)'),
            ('alphabetical', 'Alphabetical (A–Z)'),
            ('year_composed', 'Year composed (newest first)'),
        ],
    )
    years = forms.MultipleChoiceField(
        label='Year composed', required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='Select one or more years, or leave all unchecked for any year.',
    )
    category = forms.ChoiceField(required=False)
    duration = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'Any duration'),
            ('short', 'Under 5 minutes'),
            ('medium', '5–10 minutes'),
            ('long', 'Over 10 minutes'),
        ],
    )

    def __init__(self, *args, categories, years=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['years'].choices = [(str(year), str(year)) for year in years]
        self.fields['category'].choices = [('', 'All categories')] + [
            (category, category) for category in categories
        ]
