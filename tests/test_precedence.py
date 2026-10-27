# 1. Python standard library
# (None)

# 2. Third-party installed packages
import pytest

# 3. Code-level (our own) imports
from app.dto.retrieval_dto import PrecedenceCandidate
from app.helper.retrieval.precedence_helper import PrecedenceService


def test_authority_beats_recency_and_scope():
    """Verify policy outranks FAQ even if FAQ has a later effective date."""
    policy = PrecedenceCandidate(
        doc_id="POL-01",
        locator="Section 3",
        doc_type="policy",
        regions=["GLOBAL"],
        effective_date="2026-01-01",
        value="20 days annual leave",
    )
    faq = PrecedenceCandidate(
        doc_id="FAQ-01",
        locator="p. 1",
        doc_type="faq",
        regions=["GLOBAL"],
        effective_date="2026-06-01",
        value="25 days annual leave",
    )

    # Policy must beat FAQ on authority
    assert PrecedenceService.compare_candidates(policy, faq) == 1
    assert PrecedenceService.compare_candidates(faq, policy) == -1

    res = PrecedenceService.resolve([policy, faq], [], region="IN")
    assert len(res.winners) == 1
    assert res.winners[0].doc_id == "POL-01"
    assert not res.conflict


def test_scope_beats_recency():
    """Verify regional document beats GLOBAL policy even if GLOBAL policy is newer."""
    de_addendum = PrecedenceCandidate(
        doc_id="ADD-DE-01",
        locator="Section 2",
        doc_type="addendum",
        regions=["DE"],
        effective_date="2025-06-01",
        value="30 days vacation",
    )
    global_policy_v2 = PrecedenceCandidate(
        doc_id="POL-GLOBAL-V2",
        locator="Section 4",
        doc_type="policy",
        regions=["GLOBAL"],
        effective_date="2026-04-01",
        value="22 days vacation",
    )

    # Regional addendum beats GLOBAL policy on scope
    assert PrecedenceService.compare_candidates(de_addendum, global_policy_v2) == 1
    assert PrecedenceService.compare_candidates(global_policy_v2, de_addendum) == -1

    res = PrecedenceService.resolve([de_addendum, global_policy_v2], [], region="DE")
    assert len(res.winners) == 1
    assert res.winners[0].doc_id == "ADD-DE-01"


def test_recency_breaks_ties_on_same_authority_and_scope():
    """Verify newer policy outranks older policy when authority and scope match."""
    v1 = PrecedenceCandidate(
        doc_id="POL-V1",
        locator="Section 1",
        doc_type="policy",
        regions=["GLOBAL"],
        effective_date="2025-01-01",
        value="15 days",
    )
    v2 = PrecedenceCandidate(
        doc_id="POL-V2",
        locator="Section 1",
        doc_type="policy",
        regions=["GLOBAL"],
        effective_date="2026-04-01",
        value="18 days",
    )

    assert PrecedenceService.compare_candidates(v2, v1) == 1
    res = PrecedenceService.resolve([v1, v2], [], region="IN")
    assert len(res.winners) == 1
    assert res.winners[0].doc_id == "POL-V2"


def test_unresolved_conflict_returns_both_values_and_citations():
    """Verify equal authority, scope, and effective date produces conflict=True with both citations."""
    doc_a = PrecedenceCandidate(
        doc_id="MEMO-A",
        locator="p. 1",
        doc_type="memo",
        regions=["IN"],
        effective_date="2026-05-01",
        value="Core hours are 9am - 5pm",
    )
    doc_b = PrecedenceCandidate(
        doc_id="MEMO-B",
        locator="p. 2",
        doc_type="memo",
        regions=["IN"],
        effective_date="2026-05-01",
        value="Core hours are 10am - 4pm",
    )

    res = PrecedenceService.resolve([doc_a, doc_b], [], region="IN")
    assert res.conflict is True
    assert len(res.winners) == 2
    cited_ids = {c.doc_id for c in res.citations}
    assert cited_ids == {"MEMO-A", "MEMO-B"}


def test_worked_example_india_and_germany_cases():
    """Verify the exact worked example from Part 3.5 of the specification:

    Candidates:
      Global v1 (2025-01-01, 2 days) [policy, GLOBAL]
      Global v2 (2026-04-01, 3 days) [policy, GLOBAL]
      FAQ (2026-05-01, 2 days) [faq, GLOBAL]
      DE addendum (2025-06-01, 5 days) [addendum, DE]
      Global v3 (2027-01-01, 4 days) [policy, GLOBAL] (upcoming)
    """
    gv1 = PrecedenceCandidate(doc_id="GV1", locator="p.1", doc_type="policy", regions=["GLOBAL"], effective_date="2025-01-01", value="2")
    gv2 = PrecedenceCandidate(doc_id="GV2", locator="p.1", doc_type="policy", regions=["GLOBAL"], effective_date="2026-04-01", value="3")
    faq = PrecedenceCandidate(doc_id="FAQ", locator="p.1", doc_type="faq", regions=["GLOBAL"], effective_date="2026-05-01", value="2")
    de_add = PrecedenceCandidate(doc_id="DE_ADD", locator="p.1", doc_type="addendum", regions=["DE"], effective_date="2025-06-01", value="5")
    gv3 = PrecedenceCandidate(doc_id="GV3", locator="p.1", doc_type="policy", regions=["GLOBAL"], effective_date="2027-01-01", value="4")

    # 1. India: Eligible are GV1, GV2, FAQ. Upcoming is GV3.
    res_in = PrecedenceService.resolve([gv1, gv2, faq], [gv3], region="IN")
    # GV2 wins on recency over GV1, and authority over FAQ
    assert len(res_in.winners) == 1
    assert res_in.winners[0].doc_id == "GV2"
    # GV3 is mentioned for India because it raises to 4 on 2027-01-01 beating GV2
    assert res_in.upcoming_change is not None
    assert res_in.upcoming_change.doc_id == "GV3"
    assert {c.doc_id for c in res_in.citations} == {"GV2", "GV3"}

    # 2. Germany: Eligible are GV1, GV2, FAQ, DE_ADD. Upcoming is GV3.
    res_de = PrecedenceService.resolve([gv1, gv2, faq, de_add], [gv3], region="DE")
    # DE_ADD wins on Scope over GLOBAL
    assert len(res_de.winners) == 1
    assert res_de.winners[0].doc_id == "DE_ADD"
    # GV3 is NOT mentioned for Germany because DE_ADD still wins on Scope in 2027!
    assert res_de.upcoming_change is None
    assert {c.doc_id for c in res_de.citations} == {"DE_ADD"}
