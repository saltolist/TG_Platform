"""Build the frozen v13 qualification cohort before any provider replay."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "tests/fixtures/agent_unified_phase6"
SOURCE = ROOT / "v12/qualification_selector_cohort_v4.json"
OUTPUT = ROOT / "v13/qualification_selector_cohort_v5.json"

REPLACEMENTS = {
    "Aster": "Atlas",
    "Beryl": "Beacon",
    "Copper": "Cedar",
    "Delta": "Dune",
    "Echo": "Elm",
    "Flint": "Frost",
    "Gale": "Glint",
    "Hearth": "Harbor",
    "Iris": "Ion",
    "Jasper": "Juno",
    "Kestrel": "Kite",
    "Lotus": "Lattice",
    "Mica": "Mosaic",
    "Nectar": "Nimbus",
    "Osprey": "Orion",
    "Piper": "Prism",
    "Quill": "Quest",
    "River": "Rowan",
    "Sierra": "Summit",
    "Thistle": "Tempo",
    "Ulster": "Unity",
    "Vega": "Vale",
    "Wren": "Willow",
    "Виктор": "Максим",
    "Елена": "Ирина",
    "04:05": "05:10",
    "04:31": "05:44",
    "23 минуты": "29 минут",
    "06:40": "07:25",
    "03:20": "02:50",
    "14:05": "15:20",
    "10:15": "11:05",
    "five hours": "six hours",
    "22:40": "21:50",
    "845 ms": "910 ms",
    "560 ms": "605 ms",
    "135 возвратов": "160 возвратов",
    "52 суток": "61 суток",
    "675 rps": "710 rps",
    "805 rps": "860 rps",
    "610 rps": "645 rps",
    "24 mars": "11 avril",
    "68 pour cent": "74 pour cent",
    "vingt-sept minutes": "trente-et-une minutes",
    "sei zone": "sette zone",
    "quattro zone": "cinque zone",
    "735 GB": "790 GB",
    "735 ГБ": "790 ГБ",
    "455 GB": "490 GB",
    "eu-central": "ap-south",
}


def replace_strings(value: object) -> object:
    if isinstance(value, str):
        result = value
        for source, target in REPLACEMENTS.items():
            result = result.replace(source, target).replace(
                source.casefold(), target.casefold()
            )
        result = result.replace("fixture-t", "fixture-u")
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


def main() -> None:
    payload = replace_strings(json.loads(SOURCE.read_text(encoding="utf-8")))
    assert isinstance(payload, dict)
    payload["version"] = "2026-07-29-semantic-qualification-v5"
    payload["qualification_status"] = "untouched"
    for case in payload["cases"]:
        case["id"] = replace_id_prefix(case["id"], source="t", target="u")
    for scenario in payload["scenarios"]:
        scenario["id"] = replace_id_prefix(
            scenario["id"], source="t", target="u"
        )
        scenario["candidate_ids"] = [
            replace_id_prefix(item, source="t", target="u")
            for item in scenario["candidate_ids"]
        ]

    cross_record = next(
        item for item in payload["scenarios"] if item["id"] == "u15-cross-record-en"
    )
    cross_record["query"] = "And did the signed version keep that choice?"
    cross_record["dialog_context"] = (
        "User: Compare the recovery region in the Cedar draft with the signed Cedar policy, "
        "not the Nimbus inventory. Assistant: Cedar is the active comparison."
    )
    cross_record["planner_expectation"] = {
        "call_type": "read",
        "dialog_resolution_required": True,
        "required_query_term_groups": [
            ["cedar"],
            ["draft", "proposed"],
            ["signed", "final"],
            ["region", "recovery"],
        ],
        "forbidden_query_terms": ["nimbus"],
    }

    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    scenarios = payload["scenarios"]
    assert len(scenarios) == 20
    assert sum(len(item["critical_required_refs"]) for item in scenarios) == 21
    assert sum(len(item["irrelevant_refs"]) for item in scenarios) == 20
    assert sum("simple" in item["id"] for item in scenarios) >= 5
    assert sum(bool(item.get("planner_expectation")) for item in scenarios) >= 4
    assert not any(name.casefold() in serialized.casefold() for name in REPLACEMENTS)
    validate_references(payload)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(serialized, encoding="utf-8")


if __name__ == "__main__":
    main()
