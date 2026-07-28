import unicodedata


def normalize_name(value: str | None) -> str:
    """
    Normaliza un nombre/apellido para comparación tolerante:
    minúsculas, sin tildes/diacríticos, espacios colapsados.
    """
    if not value:
        return ""

    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = " ".join(text.lower().split())
    return text
