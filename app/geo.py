import math
import re


def validate_coordinates(lat: float, lng: float) -> bool:
    """Return True if lat/lng are within valid WGS-84 ranges."""
    return -90 <= lat <= 90 and -180 <= lng <= 180


def calculate_distance_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance between two coordinates using the Haversine formula.

    Returns 0.0 if any coordinate is outside the valid WGS-84 range.
    """
    if not (validate_coordinates(lat1, lng1) and validate_coordinates(lat2, lng2)):
        return 0.0

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
