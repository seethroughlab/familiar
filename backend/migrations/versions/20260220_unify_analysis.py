"""Unify track analysis: typed columns, merge deep analysis, drop old table.

Promotes JSONB features to typed columns on track_analysis, migrates data
from track_deep_analysis into track_analysis.analysis_detail, then drops
the track_deep_analysis table and the features JSONB column.

Revision ID: 20260220_unify_analysis
Revises: 20260219_frontend_logs
Create Date: 2026-02-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260220_unify_analysis"
down_revision = "20260219_frontend_logs"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table_name, "column": column_name},
    )
    return result.fetchone() is not None


def _table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = :table"
        ),
        {"table": table_name},
    )
    return result.fetchone() is not None


def _index_exists(index_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT indexname FROM pg_indexes WHERE indexname = :name"
        ),
        {"name": index_name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    # ── Step 1: Add typed feature columns to track_analysis ──────────
    typed_columns = [
        # Phase 1: librosa features (promoted from JSONB)
        ("bpm", sa.Float()),
        ("key", sa.String(10)),
        ("energy", sa.Float()),
        ("danceability", sa.Float()),
        ("valence", sa.Float()),
        ("acousticness", sa.Float()),
        ("instrumentalness", sa.Float()),
        ("speechiness", sa.Float()),
        ("loudness_lufs", sa.Float()),
        ("track_peak", sa.Float()),
        ("replaygain_track_gain", sa.Float()),
        # Phase 1: analysis algorithm scalars
        ("harmonic_complexity", sa.Float()),
        ("key_stability", sa.String(20)),
        ("modal_character", sa.String(40)),
        ("modal_confidence", sa.Float()),
        ("swing_ratio", sa.Float()),
        ("syncopation", sa.Float()),
        ("tempo_character", sa.String(20)),
        ("brightness", sa.Float()),
        ("dynamic_range_db", sa.Float()),
        ("energy_shape", sa.String(20)),
        ("section_count", sa.Integer()),
        ("form_string", sa.String(50)),
        ("avg_section_length", sa.Float()),
        # Phase 3: melodic features
        ("note_density", sa.Float()),
        ("interval_character", sa.String(20)),
        ("pitch_range", sa.Integer()),
        # Structural columns
        ("analysis_detail", postgresql.JSONB()),
        ("has_melodic", sa.Boolean(), {"server_default": sa.text("false")}),
        ("midi_path", sa.String(500)),
        ("melodic_version", sa.Integer(), {"server_default": sa.text("0")}),
    ]

    # Map SQLAlchemy types to PostgreSQL DDL type strings
    _sa_to_pg = {
        "FLOAT": "DOUBLE PRECISION",
        "VARCHAR": "VARCHAR",
        "STRING": "VARCHAR",
        "INTEGER": "INTEGER",
        "BOOLEAN": "BOOLEAN",
        "JSONB": "JSONB",
    }

    for col_def in typed_columns:
        col_name = col_def[0]
        col_type = col_def[1]
        kwargs = col_def[2] if len(col_def) > 2 else {}

        # Build PostgreSQL type string
        sa_type_name = type(col_type).__name__.upper()
        pg_type = _sa_to_pg.get(sa_type_name, sa_type_name)
        if hasattr(col_type, "length") and col_type.length:
            pg_type = f"VARCHAR({col_type.length})"

        # Build column definition with optional DEFAULT
        col_sql = f'ALTER TABLE track_analysis ADD COLUMN IF NOT EXISTS "{col_name}" {pg_type}'
        if "server_default" in kwargs:
            col_sql += f" DEFAULT {kwargs['server_default'].text}"
        op.execute(sa.text(col_sql))

    # ── Step 2: Migrate JSONB features → typed columns ───────────────
    # Only runs if features column still exists (uses DO block for safety)
    op.execute(sa.text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'track_analysis' AND column_name = 'features'
            ) THEN
                UPDATE track_analysis SET
                    bpm = COALESCE(bpm, (features->>'bpm')::float),
                    key = COALESCE(key, features->>'key'),
                    energy = COALESCE(energy, (features->>'energy')::float),
                    danceability = COALESCE(danceability, (features->>'danceability')::float),
                    valence = COALESCE(valence, (features->>'valence')::float),
                    acousticness = COALESCE(acousticness, (features->>'acousticness')::float),
                    instrumentalness = COALESCE(instrumentalness, (features->>'instrumentalness')::float),
                    speechiness = COALESCE(speechiness, (features->>'speechiness')::float),
                    loudness_lufs = COALESCE(loudness_lufs, (features->>'loudness_lufs')::float),
                    track_peak = COALESCE(track_peak, (features->>'track_peak')::float),
                    replaygain_track_gain = COALESCE(replaygain_track_gain, (features->>'replaygain_track_gain')::float)
                WHERE features IS NOT NULL AND features != '{}'::jsonb;
            END IF;
        END $$;
    """))

    # ── Step 3: Migrate track_deep_analysis → track_analysis ─────────
    # Wrapped in DO block so the UPDATE is skipped if table was already dropped
    op.execute(sa.text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'track_deep_analysis'
            ) THEN
                -- Extract scalar features from deep analysis results and merge into track_analysis
                UPDATE track_analysis ta SET
                    analysis_detail = tda.results,
                    has_melodic = CASE
                        WHEN tda.results->'melodic' IS NOT NULL
                             AND (tda.results->'melodic'->>'degraded')::boolean IS NOT TRUE
                        THEN true ELSE false
                    END,
                    midi_path = COALESCE(ta.midi_path, tda.midi_path),
                    melodic_version = tda.version,
                    harmonic_complexity = COALESCE(ta.harmonic_complexity,
                        (tda.results->'harmonic'->>'harmonic_rhythm')::float),
                    key_stability = COALESCE(ta.key_stability,
                        tda.results->'harmonic'->>'key_stability'),
                    modal_character = COALESCE(ta.modal_character,
                        tda.results->'harmonic'->>'modal_character'),
                    modal_confidence = COALESCE(ta.modal_confidence,
                        (tda.results->'harmonic'->>'modal_confidence')::float),
                    swing_ratio = COALESCE(ta.swing_ratio,
                        (tda.results->'rhythmic'->>'swing_ratio')::float),
                    syncopation = COALESCE(ta.syncopation,
                        (tda.results->'rhythmic'->>'syncopation_index')::float),
                    tempo_character = COALESCE(ta.tempo_character,
                        tda.results->'rhythmic'->>'tempo_stability'),
                    brightness = COALESCE(ta.brightness,
                        CASE WHEN tda.results->'spectral'->>'brightness' = 'dark' THEN 0.1
                             WHEN tda.results->'spectral'->>'brightness' = 'neutral' THEN 0.5
                             WHEN tda.results->'spectral'->>'brightness' = 'bright' THEN 0.9
                             ELSE NULL END),
                    dynamic_range_db = COALESCE(ta.dynamic_range_db,
                        (tda.results->'energy'->>'dynamic_range_db')::float),
                    energy_shape = COALESCE(ta.energy_shape,
                        tda.results->'energy'->>'energy_shape'),
                    section_count = COALESCE(ta.section_count,
                        (tda.results->'structural'->>'section_count')::int),
                    form_string = COALESCE(ta.form_string,
                        tda.results->'structural'->>'form'),
                    avg_section_length = COALESCE(ta.avg_section_length,
                        (tda.results->'structural'->>'avg_section_length')::float),
                    note_density = COALESCE(ta.note_density,
                        (tda.results->'melodic'->>'note_density_per_beat')::float),
                    interval_character = COALESCE(ta.interval_character,
                        tda.results->'melodic'->>'interval_character'),
                    pitch_range = COALESCE(ta.pitch_range,
                        CASE WHEN tda.results->'melodic'->'pitch_range' IS NOT NULL
                             THEN (tda.results->'melodic'->'pitch_range'->>'high')::int
                                  - (tda.results->'melodic'->'pitch_range'->>'low')::int
                             ELSE NULL END)
                FROM track_deep_analysis tda
                WHERE ta.track_id = tda.track_id
                    AND ta.version = (
                        SELECT MAX(version) FROM track_analysis
                        WHERE track_id = tda.track_id
                    );
            END IF;
        END $$;
    """))

    # Drop the old table (IF EXISTS for idempotency)
    op.execute(sa.text("DROP TABLE IF EXISTS track_deep_analysis"))

    # ── Step 4: Drop features JSONB column ───────────────────────────
    op.execute(sa.text("ALTER TABLE track_analysis DROP COLUMN IF EXISTS features"))

    # ── Step 5: Add indexes on commonly filtered columns ─────────────
    for idx_name, col_name in [
        ("ix_track_analysis_bpm", "bpm"),
        ("ix_track_analysis_energy", "energy"),
        ("ix_track_analysis_valence", "valence"),
        ("ix_track_analysis_key", "key"),
        ("ix_track_analysis_swing_ratio", "swing_ratio"),
        ("ix_track_analysis_brightness", "brightness"),
    ]:
        op.execute(sa.text(
            f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON track_analysis ("{col_name}")'
        ))

    # ── Step 6: Set NOT NULL on columns with server defaults ───────────
    for col_name, col_type in [("has_melodic", sa.Boolean()), ("melodic_version", sa.Integer())]:
        op.alter_column("track_analysis", col_name, nullable=False, existing_type=col_type)

    # ── Step 7: Per-phase versioning ─────────────────────────────────
    # Rename version → features_version
    if _column_exists("track_analysis", "version") and not _column_exists("track_analysis", "features_version"):
        op.alter_column("track_analysis", "version", new_column_name="features_version")

    # Add embedding_version column
    if not _column_exists("track_analysis", "embedding_version"):
        op.execute(sa.text(
            "ALTER TABLE track_analysis ADD COLUMN embedding_version INTEGER DEFAULT 0 NOT NULL"
        ))
        # Backfill: tracks that have an embedding were analyzed at features_version
        op.execute(sa.text(
            "UPDATE track_analysis SET embedding_version = features_version "
            "WHERE embedding IS NOT NULL"
        ))

    # Replace UniqueConstraint: (track_id, version) → (track_id)
    op.execute(sa.text(
        "ALTER TABLE track_analysis DROP CONSTRAINT IF EXISTS uq_track_analysis_version"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_track_analysis_track_id') THEN "
        "ALTER TABLE track_analysis ADD CONSTRAINT uq_track_analysis_track_id UNIQUE (track_id); "
        "END IF; END $$"
    ))


def downgrade() -> None:
    # Revert per-phase versioning
    op.execute(sa.text(
        "ALTER TABLE track_analysis DROP CONSTRAINT IF EXISTS uq_track_analysis_track_id"
    ))
    if _column_exists("track_analysis", "embedding_version"):
        op.drop_column("track_analysis", "embedding_version")
    if _column_exists("track_analysis", "features_version") and not _column_exists("track_analysis", "version"):
        op.alter_column("track_analysis", "features_version", new_column_name="version")
    # Re-add old constraint (may fail if duplicates exist, but best-effort for downgrade)
    op.execute(sa.text(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_track_analysis_version') THEN "
        "ALTER TABLE track_analysis ADD CONSTRAINT uq_track_analysis_version UNIQUE (track_id, version); "
        "END IF; END $$"
    ))

    # Re-add features JSONB column
    if not _column_exists("track_analysis", "features"):
        op.add_column("track_analysis", sa.Column("features", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")))

    # Populate features JSONB from typed columns
    op.execute(sa.text("""
        UPDATE track_analysis SET features = jsonb_strip_nulls(jsonb_build_object(
            'bpm', bpm, 'key', key, 'energy', energy, 'danceability', danceability,
            'valence', valence, 'acousticness', acousticness,
            'instrumentalness', instrumentalness, 'speechiness', speechiness,
            'loudness_lufs', loudness_lufs, 'track_peak', track_peak,
            'replaygain_track_gain', replaygain_track_gain
        ))
    """))

    # Re-create track_deep_analysis table
    op.create_table(
        "track_deep_analysis",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("track_id", sa.Uuid(), sa.ForeignKey("tracks.id", ondelete="CASCADE"), index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("results", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("midi_path", sa.String(500)),
        sa.Column("section_errors", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("analysis_duration_seconds", sa.Float()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("track_id", "version", name="uq_track_deep_analysis_version"),
    )

    # Migrate analysis_detail back to track_deep_analysis
    op.execute(sa.text("""
        INSERT INTO track_deep_analysis (id, track_id, version, results, midi_path, created_at)
        SELECT gen_random_uuid(), track_id, COALESCE(melodic_version, 0), analysis_detail, midi_path, created_at
        FROM track_analysis
        WHERE analysis_detail IS NOT NULL
    """))

    # Drop indexes
    for idx_name in [
        "ix_track_analysis_bpm", "ix_track_analysis_energy",
        "ix_track_analysis_valence", "ix_track_analysis_key",
        "ix_track_analysis_swing_ratio", "ix_track_analysis_brightness",
    ]:
        if _index_exists(idx_name):
            op.drop_index(idx_name, "track_analysis")

    # Drop typed columns
    typed_col_names = [
        "bpm", "key", "energy", "danceability", "valence", "acousticness",
        "instrumentalness", "speechiness", "loudness_lufs", "track_peak",
        "replaygain_track_gain", "harmonic_complexity", "key_stability",
        "modal_character", "modal_confidence", "swing_ratio", "syncopation",
        "tempo_character", "brightness", "dynamic_range_db", "energy_shape",
        "section_count", "form_string", "avg_section_length",
        "note_density", "interval_character", "pitch_range",
        "analysis_detail", "has_melodic", "midi_path", "melodic_version",
    ]
    for col_name in typed_col_names:
        if _column_exists("track_analysis", col_name):
            op.drop_column("track_analysis", col_name)
