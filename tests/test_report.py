"""`report.py` — 값 검증 리포트와 비교 리포트. **둘은 섞지 않는다.**"""

from __future__ import annotations

import json
from pathlib import Path

from strictler.errors import Finding, NotRunCause
from strictler.report import (
    CompareEntry,
    CompareReport,
    Report,
    Summary,
    build_compare_report,
    build_report,
    render_json,
    render_text,
    write_compare_report,
)

# `schema.md` 11절 예시 세 항목 그대로.
VIOLATION = Finding(
    path="login.json > plan[0] > login-flow",
    node="detectButtons",
    status="violation",
    rule_id="expectedCount",
    message="버튼 3개 기대, 2개 관측",
)
NOT_RUN = Finding(
    path="login.json > plan[0] > login-flow",
    node="checkToken",
    status="not_run",
    cause=NotRunCause(node="captureHtml", reason="state_unreachable"),
)
ERROR = Finding(
    path="login.json > plan[1] > menu-check",
    node="detectMenu",
    status="error",
    rule_id="STR-CONTRACT-001",
    message="`Args` dataclass 가 선언돼 있지 않습니다.",
)


def test_build_report_counts_four_states() -> None:
    passed = Finding(status="pass", node="a")
    report = build_report([passed, VIOLATION, NOT_RUN, ERROR, VIOLATION])
    assert report.summary.passed == 1
    assert report.summary.violation == 2
    assert report.summary.not_run == 1
    assert report.summary.error == 1
    assert len(report.results) == 5


def test_build_report_empty() -> None:
    report = build_report([])
    assert report.summary.model_dump() == {
        "passed": 0,
        "violation": 0,
        "not_run": 0,
        "error": 0,
    }
    assert report.results == []


def test_summary_counts_survive_at_zero() -> None:
    """4상태 카운트는 `0` 이어도 생략하지 않는다."""
    data = json.loads(render_json(build_report([])))
    assert data["summary"] == {"pass": 0, "violation": 0, "not_run": 0, "error": 0}


def test_render_json_key_sets_match_schema_example() -> None:
    """`schema.md` 11절 예시와 **키 구성까지** 일치해야 한다."""
    data = json.loads(render_json(build_report([VIOLATION, NOT_RUN, ERROR])))
    violation, not_run, error = data["results"]

    assert set(violation) == {"path", "node", "status", "rule", "message"}
    assert set(not_run) == {"path", "node", "status", "cause"}
    assert set(error) == {"path", "node", "status", "rule", "message"}


def test_render_json_no_null_cause_and_no_empty_strings() -> None:
    text = render_json(build_report([VIOLATION, NOT_RUN, ERROR]))
    assert '"cause": null' not in text
    assert '"rule": ""' not in text
    assert '"message": ""' not in text
    assert '"path": ""' not in text
    assert '"node": ""' not in text


def test_render_json_uses_aliases() -> None:
    data = json.loads(render_json(build_report([VIOLATION])))
    assert "pass" in data["summary"]
    assert "passed" not in data["summary"]
    assert data["results"][0]["rule"] == "expectedCount"
    assert "rule_id" not in data["results"][0]


def test_render_json_values_match_schema_example() -> None:
    data = json.loads(render_json(build_report([VIOLATION, NOT_RUN, ERROR])))
    assert data["results"][0] == {
        "path": "login.json > plan[0] > login-flow",
        "node": "detectButtons",
        "status": "violation",
        "rule": "expectedCount",
        "message": "버튼 3개 기대, 2개 관측",
    }
    assert data["results"][1]["cause"] == {
        "node": "captureHtml",
        "reason": "state_unreachable",
    }


def test_render_json_is_flat_not_nested() -> None:
    """Spec→plan→pipeline→node 중첩으로 쌓지 않는다."""
    data = json.loads(render_json(build_report([VIOLATION, NOT_RUN])))
    assert set(data) == {"summary", "results"}
    assert isinstance(data["results"], list)
    assert all(isinstance(entry["path"], str) for entry in data["results"])


def test_render_text_shows_all_four_states() -> None:
    passed = Finding(status="pass", node="detectMenu")
    text = render_text(build_report([passed, VIOLATION, NOT_RUN, ERROR]))
    assert "pass 1" in text
    assert "violation 1" in text
    assert "not_run 1" in text
    assert "error 1" in text
    assert "[violation]" in text
    assert "[not_run]" in text
    assert "[error]" in text
    assert "captureHtml (state_unreachable)" in text
    assert "detectButtons" in text


def test_build_compare_report_all_same() -> None:
    report = build_compare_report(
        {"detectButtons": {"legacy": 3, "v2": 3, "v3": 3, "canary": 3}}
    )
    assert report.root["detectButtons"].same is True


def test_build_compare_report_one_differs_is_violation() -> None:
    """짝지어 비교가 아니라 목록 전부가 한 값이냐를 묻는다. 하나만 어긋나도 위반."""
    report = build_compare_report(
        {"detectButtons": {"legacy": 3, "v2": 3, "v3": 2, "canary": 3}}
    )
    entry = report.root["detectButtons"]
    assert entry.same is False
    assert entry.values == {"legacy": 3, "v2": 3, "v3": 2, "canary": 3}


def test_build_compare_report_uses_plain_equality() -> None:
    """엔진은 `==` 만 안다 — 허용 오차도 무시 필드도 없다."""
    report = build_compare_report(
        {
            "coords": {"a": [1.0, 2.0], "b": [1.0, 2.0]},
            "coords2": {"a": [1.0, 2.0], "b": [1.0, 2.000001]},
        }
    )
    assert report.root["coords"].same is True
    assert report.root["coords2"].same is False


def test_build_compare_report_multiple_nodes() -> None:
    report = build_compare_report(
        {
            "detectButtons": {"legacy": 3, "v2": 3},
            "extractMenu": {"legacy": ["a"], "v2": ["b"]},
        }
    )
    assert set(report.root) == {"detectButtons", "extractMenu"}
    assert report.root["detectButtons"].same is True
    assert report.root["extractMenu"].same is False


def test_compare_report_shape_matches_schema_example() -> None:
    report = build_compare_report(
        {"detectButtons": {"legacy": 3, "v2": 3, "v3": 2, "canary": 3}}
    )
    assert report.model_dump() == {
        "detectButtons": {
            "same": False,
            "values": {"legacy": 3, "v2": 3, "v3": 2, "canary": 3},
        }
    }


def test_write_compare_report(tmp_path: Path) -> None:
    report = build_compare_report({"detectButtons": {"legacy": 3, "v2": 2}})
    out = tmp_path / "nested" / "compare.json"
    write_compare_report(report, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == {
        "detectButtons": {"same": False, "values": {"legacy": 3, "v2": 2}}
    }


def test_compare_report_does_not_mix_with_value_report() -> None:
    """값 검증은 노드별 판정, 비교는 노드별 대상 간 대조 — 필드가 안 겹친다."""
    value_json = json.loads(render_json(build_report([VIOLATION])))
    compare = build_compare_report({"detectButtons": {"legacy": 3, "v2": 2}})
    compare_json = compare.model_dump()

    assert "summary" not in compare_json
    assert "results" not in compare_json
    assert "same" not in value_json
    assert "values" not in value_json
    # 비교 리포트는 값 검증 `Finding` 어휘를 하나도 갖지 않는다.
    entry = compare_json["detectButtons"]
    assert set(entry) == {"same", "values"}
    assert not {"status", "rule", "message", "cause"} & set(entry)


def test_report_and_compare_report_are_distinct_types() -> None:
    assert not isinstance(build_compare_report({}), Report)
    assert isinstance(build_compare_report({}), CompareReport)
    assert isinstance(build_report([]), Report)
    assert isinstance(build_report([]).summary, Summary)
    assert isinstance(
        build_compare_report({"n": {"a": 1, "b": 1}}).root["n"], CompareEntry
    )
