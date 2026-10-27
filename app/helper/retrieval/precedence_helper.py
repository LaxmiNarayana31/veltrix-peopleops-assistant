"""Precedence service implementing Section 5 rules: Authority, Scope, Recency, Conflict."""

import logging
from typing import Dict, List, Optional

from app.dto.chat_dto import CitationDTO
from app.dto.document_dto import ChunkDTO
from app.dto.retrieval_dto import PrecedenceCandidate, PrecedenceResolutionResult
from app.exceptions.custom_exceptions import AppException, RetrievalException

logger = logging.getLogger(__name__)

HIGH_AUTHORITY_TYPES = {"policy", "addendum", "memo", "handbook", "calendar"}
LOW_AUTHORITY_TYPES = {"faq", "wiki"}


class PrecedenceService:
    """Implements Section 5 precedence rules: Authority -> Scope -> Recency -> Conflict."""

    @classmethod
    def authority_rank(cls, doc_type: str) -> int:
        """Return 1 for authoritative documents, 0 for informal wiki/faq."""
        return 1 if doc_type.lower().strip() in HIGH_AUTHORITY_TYPES else 0

    @classmethod
    def scope_rank(cls, regions: List[str]) -> int:
        """Return 1 for region-specific documents, 0 for GLOBAL scope."""
        return 0 if "GLOBAL" in regions else 1

    @classmethod
    def compare_candidates(cls, a: PrecedenceCandidate, b: PrecedenceCandidate) -> int:
        """Compare candidate a and b under Section 5 rules."""
        auth_a = cls.authority_rank(a.doc_type)
        auth_b = cls.authority_rank(b.doc_type)
        if auth_a > auth_b:
            return 1
        if auth_b > auth_a:
            return -1

        scope_a = cls.scope_rank(a.regions)
        scope_b = cls.scope_rank(b.regions)
        if scope_a > scope_b:
            return 1
        if scope_b > scope_a:
            return -1

        if a.effective_date > b.effective_date:
            return 1
        if b.effective_date > a.effective_date:
            return -1

        return 0

    @classmethod
    def resolve(
        cls,
        eligible_candidates: List[PrecedenceCandidate],
        upcoming_candidates: List[PrecedenceCandidate],
        region: str,
    ) -> PrecedenceResolutionResult:
        """Execute deterministic Section 5 conflict resolution."""
        try:
            if not eligible_candidates:
                return PrecedenceResolutionResult()

            unique_candidates: Dict[str, PrecedenceCandidate] = {}
            for c in eligible_candidates:
                if c.doc_id not in unique_candidates:
                    unique_candidates[c.doc_id] = c

            candidates_list = list(unique_candidates.values())
            if len(candidates_list) == 1:
                winner = candidates_list[0]
                citations = [CitationDTO(doc_id=winner.doc_id, locator=winner.locator)]
                upcoming = cls._find_winning_upcoming(winner, upcoming_candidates, region)
                if upcoming:
                    citations.append(CitationDTO(doc_id=upcoming.doc_id, locator=upcoming.locator))
                return PrecedenceResolutionResult(
                    winners=[winner],
                    conflict=False,
                    upcoming_change=upcoming,
                    citations=citations,
                    resolution_notes=f"Single eligible document {winner.doc_id} applies.",
                )

            current_winners: List[PrecedenceCandidate] = [candidates_list[0]]

            for challenger in candidates_list[1:]:
                comp = cls.compare_candidates(challenger, current_winners[0])
                if comp > 0:
                    current_winners = [challenger]
                elif comp == 0:
                    val_a = (current_winners[0].normalized_value or current_winners[0].value).strip().lower()
                    val_b = (challenger.normalized_value or challenger.value).strip().lower()
                    if val_a != val_b:
                        current_winners.append(challenger)
                    else:
                        pass
                else:
                    pass

            is_conflict = len(current_winners) > 1
            citations = [CitationDTO(doc_id=w.doc_id, locator=w.locator) for w in current_winners]

            upcoming_winner = None
            if not is_conflict:
                upcoming_winner = cls._find_winning_upcoming(current_winners[0], upcoming_candidates, region)
                if upcoming_winner:
                    citations.append(CitationDTO(doc_id=upcoming_winner.doc_id, locator=upcoming_winner.locator))

            notes = "Resolved precedence successfully."
            if is_conflict:
                notes = f"Unresolved conflict between {', '.join(w.doc_id for w in current_winners)}."

            return PrecedenceResolutionResult(
                winners=current_winners,
                conflict=is_conflict,
                upcoming_change=upcoming_winner,
                citations=citations,
                resolution_notes=notes,
            )
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Precedence resolution failed")
            raise RetrievalException("Error executing precedence logic") from exc

    @classmethod
    def _find_winning_upcoming(
        cls,
        current_winner: PrecedenceCandidate,
        upcoming_candidates: List[PrecedenceCandidate],
        region: str,
    ) -> Optional[PrecedenceCandidate]:
        """Check if any upcoming document would win on its effective date under Section 5 rules."""
        if not upcoming_candidates:
            return None

        for upcoming in upcoming_candidates:
            if region not in upcoming.regions and "GLOBAL" not in upcoming.regions:
                continue

            comp = cls.compare_candidates(upcoming, current_winner)
            if comp > 0:
                return upcoming

        return None

    @classmethod
    def build_candidates_from_chunks(
        cls,
        chunks: List[ChunkDTO],
        is_upcoming: bool = False,
    ) -> List[PrecedenceCandidate]:
        """Convert retrieved chunks to precedence candidates using document metadata."""
        try:
            candidates: List[PrecedenceCandidate] = []
            for c in chunks:
                candidates.append(
                    PrecedenceCandidate(
                        doc_id=c.doc_id,
                        locator=c.locator,
                        doc_type=c.doc_type,
                        regions=c.regions,
                        effective_date=c.effective_date,
                        value=c.text[:200],
                        normalized_value=c.text[:100],
                    )
                )
            return candidates
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed building candidates from chunks")
            raise RetrievalException("Candidate creation failed") from exc


# Module-level singleton
_precedence_service: Optional[PrecedenceService] = None


def get_precedence_service() -> PrecedenceService:
    """Return singleton PrecedenceService instance."""
    global _precedence_service
    if _precedence_service is None:
        _precedence_service = PrecedenceService()
    return _precedence_service

# Aliases for helper usage
PrecedenceHelper = PrecedenceService
get_precedence_helper = get_precedence_service
