"""Unit tests for the geo module."""

from app.geo import calculate_distance_miles, extract_postcode_area, validate_coordinates


class TestValidateCoordinates:
    def test_valid(self):
        assert validate_coordinates(51.5, -0.1) is True

    def test_boundary_values(self):
        assert validate_coordinates(90, 180) is True
        assert validate_coordinates(-90, -180) is True

    def test_out_of_range_lat(self):
        assert validate_coordinates(91, 0) is False
        assert validate_coordinates(-91, 0) is False

    def test_out_of_range_lng(self):
        assert validate_coordinates(0, 181) is False
        assert validate_coordinates(0, -181) is False


class TestCalculateDistanceMiles:
    def test_same_point(self):
        assert calculate_distance_miles(51.5, -0.1, 51.5, -0.1) == 0.0

    def test_london_to_manchester(self):
        dist = calculate_distance_miles(51.5074, -0.1278, 53.4808, -2.2426)
        assert 160 < dist < 170  # ~163 miles

    def test_invalid_coordinates_return_zero(self):
        assert calculate_distance_miles(999, 0, 51.5, -0.1) == 0.0


class TestExtractPostcodeArea:
    def test_full_postcode(self):
        assert extract_postcode_area("SW1A 2AA") == "SW1A"

    def test_short_postcode(self):
        assert extract_postcode_area("M1 1AA") == "M1"

    def test_empty_string(self):
        assert extract_postcode_area("") == ""

    def test_none(self):
        assert extract_postcode_area(None) == ""
