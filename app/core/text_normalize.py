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


_ACENTOS = "áéíóúüñÁÉÍÓÚÜÑ"
_SIN_ACENTOS = "aeiouunAEIOUUN"


def fold_sql(column):
    """
    Expresión SQL equivalente a `normalize_name` para comparar columnas de texto
    sin distinguir mayúsculas ni tildes («José» == «JOSE» == «jose»).

    Usa `translate` + `lower` en vez de la extensión `unaccent`, que no está
    instalada en todas las bases.
    """
    from sqlalchemy import func

    return func.lower(func.translate(column, _ACENTOS, _SIN_ACENTOS))
