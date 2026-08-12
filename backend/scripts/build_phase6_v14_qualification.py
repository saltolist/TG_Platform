"""Build the frozen v14 qualification cohort before any provider replay."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "tests/fixtures/agent_unified_phase6"
SOURCE = ROOT / "v13/qualification_selector_cohort_v5.json"
OUTPUT = ROOT / "v14/qualification_selector_cohort_v6.json"

REPLACEMENTS = {
    "Atlas": "Arbor",
    "Beacon": "Bastion",
    "Cedar": "Cipher",
    "Dune": "Dahlia",
    "Elm": "Eon",
    "Frost": "Forge",
    "Glint": "Garnet",
    "Harbor": "Helix",
    "Ion": "Ivory",
    "Juno": "Jade",
    "Kite": "Kernel",
    "Lattice": "Lyric",
    "Mosaic": "Matrix",
    "Nimbus": "Nova",
    "Orion": "Onyx",
    "Prism": "Pulse",
    "Quest": "Quasar",
    "Rowan": "Raven",
    "Summit": "Solstice",
    "Tempo": "Tangent",
    "Unity": "Umbra",
    "Vale": "Vertex",
    "Willow": "Wave",
    "Максим": "Антон",
    "Ирина": "Ольга",
    "05:10": "06:15",
    "05:44": "06:52",
    "29 минут": "34 минуты",
    "07:25": "08:10",
    "02:50": "03:35",
    "15:20": "16:10",
    "11:05": "11:50",
    "six hours": "seven hours",
    "21:50": "20:45",
    "910 ms": "975 ms",
    "605 ms": "640 ms",
    "160 возвратов": "185 возвратов",
    "61 суток": "67 суток",
    "710 rps": "745 rps",
    "860 rps": "890 rps",
    "645 rps": "680 rps",
    "11 avril": "19 mai",
    "74 pour cent": "79 pour cent",
    "trente-et-une minutes": "trente-six minutes",
    "sette zone": "otto zone",
    "cinque zone": "sei zone",
    "790 GB": "840 GB",
    "790 ГБ": "840 ГБ",
    "490 GB": "525 GB",
    "ap-south": "ca-central",
}


def replace_strings(value: object) -> object:
    if isinstance(value, str):
        result = value
        for source, target in REPLACEMENTS.items():
            if source == "Ion":
                result = re.sub(r"\bIon\b", target, result)
                continue
            result = result.replace(source, target).replace(
                source.casefold(), target.casefold()
            )
        result = result.replace("fixture-u", "fixture-v")
        return result
    if isinstance(value, list):
        return [replace_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: replace_strings(item) for key, item in value.items()}
    return value


def replace_id_prefix(value: object, *, source: str, target: str) -> str:
    identifier = str(value)
    if not identifier.startswith(source):
        raise ValueError(f"expected {source!r} prefix in {identifier!r}")
    return target + identifier[len(source) :]


def validate_references(payload: dict[str, object]) -> None:
    cases = payload["cases"]
    scenarios = payload["scenarios"]
    assert isinstance(cases, list)
    assert isinstance(scenarios, list)
    case_by_id = {str(item["id"]): item for item in cases}
    assert len(case_by_id) == len(cases)
    assert len({str(item["id"]) for item in scenarios}) == len(scenarios)

    for scenario in scenarios:
        candidate_ids = [str(item) for item in scenario["candidate_ids"]]
        assert len(candidate_ids) == len(set(candidate_ids))
        assert set(candidate_ids) <= set(case_by_id)
        expected_refs = {
            f"{case_by_id[candidate_id]['kind']}:fixture-{candidate_id}"
            for candidate_id in candidate_ids
        }
        labeled_refs = {
            str(ref)
            for key in (
                "required_refs",
                "critical_required_refs",
                "allowed_supporting_refs",
                "irrelevant_refs",
            )
            for ref in scenario[key]
        }
        assert labeled_refs <= expected_refs


def validate_cross_record_referent(payload: dict[str, object]) -> None:
    cases = {str(item["id"]): item for item in payload["cases"]}
    scenario = next(
        item
        for item in payload["scenarios"]
        if item["id"] == "v15-cross-record-en"
    )
    assert "raven" in str(scenario["dialog_context"]).casefold()
    assert "inventory" in str(scenario["dialog_context"]).casefold()
    required_ids = {ref.rsplit("-", 1)[-1] for ref in scenario["required_refs"]}
    required_cases = [
        case for case_id, case in cases.items() if case_id.rsplit("-", 1)[-1] in required_ids
    ]
    assert len(required_cases) == 2
    assert all(
        "raven" in f"{case['title']} {case['selector_summary']}".casefold()
        for case in required_cases
    )


def main() -> None:
    payload = replace_strings(json.loads(SOURCE.read_text(encoding="utf-8")))
    assert isinstance(payload, dict)
    payload["version"] = "2026-07-29-semantic-qualification-v6"
    payload["qualification_status"] = "untouched"
    for case in payload["cases"]:
        case["id"] = replace_id_prefix(case["id"], source="u", target="v")
    for scenario in payload["scenarios"]:
        scenario["id"] = replace_id_prefix(
            scenario["id"], source="u", target="v"
        )
        scenario["candidate_ids"] = [
            replace_id_prefix(item, source="u", target="v")
            for item in scenario["candidate_ids"]
        ]

    cross_record = next(
        item for item in payload["scenarios"] if item["id"] == "v15-cross-record-en"
    )
    cross_record["query"] = "And did the signed version keep that choice?"
    cross_record["dialog_context"] = (
        "User: Compare the recovery region in the Raven draft with the signed Raven policy. "
        "The inventory only lists options and is out of scope. Assistant: Raven is the active comparison."
    )
    cross_record["planner_expectation"] = {
        "call_type": "read",
        "dialog_resolution_required": True,
        "required_query_term_groups": [
            ["raven"],
            ["draft", "proposed"],
            ["signed", "final"],
            ["region", "recovery"],
        ],
        "forbidden_query_terms": ["inventory"],
    }

    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    scenarios = payload["scenarios"]
    assert len(scenarios) == 20
    assert sum(len(item["critical_required_refs"]) for item in scenarios) == 21
    assert sum(len(item["irrelevant_refs"]) for item in scenarios) == 20
    assert sum("simple" in item["id"] for item in scenarios) >= 5
    assert sum(bool(item.get("planner_expectation")) for item in scenarios) == 4
    assert not any(
        re.search(rf"(?<!\w){re.escape(name)}(?!\w)", serialized, re.IGNORECASE)
        for name in REPLACEMENTS
    )
    validate_references(payload)
    validate_cross_record_referent(payload)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(serialized, encoding="utf-8")


if __name__ == "__main__":
    main()
