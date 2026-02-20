"""Track analysis subpackage.

Re-exports all public names for backward compatibility so that
``from app.services.track_analysis import X`` continues to work.
"""

from app.services.track_analysis.constants import MIDI_DATA_DIR
from app.services.track_analysis.pipeline import (
    extract_feature_scalars,
    extract_melodic_scalars,
    run_analysis,
    run_backfill,
    run_cheap_sections,
    run_track_melodic,
)
from app.services.track_analysis.reports import (
    generate_comparative_report,
    generate_report,
)

__all__ = [
    "MIDI_DATA_DIR",
    "extract_feature_scalars",
    "extract_melodic_scalars",
    "generate_comparative_report",
    "generate_report",
    "run_analysis",
    "run_backfill",
    "run_cheap_sections",
    "run_track_melodic",
]
