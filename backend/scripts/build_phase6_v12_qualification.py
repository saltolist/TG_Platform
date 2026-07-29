"""Build the frozen v12 qualification cohort before any provider replay."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "tests/fixtures/agent_unified_phase6"
SOURCE = ROOT / "v11/qualification_selector_cohort_v3.json"
OUTPUT = ROOT / "v12/qualification_selector_cohort_v4.json"

REPLACEMENTS = {
    "Amber": "Aster",
    "Birch": "Beryl",
    "Cobalt": "Copper",
    "Drift": "Delta",
    "Ember": "Echo",
    "Fjord": "Flint",
    "Grove": "Gale",
    "Halo": "Hearth",
    "Islet": "Iris",
    "Juniper": "Jasper",
    "Keystone": "Kestrel",
    "Lantern": "Lotus",
    "Meridian": "Mica",
    "Northstar": "Nectar",
    "Opal": "Osprey",
    "Pollen": "Piper",
    "Quartz": "Quill",
    "Rill": "River",
    "Solace": "Sierra",
    "Tundra": "Thistle",
    "Umber": "Ulster",
    "Violet": "Vega",
    "Wisp": "Wren",
    "02:15": "04:05",
    "02:42": "04:31",
    "18 минут": "23 минуты",
    "13:10": "14:05",
    "09:30": "10:15",
    "four hours": "five hours",
    "23:00": "22:40",
    "780 ms": "845 ms",
    "510 ms": "560 ms",
    "90 возвратов": "135 возвратов",
    "45 суток": "52 суток",
    "620 rps": "675 rps",
    "760 rps": "805 rps",
    "580 rps": "610 rps",
    "17 fevrier": "24 mars",
    "72 pour cent": "68 pour cent",
    "trente-deux minutes": "vingt-sept minutes",
    "cinque zone": "sei zone",
    "tre zone": "quattro zone",
    "680 GB": "735 GB",
    "680 ГБ": "735 ГБ",
    "410 GB": "455 GB",
}


def replace_strings(value: object) -> object:
    if isinstance(value, str):
        result = value
        for source, target in REPLACEMENTS.items():
            result = result.replace(source, target).replace(source.casefold(), target.casefold())
        result = result.replace("fixture-s", "fixture-t")
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
    scenario_ids = {str(item["id"]) for item in scenarios}
    assert len(scenario_ids) == len(scenarios)

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
    payload["version"] = "2026-07-29-semantic-qualification-v4"
    payload["qualification_status"] = "untouched"
    for case in payload["cases"]:
        case["id"] = replace_id_prefix(case["id"], source="s", target="t")
    for scenario in payload["scenarios"]:
        scenario["id"] = replace_id_prefix(scenario["id"], source="s", target="t")
        scenario["candidate_ids"] = [
            replace_id_prefix(item, source="s", target="t")
            for item in scenario["candidate_ids"]
        ]
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    assert len(payload["scenarios"]) == 20
    assert sum(len(item["critical_required_refs"]) for item in payload["scenarios"]) >= 20
    assert sum(len(item["irrelevant_refs"]) for item in payload["scenarios"]) >= 20
    assert not any(name.casefold() in serialized.casefold() for name in REPLACEMENTS)
    validate_references(payload)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(serialized, encoding="utf-8")


if __name__ == "__main__":
    main()
