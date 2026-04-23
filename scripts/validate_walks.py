"""Validate every walks/*.json against schema/walk.schema.json.

Also checks cross-file invariants that a per-file schema can't enforce:
  - IDs are unique and dense (1..N with no gaps)
  - Slugs are unique
  - Filename matches {id:03d}-{slug}.json

Exit code: 0 on success, 1 on any validation failure. Suitable for CI.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import jsonschema

HERE   = Path(__file__).resolve().parent.parent
SCHEMA = HERE / "schema" / "walk.schema.json"
WALKS  = HERE / "walks"


def pick_validator(schema: dict):
    """Prefer Draft 2020-12; fall back to Draft-07 if jsonschema is older.
    Our schema uses no features unique to 2020-12, so Draft-07 is safe."""
    Draft202012 = getattr(jsonschema, "Draft202012Validator", None)
    if Draft202012 is not None:
        return Draft202012(schema)
    return jsonschema.Draft7Validator(schema)


def main() -> int:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = pick_validator(schema)

    files = sorted(WALKS.glob("*.json"))
    if not files:
        print(f"ERROR: no JSONs in {WALKS}", file=sys.stderr)
        return 1

    errors = 0
    ids: dict[int, str] = {}
    slugs: dict[str, str] = {}

    for path in files:
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[{path.name}] JSON parse error: {e}", file=sys.stderr)
            errors += 1
            continue

        for err in validator.iter_errors(rec):
            loc = "/".join(str(p) for p in err.absolute_path) or "(root)"
            print(f"[{path.name}] {loc}: {err.message}", file=sys.stderr)
            errors += 1

        wid = rec.get("id")
        slug = rec.get("slug")
        if wid in ids:
            print(f"[{path.name}] duplicate id {wid} (also in {ids[wid]})", file=sys.stderr)
            errors += 1
        elif wid is not None:
            ids[wid] = path.name
        if slug in slugs:
            print(f"[{path.name}] duplicate slug {slug!r} (also in {slugs[slug]})", file=sys.stderr)
            errors += 1
        elif slug:
            slugs[slug] = path.name

        expected = f"{wid:03d}-{slug}.json" if wid and slug else None
        if expected and path.name != expected:
            print(f"[{path.name}] filename should be {expected}", file=sys.stderr)
            errors += 1

    # Density check: IDs should be 1..N
    if ids:
        expected_ids = set(range(1, max(ids) + 1))
        missing = expected_ids - ids.keys()
        if missing:
            print(f"Missing IDs in sequence: {sorted(missing)}", file=sys.stderr)
            errors += 1

    if errors:
        print(f"\nFAIL: {errors} error(s) across {len(files)} walks", file=sys.stderr)
        return 1
    print(f"OK: {len(files)} walks valid (ids 1..{max(ids)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
