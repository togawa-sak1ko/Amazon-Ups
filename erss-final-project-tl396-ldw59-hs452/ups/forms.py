from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import QuoteServiceLevel, SupportTicketCategory


User = get_user_model()


class TrackingLookupForm(forms.Form):
    tracking_number = forms.CharField(
        max_length=32,
        label="Package ID or tracking number",
        widget=forms.TextInput(attrs={"placeholder": "123456789 or UPS-000123"}),
    )


class RedirectShipmentForm(forms.Form):
    destination_x = forms.IntegerField(label="New X coordinate")
    destination_y = forms.IntegerField(label="New Y coordinate")

    def __init__(self, *args, shipment=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.shipment = shipment

    def clean(self):
        cleaned_data = super().clean()
        if self.shipment is not None and not self.shipment.can_redirect():
            raise forms.ValidationError(
                "This shipment can no longer be redirected because it is already out for delivery."
            )
        return cleaned_data


class PortalSearchForm(forms.Form):
    query = forms.CharField(
        max_length=120,
        label="Search",
        widget=forms.TextInput(attrs={"placeholder": "Track, search, or find a service"}),
    )


class QuoteEstimateForm(forms.Form):
    service_level = forms.ChoiceField(choices=QuoteServiceLevel.choices, initial=QuoteServiceLevel.GROUND)
    origin_x = forms.IntegerField(label="Origin X")
    origin_y = forms.IntegerField(label="Origin Y")
    destination_x = forms.IntegerField(label="Destination X")
    destination_y = forms.IntegerField(label="Destination Y")
    package_count = forms.IntegerField(min_value=1, initial=1)
    total_weight_lbs = forms.DecimalField(min_value=0.1, decimal_places=2, max_digits=7, initial=1.0)


class SupportTicketForm(forms.Form):
    email = forms.EmailField()
    tracking_number = forms.CharField(max_length=32, required=False)
    category = forms.ChoiceField(choices=SupportTicketCategory.choices, initial=SupportTicketCategory.TRACKING)
    subject = forms.CharField(max_length=140)
    message = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}))


class SignUpForm(UserCreationForm):
    email = forms.EmailField()

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {
                "placeholder": "Choose a UPS username",
                "autocomplete": "username",
            }
        )
        self.fields["email"].widget.attrs.update(
            {
                "placeholder": "name@example.com",
                "autocomplete": "email",
            }
        )
        self.fields["password1"].widget.attrs.update(
            {
                "placeholder": "Create a password",
                "autocomplete": "new-password",
            }
        )
        self.fields["password2"].widget.attrs.update(
            {
                "placeholder": "Confirm the password",
                "autocomplete": "new-password",
            }
        )

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user
