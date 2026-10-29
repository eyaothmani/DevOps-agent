from agent.groundedness import compute_groundedness_score
from agent.models import RCAResult


def _rca(steps):
    return RCAResult(
        diagnosis="test",
        confidence=90,
        suggested_action="ScaleOut",
        reasoning_steps=steps,
    )


def test_groundedness_grounded_step():
    logs = "kernel: high sustained load average 8.2 detected on process nginx"
    result = _rca(["Le log mentionne un load average de 8.2 sur le process nginx"])
    assert compute_groundedness_score(result, logs) == 1.0


def test_groundedness_hallucinated_step():
    logs = "kernel: load average 8.2"
    result = _rca(["Le disque est plein à 95% selon les métriques CloudWatch"])
    assert compute_groundedness_score(result, logs) == 0.0


def test_groundedness_empty_steps():
    result = _rca([])
    assert compute_groundedness_score(result, "peu importe") == 0.0
