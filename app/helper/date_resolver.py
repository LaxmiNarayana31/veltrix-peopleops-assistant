"""Date resolution utility resolving relative date expressions for the leave year."""

import logging
import re
from datetime import date, timedelta
from typing import Optional, Tuple

from app.exceptions.custom_exceptions import AppException
from app.utils.constants import LEAVE_YEAR, MONTH_MAP
from config.app_config import REFERENCE_DATE

logger = logging.getLogger(__name__)

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class DateResolver:
    """Resolves relative date expressions ('next Friday', 'next week') into calendar dates for 2026."""

    @classmethod
    def resolve_date_phrase(cls, phrase: str, today: Optional[date] = None) -> Optional[date]:
        """Convert a date phrase or string into a concrete date object."""
        try:
            if not phrase:
                return None

            ref_today = today or REFERENCE_DATE
            p = phrase.strip().lower()

            # Exact ISO format: YYYY-MM-DD
            iso_match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", p)
            if iso_match:
                return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))

            # Relative: "today"
            if p == "today":
                return ref_today

            # Relative: "tomorrow"
            if p == "tomorrow":
                return ref_today + timedelta(days=1)

            # Relative: "next friday", "next monday", etc.
            for day_name, day_idx in WEEKDAYS.items():
                if f"next {day_name}" in p or (p.startswith(day_name) and "next" not in p):
                    days_ahead = (day_idx - ref_today.weekday()) % 7
                    if days_ahead == 0:
                        days_ahead = 7
                    return ref_today + timedelta(days=days_ahead)

            # Explicit month and day: "15th June", "June 15", "15 June 2026"
            month_regex = re.compile(
                r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)(?:\s+(\d{4}))?|([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?"
            )
            m = month_regex.search(p)
            if m:
                if m.group(1) and m.group(2):
                    day_val = int(m.group(1))
                    month_val = MONTH_MAP.get(m.group(2).lower())
                    year_val = int(m.group(3)) if m.group(3) else LEAVE_YEAR
                else:
                    month_val = MONTH_MAP.get(m.group(4).lower())
                    day_val = int(m.group(5))
                    year_val = int(m.group(6)) if m.group(6) else LEAVE_YEAR

                if month_val and 1 <= day_val <= 31:
                    return date(year_val, month_val, day_val)

            return None
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed resolving date phrase '%s'", phrase)
            return None

    @classmethod
    def resolve_date_range(
        cls,
        start_phrase: Optional[str],
        end_phrase: Optional[str],
        today: Optional[date] = None,
    ) -> Tuple[Optional[date], Optional[date]]:
        """Resolve start and end date phrases. Handles 'next week' spanning Monday to Friday."""
        try:
            ref_today = today or REFERENCE_DATE

            # Special case: "next week" = Mon to Fri of the following week
            if start_phrase and "next week" in start_phrase.lower():
                days_until_next_monday = (0 - ref_today.weekday()) % 7
                if days_until_next_monday == 0:
                    days_until_next_monday = 7
                next_monday = ref_today + timedelta(days=days_until_next_monday)
                next_friday = next_monday + timedelta(days=4)
                return next_monday, next_friday

            start_d = cls.resolve_date_phrase(start_phrase, ref_today) if start_phrase else None
            end_d = cls.resolve_date_phrase(end_phrase, ref_today) if end_phrase else None

            # If only start date is provided for a single day request, end_date defaults to start_date
            if start_d and not end_d and end_phrase is None:
                end_d = start_d

            return start_d, end_d
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed resolving date range '%s' - '%s'", start_phrase, end_phrase)
            return None, None


def get_date_resolver() -> DateResolver:
    """Return DateResolver instance for backward compatibility."""
    return DateResolver()
