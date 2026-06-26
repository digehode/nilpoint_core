from django import forms
import re


# TODO: need to downcast PlayerCharacter?
from nilpoint.models import PlayerCharacter


def is_valid_handle(input_string):
    # \w matches any alphanumeric character (letters, numbers) and underscores.
    # ^ ensures the match starts at the beginning of the string.
    # $ ensures the match goes until the end of the string.
    # + ensures the string has at least one character.
    # If you want to allow empty strings as well, change the + to *
    return bool(re.match(r"^\w+$", input_string))


class NewPlayerCharacterForm(forms.Form):
    handle = forms.CharField(
        label="Handle",
        help_text="Your Player Character will be referred to by their handle in this game. The handle can be made of numbers, letters and the underscore character.",
        max_length=100,
    )

    def clean_handle(self):
        # Grab the data Django has already sanitized
        handle = self.cleaned_data.get("handle").strip()

        if PlayerCharacter.objects.filter(handle__iexact=handle).exists():
            if hasattr(self, "game"):
                game = getattr(self, "game")
                if PlayerCharacter.objects.filter(
                    handle__iexact=handle, game=game
                ).exists():
                    raise forms.ValidationError(
                        "That handle is already being used in this game."
                    )
            else:
                raise forms.ValidationError("That handle is already being used.")
        if not is_valid_handle(handle):
            raise forms.ValidationError(
                "You can only use A-Z, a-z, 0-9 and _ in handles."
            )

        return handle
