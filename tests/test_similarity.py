import pytest

from wtest.catalog import CatalogError
from wtest.config import SimilarityConfig
from wtest.signature import Signature, extract_signature
from wtest.similarity import jaccard, score, sequence_similarity

from helpers import RESTART, scenario

CFG = SimilarityConfig()


def sig(steps, pre=(), crit=()):
    return Signature(tuple(steps), frozenset(pre), frozenset(crit))


def test_signature_drops_values_keeps_signature_params(catalog):
    s = extract_signature(RESTART, catalog)
    assert s.steps == ("set_config:timeout", "restart_service", "wait", "service_status")
    assert s.actions == {"set_config", "restart_service", "wait", "service_status"}


def test_value_only_change_has_same_signature(catalog):
    other = scenario(
        ("set_config", {"key": "timeout", "value": 999}),
        ("restart_service", {"svc": "OtherSvc"}),
        ("wait", {"seconds": 5}),
        ("service_status", {"svc": "OtherSvc"}),
        pre=["AgentSvc running"],
        crit=["AgentSvc running within 5s", "No  crash dump"],  # 숫자·대소문자·공백만 다름
    )
    assert extract_signature(other, catalog).hash == extract_signature(RESTART, catalog).hash


def test_value_classes_when_enabled(catalog):
    def token(value):
        sc = scenario(("set_config", {"key": "timeout", "value": value}))
        return extract_signature(sc, catalog, value_classes=True).steps[0]

    assert token(30) == "set_config:timeout@value=normal"
    assert token(0) == "set_config:timeout@value=boundary"
    assert token(3600) == "set_config:timeout@value=boundary"
    assert token(-1) == "set_config:timeout@value=invalid"


@pytest.mark.parametrize(
    "bad",
    [
        scenario(("format_disk", {})),
        scenario(("wait", {"secs": 1})),
        {"title": "x", "steps": []},
    ],
)
def test_signature_rejects_outside_catalog(catalog, bad):
    with pytest.raises(CatalogError):
        extract_signature(bad, catalog)


def test_edge_cases_empty():
    assert jaccard(frozenset(), frozenset()) == 1.0
    assert sequence_similarity([], []) == 1.0
    assert sequence_similarity(["a"], []) == 0.0


def test_sequence_similarity_is_order_sensitive():
    assert sequence_similarity(["a", "b", "c"], ["a", "b", "c"]) == 1.0
    assert sequence_similarity(["a", "b", "c"], ["c", "b", "a"]) == pytest.approx(1 / 3)


def test_threshold_boundary_exact_and_below():
    steps = ["a", "b"]
    # 0.6×1 + 0.2×(1/2) + 0.2×0 = 0.7 → 임계값과 같으므로 '동일 테스트'
    exact = score(sig(steps, pre={"p"}, crit={"x"}), sig(steps, pre={"p", "q"}, crit={"y"}), CFG)
    assert exact == 0.7
    assert exact >= CFG.threshold
    # 0.6×1 + 0.2×(1/3) + 0 = 0.6667 → 다른 테스트
    below = score(sig(steps, pre={"p"}, crit={"x"}), sig(steps, pre={"p", "q", "r"}, crit={"y"}), CFG)
    assert below < CFG.threshold
