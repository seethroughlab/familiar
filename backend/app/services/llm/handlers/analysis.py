"""Analysis tool handlers (get_track_analysis)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select

from app.db.models import Track, TrackAnalysis, TrackStatus

if TYPE_CHECKING:
    from app.services.llm.executor import ToolExecutor

logger = logging.getLogger(__name__)


class AnalysisHandlersMixin:
    """Mixin providing analysis tool handlers."""

    async def _get_track_analysis(
        self: "ToolExecutor",
        track_ids: list[str],
        include_comparative: bool = True,
    ) -> dict[str, Any]:
        """Get musical analysis for one or more tracks.

        Checks cache first, triggers analysis if needed.
        Returns markdown report content for LLM consumption.
        """
        import asyncio

        from app.services.background import get_background_manager
        from app.services.track_analysis import (
            generate_comparative_report,
            generate_report,
        )

        if not track_ids:
            return {"error": "No track IDs provided"}

        if len(track_ids) > 10:
            return {"error": "Maximum 10 tracks per analysis request"}

        bg = get_background_manager()
        analyses = []
        track_metas = []
        errors = []

        for tid in track_ids:
            try:
                # Check for existing analysis_detail on TrackAnalysis
                analysis = (
                    await self.db.execute(
                        select(TrackAnalysis)
                        .where(TrackAnalysis.track_id == UUID(tid))
                    )
                ).scalar_one_or_none()

                has_detail = analysis and analysis.analysis_detail

                if not has_detail:
                    # Trigger analysis and wait for it
                    await bg.run_track_analysis(tid)
                    # Wait for completion (poll up to 120s)
                    for _ in range(60):
                        await asyncio.sleep(2)
                        self.db.expire_all()
                        analysis = (
                            await self.db.execute(
                                select(TrackAnalysis)
                                .where(TrackAnalysis.track_id == UUID(tid))
                                    )
                        ).scalar_one_or_none()
                        if analysis and analysis.analysis_detail:
                            break

                if not analysis or not analysis.analysis_detail:
                    errors.append(f"Analysis timed out for track {tid}")
                    continue

                # Load track metadata
                track = (
                    await self.db.execute(select(Track).where(Track.active_filter(), Track.id == UUID(tid)))
                ).scalar_one_or_none()

                if track:
                    analyses.append(analysis.analysis_detail)
                    track_metas.append({
                        "artist": track.artist,
                        "title": track.title,
                        "album": track.album,
                        "duration_seconds": track.duration_seconds,
                    })

            except Exception as e:
                errors.append(f"Error analyzing track {tid}: {str(e)}")

        if not analyses:
            return {
                "error": "No analyses completed",
                "errors": errors,
            }

        # Generate report (for_llm=True strips heavy raw data sections)
        if len(analyses) == 1:
            report = generate_report(analyses[0], track_metas[0], for_llm=True)
        elif include_comparative:
            report = generate_comparative_report(analyses, track_metas, for_llm=True)
        else:
            # Multiple tracks without comparison: just concatenate
            parts = []
            for a, m in zip(analyses, track_metas):
                parts.append(generate_report(a, m, for_llm=True))
            report = "\n\n---\n\n".join(parts)

        result: dict[str, Any] = {
            "report": report,
            "tracks_analyzed": len(analyses),
            "total_requested": len(track_ids),
        }
        if errors:
            result["errors"] = errors

        return result
