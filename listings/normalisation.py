import unicodedata


def normalise_title(text: str) -> str:
    """Return the conservative normalized title used for exact alias lookup."""
    normalised = unicodedata.normalize("NFKC", text).casefold()
    characters = []
    at_boundary = True

    for character in normalised:
        if character.isalnum():
            characters.append(character)
            at_boundary = False
        elif not at_boundary:
            # Every non-alphanumeric character separates rather than merges tokens.
            characters.append(" ")
            at_boundary = True

    if characters and characters[-1] == " ":
        characters.pop()

    return "".join(characters)
