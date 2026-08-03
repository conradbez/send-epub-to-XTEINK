from django import forms
from django.contrib.auth.forms import UserCreationForm

from library.models import User


class SignupForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",)


class DeviceForm(forms.Form):
    name = forms.CharField(
        max_length=100,
        label="Device name",
        widget=forms.TextInput(
            attrs={"placeholder": "Lounge X4", "autocomplete": "off"}
        ),
    )

    def clean_name(self):
        return self.cleaned_data["name"].strip()
