"""Backward-compatibility shim. Moved to app.services.metadata.audio_identification."""

from app.services.metadata.audio_identification import *  # noqa: F401,F403
from app.services.metadata.audio_identification import (  # noqa: F401
    AudioIdentificationService,
    IdentifyCandidate,
    IdentifyResult,
    get_audio_identification_service,
)
