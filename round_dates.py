"""Wspólne, niezależne od projektu obliczenia zakresu dat kolejki."""


def round_date_range(dates, all_dates_confirmed=True):
    """Zwraca zakres dat, jeśli wszystkie daty kolejki są potwierdzone."""
    if not all_dates_confirmed:
        return None, None
    confirmed_dates = [day for day in dates if day is not None]
    if not confirmed_dates:
        return None, None
    return min(confirmed_dates), max(confirmed_dates)
