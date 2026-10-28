"""Validate the complete academic calendar before joining activity."""

from collections import Counter

from shared.data_loading import csv_stream, rows
from shared.errors import InputError
from shared.time_utils import parse_date

def load_calendar(path, selected_year):
    calendar = {}
    with csv_stream([path]) as stream:
        for line, row in rows(stream, ("DATE", "WEEK_NUMBER", "ACADEMIC_YEAR"), path):
            try:
                day = parse_date(row["DATE"])
                week = int(row["WEEK_NUMBER"])
                year = row["ACADEMIC_YEAR"]
                if not year or not 1 <= week <= 52:
                    raise ValueError("expected academic year and week 1–52")
                if day in calendar:
                    raise ValueError("duplicate DATE would make the calendar join ambiguous")
                calendar[day] = (year, week)
            except ValueError as exc:
                raise InputError(f"{path}, line {line}: {exc}") from exc
    years = {year for year, _ in calendar.values()}
    if selected_year is None:
        if len(years) != 1:
            raise InputError("calendar has zero/multiple academic years; set --academic-year")
        selected_year = next(iter(years))
    selected = {day: week for day, (year, week) in calendar.items() if year == selected_year}
    if set(selected.values()) != set(range(1, 53)):
        raise InputError("selected calendar must contain all 52 academic weeks, including 1–4")
    days = sorted(selected)
    if len(days) != (days[-1] - days[0]).days + 1:
        raise InputError("selected calendar has missing dates")
    week_days = Counter(selected.values())
    if any(week_days[w] != 7 for w in range(1, 52)) or week_days[52] < 7:
        raise InputError("calendar must contain seven days per week (week 52 may include extra year-end days)")
    if any(selected[b] < selected[a] or selected[b] > selected[a] + 1
           for a, b in zip(days, days[1:])):
        raise InputError("academic weeks must progress in date order")
    return calendar, selected_year
