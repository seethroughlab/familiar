"""Tests for SmartPlaylistService - rule validation, date resolution, and query building."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.services.smart_playlists import (
    EXTERNAL_COMPATIBLE_FIELDS,
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


class TestCanIncludeExternal:
    """Tests for SmartPlaylistService._can_include_external."""

    @pytest.fixture
    def service(self):
        return SmartPlaylistService(db=AsyncMock())

    # --- Compatible cases (should return True) ---

    def test_all_compatible_fields_returns_true(self, service):
        """Rules using only EXTERNAL_COMPATIBLE_FIELDS should allow external tracks."""
        rules = [
            {"field": "artist", "operator": "contains", "value": "Beatles"},
            {"field": "year", "operator": "greater_or_equal", "value": 2000},
        ]
        assert service._can_include_external(rules, "title") is True

    def test_single_title_rule(self, service):
        rules = [{"field": "title", "operator": "contains", "value": "love"}]
        assert service._can_include_external(rules, "artist") is True

    def test_single_album_rule(self, service):
        rules = [{"field": "album", "operator": "equals", "value": "Abbey Road"}]
        assert service._can_include_external(rules, "album") is True

    def test_duration_rule(self, service):
        rules = [{"field": "duration_seconds", "operator": "greater_than", "value": 120}]
        assert service._can_include_external(rules, "duration_seconds") is True

    def test_track_number_rule(self, service):
        rules = [{"field": "track_number", "operator": "equals", "value": 1}]
        assert service._can_include_external(rules, "title") is True

    def test_year_rule(self, service):
        rules = [{"field": "year", "operator": "between", "value": [1990, 2000]}]
        assert service._can_include_external(rules, "year") is True

    def test_empty_rules(self, service):
        """No rules means all tracks match - external should be included."""
        assert service._can_include_external([], "title") is True

    def test_all_external_compatible_fields_covered(self, service):
        """Build a rule for each compatible field and verify they all work."""
        rules = [{"field": f, "operator": "equals", "value": "x"} for f in EXTERNAL_COMPATIBLE_FIELDS]
        for f in EXTERNAL_COMPATIBLE_FIELDS:
            assert service._can_include_external(rules, f) is True

    # --- Incompatible cases (should return False) ---

    def test_genre_rule_incompatible(self, service):
        """Genre doesn't exist on ExternalTrack."""
        rules = [{"field": "genre", "operator": "contains", "value": "rock"}]
        assert service._can_include_external(rules, "title") is False

    def test_format_rule_incompatible(self, service):
        rules = [{"field": "format", "operator": "equals", "value": "flac"}]
        assert service._can_include_external(rules, "title") is False

    def test_analysis_field_incompatible(self, service):
        """Analysis fields (energy, bpm, etc.) are not on ExternalTrack."""
        rules = [{"field": "energy", "operator": "greater_or_equal", "value": 0.7}]
        assert service._can_include_external(rules, "title") is False

    def test_play_history_field_incompatible(self, service):
        rules = [{"field": "play_count", "operator": "greater_or_equal", "value": 5}]
        assert service._can_include_external(rules, "title") is False

    def test_never_played_incompatible(self, service):
        rules = [{"field": "never_played", "operator": "equals", "value": True}]
        assert service._can_include_external(rules, "title") is False

    def test_created_at_incompatible(self, service):
        rules = [{"field": "created_at", "operator": "after", "value": "this_year"}]
        assert service._can_include_external(rules, "title") is False

    def test_album_artist_incompatible(self, service):
        rules = [{"field": "album_artist", "operator": "contains", "value": "Beatles"}]
        assert service._can_include_external(rules, "title") is False

    def test_file_path_incompatible(self, service):
        rules = [{"field": "file_path", "operator": "contains", "value": "/music/"}]
        assert service._can_include_external(rules, "title") is False

    def test_incompatible_order_by(self, service):
        """Even if rules are compatible, incompatible order_by returns False."""
        rules = [{"field": "title", "operator": "contains", "value": "love"}]
        assert service._can_include_external(rules, "genre") is False

    def test_incompatible_order_by_analysis(self, service):
        rules = [{"field": "artist", "operator": "contains", "value": "x"}]
        assert service._can_include_external(rules, "energy") is False

    def test_incompatible_order_by_play_count(self, service):
        rules = [{"field": "title", "operator": "contains", "value": "x"}]
        assert service._can_include_external(rules, "play_count") is False

    def test_mixed_compatible_and_incompatible(self, service):
        """One incompatible rule makes the whole playlist incompatible."""
        rules = [
            {"field": "artist", "operator": "contains", "value": "Beatles"},
            {"field": "genre", "operator": "contains", "value": "rock"},
        ]
        assert service._can_include_external(rules, "title") is False


class TestBuildExternalCondition:
    """Tests for SmartPlaylistService._build_external_condition.

    These test that conditions are generated (non-None) for valid operator/field
    combos, and that SQL is produced. We compile to string to verify the clause
    structure without needing a database.
    """

    @pytest.fixture
    def service(self):
        return SmartPlaylistService(db=AsyncMock())

    def _compile(self, clause):
        """Compile a SQLAlchemy clause to a string for assertions."""
        from sqlalchemy.dialects import postgresql
        return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    # --- Equality operators ---

    def test_equals(self, service):
        rule = {"field": "artist", "operator": "equals", "value": "Beatles"}
        cond = service._build_external_condition(rule)
        assert cond is not None
        sql = self._compile(cond)
        assert "external_tracks.artist" in sql
        assert "Beatles" in sql

    def test_not_equals(self, service):
        rule = {"field": "title", "operator": "not_equals", "value": "Help"}
        cond = service._build_external_condition(rule)
        assert cond is not None
        sql = self._compile(cond)
        assert "external_tracks.title" in sql
        assert "!=" in sql

    # --- String operators ---

    def test_contains(self, service):
        rule = {"field": "artist", "operator": "contains", "value": "beat"}
        cond = service._build_external_condition(rule)
        assert cond is not None
        sql = self._compile(cond)
        assert "ILIKE" in sql
        assert "%beat%" in sql

    def test_not_contains(self, service):
        rule = {"field": "album", "operator": "not_contains", "value": "live"}
        cond = service._build_external_condition(rule)
        assert cond is not None
        sql = self._compile(cond)
        assert "ILIKE" in sql or "ilike" in sql.lower()
        assert "%live%" in sql

    def test_starts_with(self, service):
        rule = {"field": "title", "operator": "starts_with", "value": "The"}
        cond = service._build_external_condition(rule)
        assert cond is not None
        sql = self._compile(cond)
        assert "ILIKE" in sql
        # PostgreSQL dialect escapes % as %% in compiled output
        assert "The%" in sql

    def test_ends_with(self, service):
        rule = {"field": "title", "operator": "ends_with", "value": "Mix"}
        cond = service._build_external_condition(rule)
        assert cond is not None
        sql = self._compile(cond)
        assert "ILIKE" in sql
        assert "%Mix" in sql

    # --- Comparison operators ---

    def test_greater_than(self, service):
        rule = {"field": "year", "operator": "greater_than", "value": 2000}
        cond = service._build_external_condition(rule)
        assert cond is not None
        sql = self._compile(cond)
        assert "external_tracks.year" in sql
        assert "> " in sql

    def test_less_than(self, service):
        rule = {"field": "year", "operator": "less_than", "value": 1980}
        cond = service._build_external_condition(rule)
        assert cond is not None
        sql = self._compile(cond)
        assert "< " in sql

    def test_greater_or_equal(self, service):
        rule = {"field": "duration_seconds", "operator": "greater_or_equal", "value": 180.0}
        cond = service._build_external_condition(rule)
        assert cond is not None
        sql = self._compile(cond)
        assert ">=" in sql

    def test_less_or_equal(self, service):
        rule = {"field": "track_number", "operator": "less_or_equal", "value": 5}
        cond = service._build_external_condition(rule)
        assert cond is not None
        sql = self._compile(cond)
        assert "<=" in sql

    # --- Range and set operators ---

    def test_between(self, service):
        rule = {"field": "year", "operator": "between", "value": [1990, 2000]}
        cond = service._build_external_condition(rule)
        assert cond is not None
        sql = self._compile(cond)
        assert "1990" in sql
        assert "2000" in sql

    def test_between_invalid_value_returns_none(self, service):
        rule = {"field": "year", "operator": "between", "value": "not a list"}
        assert service._build_external_condition(rule) is None

    def test_between_wrong_length_returns_none(self, service):
        rule = {"field": "year", "operator": "between", "value": [1990]}
        assert service._build_external_condition(rule) is None

    def test_in(self, service):
        rule = {"field": "artist", "operator": "in", "value": ["Beatles", "Stones"]}
        cond = service._build_external_condition(rule)
        assert cond is not None
        sql = self._compile(cond)
        assert "IN" in sql

    def test_in_invalid_value_returns_none(self, service):
        rule = {"field": "artist", "operator": "in", "value": "not a list"}
        assert service._build_external_condition(rule) is None

    def test_not_in(self, service):
        rule = {"field": "artist", "operator": "not_in", "value": ["Beatles", "Stones"]}
        cond = service._build_external_condition(rule)
        assert cond is not None
        sql = self._compile(cond)
        # NOT IN or NOT (... IN ...) depending on dialect
        assert "IN" in sql

    def test_not_in_invalid_value_returns_none(self, service):
        rule = {"field": "artist", "operator": "not_in", "value": "not a list"}
        assert service._build_external_condition(rule) is None

    # --- Empty/not empty ---

    def test_is_empty(self, service):
        rule = {"field": "album", "operator": "is_empty"}
        cond = service._build_external_condition(rule)
        assert cond is not None
        sql = self._compile(cond)
        assert "IS NULL" in sql or "NULL" in sql

    def test_is_not_empty(self, service):
        rule = {"field": "album", "operator": "is_not_empty"}
        cond = service._build_external_condition(rule)
        assert cond is not None
        sql = self._compile(cond)
        assert "IS NOT NULL" in sql or "NOT NULL" in sql

    # --- Unknown operator returns None ---

    def test_unknown_operator_returns_none(self, service):
        rule = {"field": "artist", "operator": "within_days", "value": 7}
        # within_days is a date operator, not handled by _build_external_condition
        cond = service._build_external_condition(rule)
        assert cond is None


class TestBuildCondition:
    """Tests for SmartPlaylistService._build_condition.

    Tests the main _build_condition method which operates on Track/TrackAnalysis
    columns. Uses compiled SQL strings to verify clause structure.
    """

    @pytest.fixture
    def service(self):
        return SmartPlaylistService(db=AsyncMock())

    def _compile(self, clause):
        from sqlalchemy.dialects import postgresql
        return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    # --- never_played special field ---

    def test_never_played_true(self, service):
        rule = {"field": "never_played", "operator": "equals", "value": True}
        cond = service._build_condition(rule, has_analysis_join=False, has_play_history_join=True)
        assert cond is not None
        sql = self._compile(cond)
        assert "IS NULL" in sql

    def test_never_played_false(self, service):
        rule = {"field": "never_played", "operator": "equals", "value": False}
        cond = service._build_condition(rule, has_analysis_join=False, has_play_history_join=True)
        assert cond is not None
        sql = self._compile(cond)
        assert "IS NOT NULL" in sql

    # --- Track field operators ---

    def test_equals_track_field(self, service):
        rule = {"field": "artist", "operator": "equals", "value": "Beatles"}
        cond = service._build_condition(rule, False)
        assert cond is not None
        sql = self._compile(cond)
        assert "tracks.artist" in sql

    def test_not_equals(self, service):
        rule = {"field": "genre", "operator": "not_equals", "value": "Pop"}
        cond = service._build_condition(rule, False)
        assert cond is not None
        sql = self._compile(cond)
        assert "!=" in sql

    def test_contains(self, service):
        rule = {"field": "title", "operator": "contains", "value": "love"}
        cond = service._build_condition(rule, False)
        assert cond is not None
        sql = self._compile(cond)
        assert "ILIKE" in sql

    def test_not_contains(self, service):
        rule = {"field": "artist", "operator": "not_contains", "value": "feat"}
        cond = service._build_condition(rule, False)
        assert cond is not None
        sql = self._compile(cond)
        assert "ILIKE" in sql

    def test_starts_with(self, service):
        rule = {"field": "title", "operator": "starts_with", "value": "The"}
        cond = service._build_condition(rule, False)
        assert cond is not None

    def test_ends_with(self, service):
        rule = {"field": "album", "operator": "ends_with", "value": "Edition"}
        cond = service._build_condition(rule, False)
        assert cond is not None

    def test_greater_than(self, service):
        rule = {"field": "year", "operator": "greater_than", "value": 2000}
        cond = service._build_condition(rule, False)
        assert cond is not None

    def test_less_than(self, service):
        rule = {"field": "year", "operator": "less_than", "value": 1980}
        cond = service._build_condition(rule, False)
        assert cond is not None

    def test_greater_or_equal(self, service):
        rule = {"field": "duration_seconds", "operator": "greater_or_equal", "value": 180}
        cond = service._build_condition(rule, False)
        assert cond is not None

    def test_less_or_equal(self, service):
        rule = {"field": "track_number", "operator": "less_or_equal", "value": 5}
        cond = service._build_condition(rule, False)
        assert cond is not None

    def test_between(self, service):
        rule = {"field": "year", "operator": "between", "value": [1990, 2000]}
        cond = service._build_condition(rule, False)
        assert cond is not None
        sql = self._compile(cond)
        assert "1990" in sql
        assert "2000" in sql

    def test_between_invalid_returns_none(self, service):
        rule = {"field": "year", "operator": "between", "value": "not a list"}
        assert service._build_condition(rule, False) is None

    def test_in_operator(self, service):
        rule = {"field": "genre", "operator": "in", "value": ["Rock", "Pop", "Jazz"]}
        cond = service._build_condition(rule, False)
        assert cond is not None
        sql = self._compile(cond)
        assert "IN" in sql

    def test_in_invalid_returns_none(self, service):
        rule = {"field": "genre", "operator": "in", "value": "not a list"}
        assert service._build_condition(rule, False) is None

    def test_not_in_operator(self, service):
        rule = {"field": "genre", "operator": "not_in", "value": ["Classical"]}
        cond = service._build_condition(rule, False)
        assert cond is not None

    def test_not_in_invalid_returns_none(self, service):
        rule = {"field": "genre", "operator": "not_in", "value": "not a list"}
        assert service._build_condition(rule, False) is None

    def test_is_empty(self, service):
        rule = {"field": "genre", "operator": "is_empty"}
        cond = service._build_condition(rule, False)
        assert cond is not None
        sql = self._compile(cond)
        assert "IS NULL" in sql

    def test_is_not_empty(self, service):
        rule = {"field": "genre", "operator": "is_not_empty"}
        cond = service._build_condition(rule, False)
        assert cond is not None
        sql = self._compile(cond)
        assert "IS NOT NULL" in sql

    def test_is_empty_last_played_at_blocked_by_string_guard(self, service):
        """is_empty on last_played_at is blocked by the string operator guard.

        The code checks string_operators before date_operators, and is_empty
        is in both sets. Since last_played_at is not a string field, the
        string operator guard returns None.
        """
        rule = {"field": "last_played_at", "operator": "is_empty"}
        cond = service._build_condition(rule, has_analysis_join=False, has_play_history_join=True)
        # Returns None because string_operators guard fires before date handling
        assert cond is None

    def test_is_not_empty_last_played_at_blocked_by_string_guard(self, service):
        """Same issue: is_not_empty is in string_operators, blocked on non-string fields."""
        rule = {"field": "last_played_at", "operator": "is_not_empty"}
        cond = service._build_condition(rule, has_analysis_join=False, has_play_history_join=True)
        assert cond is None

    # --- Date operators ---

    def test_within_days(self, service):
        rule = {"field": "created_at", "operator": "within_days", "value": 30}
        cond = service._build_condition(rule, False)
        assert cond is not None

    def test_within_days_string_value(self, service):
        """Value can come as string from JSON."""
        rule = {"field": "created_at", "operator": "within_days", "value": "14"}
        cond = service._build_condition(rule, False)
        assert cond is not None

    def test_within_days_invalid_value(self, service):
        rule = {"field": "created_at", "operator": "within_days", "value": "abc"}
        assert service._build_condition(rule, False) is None

    def test_within_days_none_value(self, service):
        rule = {"field": "created_at", "operator": "within_days", "value": None}
        assert service._build_condition(rule, False) is None

    def test_not_within_days(self, service):
        rule = {"field": "created_at", "operator": "not_within_days", "value": 90}
        cond = service._build_condition(rule, False)
        assert cond is not None

    def test_not_within_days_invalid(self, service):
        rule = {"field": "created_at", "operator": "not_within_days", "value": "invalid"}
        assert service._build_condition(rule, False) is None

    def test_after_keyword(self, service):
        rule = {"field": "created_at", "operator": "after", "value": "this_year"}
        cond = service._build_condition(rule, False)
        assert cond is not None

    def test_after_invalid(self, service):
        rule = {"field": "created_at", "operator": "after", "value": "not-a-date"}
        assert service._build_condition(rule, False) is None

    def test_before_keyword(self, service):
        rule = {"field": "created_at", "operator": "before", "value": "today"}
        cond = service._build_condition(rule, False)
        assert cond is not None

    def test_before_invalid(self, service):
        rule = {"field": "created_at", "operator": "before", "value": "not-valid"}
        assert service._build_condition(rule, False) is None

    def test_on_keyword(self, service):
        rule = {"field": "created_at", "operator": "on", "value": "today"}
        cond = service._build_condition(rule, False)
        assert cond is not None

    def test_on_invalid(self, service):
        rule = {"field": "created_at", "operator": "on", "value": "bad-date"}
        assert service._build_condition(rule, False) is None

    def test_in_the_last(self, service):
        rule = {"field": "created_at", "operator": "in_the_last", "value": {"amount": 3, "unit": "weeks"}}
        cond = service._build_condition(rule, False)
        assert cond is not None

    def test_in_the_last_invalid(self, service):
        rule = {"field": "created_at", "operator": "in_the_last", "value": "bad"}
        assert service._build_condition(rule, False) is None

    def test_not_in_the_last(self, service):
        rule = {"field": "created_at", "operator": "not_in_the_last", "value": {"amount": 6, "unit": "months"}}
        cond = service._build_condition(rule, False)
        assert cond is not None

    def test_not_in_the_last_invalid(self, service):
        rule = {"field": "created_at", "operator": "not_in_the_last", "value": 12345}
        assert service._build_condition(rule, False) is None

    # --- Field type guards ---

    def test_string_operator_on_date_field_returns_none(self, service):
        """Date fields should not accept non-date operators."""
        rule = {"field": "created_at", "operator": "equals", "value": "something"}
        assert service._build_condition(rule, False) is None

    def test_string_operator_on_numeric_returns_none(self, service):
        """String operators like contains should not work on numeric fields."""
        rule = {"field": "year", "operator": "contains", "value": "20"}
        assert service._build_condition(rule, False) is None

    def test_unknown_field_returns_none(self, service):
        """Fields not in any known set should return None."""
        rule = {"field": "nonexistent_field", "operator": "equals", "value": "x"}
        assert service._build_condition(rule, False) is None

    def test_analysis_field_without_join_returns_none(self, service):
        """Analysis fields without has_analysis_join=True should return None."""
        rule = {"field": "energy", "operator": "greater_than", "value": 0.5}
        assert service._build_condition(rule, has_analysis_join=False) is None

    def test_play_history_field_without_join_returns_none(self, service):
        """Play history fields without join should return None."""
        rule = {"field": "play_count", "operator": "greater_than", "value": 5}
        assert service._build_condition(rule, False, has_play_history_join=False) is None

    def test_unknown_operator_returns_none(self, service):
        """An operator not in the if/elif chain should return None."""
        rule = {"field": "title", "operator": "regex", "value": ".*"}
        assert service._build_condition(rule, False) is None

    # --- Play history fields with join ---

    def test_play_count_with_coalesce(self, service):
        """play_count should use coalesce to treat NULL as 0."""
        rule = {"field": "play_count", "operator": "greater_or_equal", "value": 5}
        cond = service._build_condition(rule, False, has_play_history_join=True)
        assert cond is not None
        sql = self._compile(cond)
        assert "coalesce" in sql.lower()

    def test_total_play_seconds_with_coalesce(self, service):
        rule = {"field": "total_play_seconds", "operator": "greater_than", "value": 600}
        cond = service._build_condition(rule, False, has_play_history_join=True)
        assert cond is not None
        sql = self._compile(cond)
        assert "coalesce" in sql.lower()

    def test_last_played_at_without_coalesce(self, service):
        """last_played_at should NOT use coalesce (it's a datetime, not numeric)."""
        rule = {"field": "last_played_at", "operator": "within_days", "value": 30}
        cond = service._build_condition(rule, False, has_play_history_join=True)
        assert cond is not None
        sql = self._compile(cond)
        assert "coalesce" not in sql.lower()


class TestGetOrderColumn:
    """Tests for SmartPlaylistService._get_order_column."""

    @pytest.fixture
    def service(self):
        return SmartPlaylistService(db=AsyncMock())

    def test_track_field(self, service):
        col = service._get_order_column("title")
        assert col is not None

    def test_analysis_field(self, service):
        col = service._get_order_column("energy")
        assert col is not None

    def test_play_count_with_coalesce(self, service):
        col = service._get_order_column("play_count")
        from sqlalchemy.dialects import postgresql
        sql = str(col.compile(dialect=postgresql.dialect()))
        assert "coalesce" in sql.lower()

    def test_total_play_seconds_with_coalesce(self, service):
        col = service._get_order_column("total_play_seconds")
        from sqlalchemy.dialects import postgresql
        sql = str(col.compile(dialect=postgresql.dialect()))
        assert "coalesce" in sql.lower()

    def test_last_played_at(self, service):
        col = service._get_order_column("last_played_at")
        assert col is not None

    def test_unknown_field_defaults_to_title(self, service):
        """Unknown fields should default to Track.title."""
        from app.db.models import Track
        col = service._get_order_column("nonexistent_field")
        assert col is Track.title
