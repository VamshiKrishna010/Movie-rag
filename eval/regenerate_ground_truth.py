"""Regenerate anchor-backed retrieval labels from the local movie catalog.

Run from the project root:

    python -m eval.regenerate_ground_truth
    python -m eval.regenerate_ground_truth --write
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence
import unicodedata

import psycopg
from psycopg.rows import dict_row

from app.config import settings


HERE = Path(__file__).parent
DATASET_PATH = HERE / "dataset.json"
SUPPORTED_ROLES = {"actor", "director", "writer"}


@dataclass(frozen=True)
class GroundTruthResult:
    titles: list[str]
    matched_people: list[str]
    warnings: list[str]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Regenerate dataset ground_truth_movies for supported _anchor entries.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DATASET_PATH,
        help=f"dataset path (default: {DATASET_PATH})",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="write regenerated labels back to the dataset file",
    )
    return parser


def normalize_person_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    simplified = re.sub(r"[^a-zA-Z0-9]+", " ", ascii_name)
    return " ".join(simplified.casefold().split())


def load_dataset(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as dataset_file:
        dataset = json.load(dataset_file)
    items = dataset.get("items")
    if not isinstance(items, list):
        raise ValueError(f"{path} must contain an 'items' list")
    return dataset


def load_people_index(conn: psycopg.Connection) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, name FROM people ORDER BY name, id")
        for row in cur.fetchall():
            index[normalize_person_name(row["name"])].append(row)
    return dict(index)


def resolve_person_ids(
    people_index: dict[str, list[dict[str, Any]]],
    person: str,
) -> tuple[list[int], list[str], list[str]]:
    matches = people_index.get(normalize_person_name(person), [])
    if not matches:
        return [], [], [f"no catalog person matched {person!r}"]

    ids = [int(match["id"]) for match in matches]
    names = [str(match["name"]) for match in matches]
    warnings = []
    if len(matches) > 1:
        warnings.append(
            f"{person!r} matched {len(matches)} people: {', '.join(names)}"
        )
    return ids, names, warnings


def _titles_for_predicates(
    conn: psycopg.Connection,
    predicates: Sequence[tuple[list[int], str]],
) -> list[str]:
    exists_clauses = []
    params: dict[str, Any] = {}
    for index, (person_ids, role) in enumerate(predicates):
        ids_key = f"person_ids_{index}"
        role_key = f"role_{index}"
        exists_clauses.append(
            f"""
            EXISTS (
                SELECT 1
                FROM movie_people mp{index}
                WHERE mp{index}.movie_id = m.id
                  AND mp{index}.person_id = ANY(%({ids_key})s)
                  AND mp{index}.role = %({role_key})s
            )
            """
        )
        params[ids_key] = person_ids
        params[role_key] = role

    sql = f"""
        SELECT
            m.title,
            MIN(m.release_year) AS sort_year,
            MIN(m.id) AS sort_id
        FROM movies m
        WHERE {" AND ".join(exists_clauses)}
        GROUP BY m.title
        ORDER BY sort_year NULLS LAST, m.title, sort_id
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [str(row["title"]) for row in cur.fetchall()]


def _unsupported_roles(roles: Sequence[str]) -> list[str]:
    return sorted({role for role in roles if role not in SUPPORTED_ROLES})


def labels_for_anchor(
    conn: psycopg.Connection,
    people_index: dict[str, list[dict[str, Any]]],
    anchor: dict[str, Any],
) -> GroundTruthResult:
    warnings: list[str] = []
    matched_people: list[str] = []

    if "person" in anchor and isinstance(anchor.get("role"), str):
        roles = [anchor["role"]]
        unsupported = _unsupported_roles(roles)
        if unsupported:
            return GroundTruthResult(
                titles=[],
                matched_people=[],
                warnings=[f"unsupported role(s): {', '.join(unsupported)}"],
            )
        person_ids, names, person_warnings = resolve_person_ids(
            people_index,
            str(anchor["person"]),
        )
        warnings.extend(person_warnings)
        matched_people.extend(names)
        if not person_ids:
            return GroundTruthResult([], matched_people, warnings)
        titles = _titles_for_predicates(conn, [(person_ids, roles[0])])
        return GroundTruthResult(titles, matched_people, warnings)

    if anchor.get("intersection") and isinstance(anchor.get("people"), list):
        people = [str(person) for person in anchor["people"]]
        if isinstance(anchor.get("role"), str):
            roles = [str(anchor["role"])] * len(people)
        elif isinstance(anchor.get("roles"), list):
            roles = [str(role) for role in anchor["roles"]]
        else:
            return GroundTruthResult([], [], ["intersection anchor needs role or roles"])

        if len(people) != len(roles):
            return GroundTruthResult([], [], ["people and roles length mismatch"])

        unsupported = _unsupported_roles(roles)
        if unsupported:
            return GroundTruthResult(
                titles=[],
                matched_people=[],
                warnings=[f"unsupported role(s): {', '.join(unsupported)}"],
            )

        predicates: list[tuple[list[int], str]] = []
        for person, role in zip(people, roles, strict=True):
            person_ids, names, person_warnings = resolve_person_ids(
                people_index,
                person,
            )
            warnings.extend(person_warnings)
            matched_people.extend(names)
            if not person_ids:
                return GroundTruthResult([], matched_people, warnings)
            predicates.append((person_ids, role))

        titles = _titles_for_predicates(conn, predicates)
        return GroundTruthResult(titles, matched_people, warnings)

    return GroundTruthResult([], [], ["unsupported anchor shape"])


def regenerate(dataset: dict[str, Any], conn: psycopg.Connection) -> dict[str, Any]:
    people_index = load_people_index(conn)
    summary = {
        "anchors": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "empty": 0,
        "warnings": [],
    }

    for item in dataset["items"]:
        anchor = item.get("_anchor")
        if not isinstance(anchor, dict):
            continue

        summary["anchors"] += 1
        result = labels_for_anchor(conn, people_index, anchor)
        item_id = item.get("id", "<missing id>")
        for warning in result.warnings:
            summary["warnings"].append(f"{item_id}: {warning}")

        if not result.titles:
            summary["skipped"] += 1
            summary["empty"] += 1
            continue

        if item.get("ground_truth_movies") == result.titles:
            summary["unchanged"] += 1
            continue

        item["ground_truth_movies"] = result.titles
        summary["updated"] += 1

    dataset["_ground_truth_regeneration"] = {
        "source": "local movies/movie_people/people tables",
        "supported_roles": sorted(SUPPORTED_ROLES),
        "anchors_seen": summary["anchors"],
        "anchors_updated": summary["updated"],
        "anchors_unchanged": summary["unchanged"],
        "anchors_skipped": summary["skipped"],
    }
    dataset["_regeneration_summary"] = summary
    return summary


def write_dataset(path: Path, dataset: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(dataset, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        dataset = load_dataset(args.dataset)
        with psycopg.connect(settings.database_url) as conn:
            summary = regenerate(dataset, conn)
        if args.write:
            dataset.pop("_regeneration_summary", None)
            write_dataset(args.dataset, dataset)

        action = "Wrote" if args.write else "Dry run"
        print(f"{action}: {args.dataset}")
        print(
            "anchors={anchors} updated={updated} unchanged={unchanged} "
            "skipped={skipped} empty={empty}".format(**summary)
        )
        if summary["warnings"]:
            print("\nWarnings:")
            for warning in summary["warnings"]:
                print(f"- {warning}")
        if not args.write:
            print("\nRun again with --write to update the dataset.")
    except (OSError, ValueError, psycopg.Error, json.JSONDecodeError) as exc:
        print(f"ground-truth regeneration failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
