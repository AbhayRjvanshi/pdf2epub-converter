"""Phase 7 (engine): the shared Tier-2 routing policy is one source of truth.

The truth table here is the contract the engine driver and the application
preflight both rely on; the offline + CMap cell is the corrected rule.
"""

from pdf2epub.engine.confidence_router import (
    VISION_BYPASS_RATIO,
    PageConfidenceReport,
    RoutingTarget,
    plan_tier2_routing,
)

DIGEST = RoutingTarget.TIER2_LLM_DIGEST
VISION = RoutingTarget.TIER2_VISION_OCR
TIER1 = RoutingTarget.TIER1_HEURISTIC


def report(index, target, cmap=False):
    return PageConfidenceReport(
        page_num=index + 1,
        page_index=index,
        score=50,
        target=target,
        cmap_corrupted=cmap,
    )


def test_digest_pages_always_reach_the_handler_online():
    plan = plan_tier2_routing([report(0, DIGEST)], total_pages=1, online=True)
    assert [r.page_index for r in plan.handler] == [0]
    assert plan.bypass == ()
    assert plan.required_routes == frozenset({"digest"})


def test_online_vision_majority_reaches_the_model():
    plan = plan_tier2_routing(
        [report(0, VISION), report(1, VISION)], total_pages=2, online=True
    )
    assert len(plan.handler) == 2
    assert plan.bypassed_vision == 0
    assert plan.required_routes == frozenset({"vision"})


def test_online_vision_minority_is_embedded():
    plan = plan_tier2_routing([report(0, VISION)], total_pages=100, online=True)
    assert [r.page_index for r in plan.bypass] == [0]
    assert plan.handler == ()
    assert plan.required_routes == frozenset()


def test_online_vision_minority_cmap_corrupted_reaches_the_model():
    plan = plan_tier2_routing(
        [report(0, VISION, cmap=True)], total_pages=100, online=True
    )
    assert len(plan.handler) == 1
    assert plan.required_routes == frozenset({"vision"})


def test_offline_vision_is_always_embedded():
    plan = plan_tier2_routing(
        [report(0, VISION), report(1, VISION, cmap=True)],
        total_pages=2,
        online=False,
    )
    assert plan.bypassed_vision == 2
    assert plan.handler == ()


def test_offline_cmap_corrupted_vision_is_embedded_not_placeheld():
    # the corrected cell: offline + CMap used to fall through to the
    # "no OCR configured" placeholder instead of its raster
    plan = plan_tier2_routing(
        [report(0, VISION, cmap=True)], total_pages=1, online=False
    )
    assert [r.page_index for r in plan.bypass] == [0]
    assert plan.handler == ()


def test_offline_digest_still_reaches_the_handler_and_needs_no_routes():
    plan = plan_tier2_routing([report(0, DIGEST)], total_pages=1, online=False)
    assert len(plan.handler) == 1
    assert plan.required_routes == frozenset()


def test_ratio_boundary_is_exclusive():
    # exactly VISION_BYPASS_RATIO is not "below" it -> the model is consulted
    pages = int(round(1 / VISION_BYPASS_RATIO))
    plan = plan_tier2_routing([report(0, VISION)], total_pages=pages, online=True)
    assert len(plan.handler) == 1


def test_tier1_pages_are_excluded_from_the_plan():
    plan = plan_tier2_routing(
        [report(0, TIER1), report(1, DIGEST)], total_pages=2, online=True
    )
    assert [r.page_index for r in plan.handler] == [1]
    assert plan.bypass == ()


def test_mixed_document_requires_both_routes_online():
    plan = plan_tier2_routing(
        [report(0, DIGEST), report(1, VISION), report(2, VISION)],
        total_pages=3,
        online=True,
    )
    assert plan.required_routes == frozenset({"digest", "vision"})


def test_zero_pages_does_not_crash():
    plan = plan_tier2_routing([], total_pages=0, online=True)
    assert plan.handler == () and plan.bypass == ()
    assert plan.required_routes == frozenset()
