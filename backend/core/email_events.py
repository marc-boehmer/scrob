from datetime import date

from core.email_translations import normalize_email_language


_MONTHS = {
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
    "de": ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"),
    "fr": ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"),
    "pt-PT": ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"),
}


def release_event(day: date, language: str | None) -> str:
    locale = normalize_email_language(language)
    month = _MONTHS[locale][day.month - 1]
    return {
        "en": f"Theatrical release date reached: {month} {day.day}, {day.year}",
        "de": f"Kinostart erreicht: {day.day}. {month} {day.year}",
        "fr": f"Date de sortie en salle atteinte : {day.day} {month} {day.year}",
        "pt-PT": f"Data de estreia nos cinemas atingida: {day.day} de {month} de {day.year}",
    }[locale]


def streaming_event(providers: list[str], language: str | None) -> str:
    names = ", ".join(providers)
    return {
        "en": f"Now available to stream on {names}",
        "de": f"Jetzt zum Streamen verfügbar bei {names}",
        "fr": f"Disponible en streaming sur {names}",
        "pt-PT": f"Disponível em streaming em {names}",
    }[normalize_email_language(language)]


def season_title(title: str, season: int, language: str | None) -> str:
    label = {"en": "season", "de": "Staffel", "fr": "saison", "pt-PT": "temporada"}
    return f"{title} ({label[normalize_email_language(language)]} {season})"
