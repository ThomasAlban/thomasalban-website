from django import forms


class EnquiryForm(forms.Form):
    name = forms.CharField(max_length=200)
    email = forms.EmailField()
    copy_count = forms.IntegerField(
        label='Approx. Copy Count', required=False, min_value=1,
        help_text='Optional - an estimate is fine.',
    )
    message = forms.CharField(required=False, max_length=10000, widget=forms.Textarea)
    website = forms.CharField(required=False, strip=False, widget=forms.HiddenInput)

    def __init__(self, *args, include_copy_count=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not include_copy_count:
            self.fields.pop('copy_count')
