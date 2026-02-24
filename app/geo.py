import math
import re


def calculate_distance_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance between two coordinates using the Haversine formula."""
    R = 3959  # Earth radius in miles
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def extract_postcode_area(postcode: str) -> str:
    """Extract the outward code from a UK postcode for redacted display.
    'SW1A 2AA' -> 'SW1A', 'M1 1AA' -> 'M1'
    """
    if not postcode:
        return ""
    parts = postcode.strip().split()
    return parts[0] if parts else ""


def extract_city_from_label(label: str) -> str:
    """Extract city name from a Mapbox geocoder label.
    Typically formatted as '123 Street, City, County, Postcode, Country'
    """
    if not label:
        return ""
    parts = [p.strip() for p in label.split(",")]
    if len(parts) >= 3:
        return parts[-3]
    elif len(parts) >= 2:
        return parts[-2]
    return parts[0]
