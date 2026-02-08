"""Tests for SmartPlaylistService - rule validation, date resolution, and query building."""

from datetime import datetime, timedelta

import pytest

from app.services.smart_playlists import (
    SmartPlaylistService,
    resolve_date_value,
    resolve_relative_date,
)


class TestResolveRelativeDate:
    """Tests for resolve_relative_date helper."""

    def test_days(self):
        result = resolve_relative_date({"amount": 7, "unit": "days"})
        assert result is not None
        assert (datetime.utcnow() - result).total_seconds() < 7 * 86400 + 5

    def test_weeks(self):
        result = resolve_relative_date({"amount": 2, "unit": "weeks"})
        assert result is not None
        assert (datetime.utcnow() - result).total_seconds() < 14 * 86400 + 5

    def test_months(self):
        result = resolve_relative_date({"amount": 1, "unit": "months"})
        assert result is not None
        assert (datetime.utcnow() - result).total_seconds() < 31 * 86400 + 5

    def test_years(self):
        result = resolve_relative_date({"amount": 1, "unit": "years"})
        assert result is not None
        assert (datetime.utcnow() - result).total_seconds() < 366 * 86400 + 5

    def test_invalid_type(self):
        assert resolve_relative_date("not a dict") is None

    def test_invalid_amount(self):
        assert resolve_relative_date({"amount": "abc", "unit": "days"}) is None

    def test_invalid_unit(self):
        assert resolve_relative_date({"amount": 1, "unit": "centuries"}) is None


class TestResolveDateValue:
    """Tests for resolve_date_value helper."""

    def test_keyword_today(self):
        result = resolve_date_value("today")
        assert result is not None
        assert result.hour == 0
        assert result.minute == 0
        assert result.date() == datetime.utcnow().date()

    def test_keyword_yesterday(self):
        result = resolve_date_value("yesterday")
        assert result is not None
        yesterday = datetime.utcnow().date() - timedelta(days=1)
        assert result.date() == yesterday

    def test_keyword_this_year(self):
        result = resolve_date_value("this_year")
        assert result is not None
        assert result.month == 1
        assert result.day == 1
        assert result.year == datetime.utcnow().year

    def test_iso_string(self):
        result = resolve_date_value("2024-06-15T00:00:00Z")
        assert result is not None
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15

    def test_invalid_string(self):
        assert resolve_date_value("not-a-date") is None

    def test_non_string(self):
        assert resolve_date_value(12345) is None


class TestValidateRules:
    """Tests for SmartPlaylistService._validate_rules."""

    @pytest.fixture
    def service(self):
        from unittest.mock import AsyncMock
        return SmartPlaylistService(db=AsyncMock())

    def test_valid_genre_rule(self, service):
        rules = [{"field": "genre", "operator": "contains", "value": "rock"}]
        service._validate_rules(rules)  # Should not raise

    def test_valid_year_rule(self, service):
        rules = [{"field": "year", "operator": "between", "value": [2000, 2024]}]
        service._validate_rules(rules)

    def test_valid_analysis_rule(self, service):
        rules = [{"field": "energy", "operator": "greater_or_equal", "value": 0.7}]
        service._validate_rules(rules)

    def test_valid_play_history_rule(self, service):
        rules = [{"field": "play_count", "operator": "greater_or_equal", "value": 5}]
        service._validate_rules(rules)

    def test_valid_never_played_rule(self, service):
        rules = [{"field": "never_played", "operator": "equals", "value": True}]
        service._validate_rules(rules)

    def test_valid_date_rule(self, service):
        rules = [{"field": "created_at", "operator": "after", "value": "this_year"}]
        service._validate_rules(rules)

    def test_valid_relative_date_rule(self, service):
        rules = [{"field": "last_played_at", "operator": "in_the_last", "value": {"amount": 7, "unit": "days"}}]
        service._validate_rules(rules)

    def test_is_empty_no_value_required(self, service):
        rules = [{"field": "genre", "operator": "is_empty"}]
        service._validate_rules(rules)  # Should not raise

    def test_missing_field_raises(self, service):
        with pytest.raises(ValueError, match="missing 'field'"):
            service._validate_rules([{"operator": "contains", "value": "rock"}])

    def test_missing_operator_raises(self, service):
        with pytest.raises(ValueError, match="missing 'operator'"):
            service._validate_rules([{"field": "genre", "value": "rock"}])

    def test_unknown_field_raises(self, service):
        with pytest.raises(ValueError, match="Unknown field"):
            service._validate_rules([{"field": "nonexistent", "operator": "equals", "value": "x"}])

    def test_unknown_operator_raises(self, service):
        with pytest.raises(ValueError, match="Unknown operator"):
            service._validate_rules([{"field": "genre", "operator": "invalid_op", "value": "x"}])

    def test_date_field_with_non_date_operator_raises(self, service):
        with pytest.raises(ValueError, match="only supports date operators"):
            service._validate_rules([{"field": "created_at", "operator": "contains", "value": "x"}])

    def test_boolean_field_non_equals_raises(self, service):
        with pytest.raises(ValueError, match="only supports 'equals'"):
            service._validate_rules([{"field": "never_played", "operator": "contains", "value": True}])

    def test_string_operator_on_numeric_field_raises(self, service):
        with pytest.raises(ValueError, match="Cannot use string operator"):
            service._validate_rules([{"field": "year", "operator": "contains", "value": "2024"}])

    def test_missing_value_raises(self, service):
        with pytest.raises(ValueError, match="requires 'value'"):
            service._validate_rules([{"field": "genre", "operator": "equals"}])

    def test_multiple_rules_validated(self, service):
        rules = [
            {"field": "genre", "operator": "contains", "value": "rock"},
            {"field": "year", "operator": "greater_or_equal", "value": 2000},
            {"field": "energy", "operator": "between", "value": [0.5, 1.0]},
        ]
        service._validate_rules(rules)  # Should not raise
