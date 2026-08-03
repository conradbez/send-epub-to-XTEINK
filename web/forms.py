from django import forms


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
