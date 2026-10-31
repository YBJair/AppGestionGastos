import unicodedata


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    characters = []
    for character in normalized:
        if unicodedata.category(character).startswith("M"):
            continue
        characters.append(character if character.isalnum() else " ")
    return " ".join("".join(characters).split())
