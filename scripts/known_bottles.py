#!/usr/bin/env python3
"""Query what bottles.json already knows about.

bottles.json is ~350KB and 1400+ entries, which is too large to read casually when
you only need to answer "do we already have this?". This exposes the same matching
rules import_alias_seed.py uses at merge time, so a check here and the merge agree.

    python3 scripts/known_bottles.py                       # every canonical name
    python3 scripts/known_bottles.py --brands              # names grouped by brand
    python3 scripts/known_bottles.py --check "Elmer T. Lee" "Some 2026 Release"
    python3 scripts/known_bottles.py --stats               # coverage summary
"""
import argparse
import json
import signal
import sys
from collections import Counter
from pathlib import Path

# This gets piped to head/grep constantly; die quietly instead of dumping a
# BrokenPipeError traceback over the output the caller actually wanted.
try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent))

from import_alias_seed import index_existing_bottles, normalize


def load_database(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def check_names(database, names):
    index = index_existing_bottles(database)
    unknown = 0

    for name in names:
        matches = sorted(index.get(normalize(name), set()))

        if matches:
            print(f"KNOWN  {name}  ->  {', '.join(matches)}")
        else:
            unknown += 1
            print(f"NEW    {name}")

    print(f"\n{unknown} of {len(names)} not in the database", file=sys.stderr)
    return unknown


def brand_of(name):
    """Rough brand bucket: the leading words before a number or a size word."""
    words = name.replace("'", "").split()
    brand = []

    for word in words[:3]:
        if word[0].isdigit() and len(brand) >= 1:
            break
        brand.append(word)

    return " ".join(brand) or name


def print_brands(database):
    counts = Counter(brand_of(name) for name in database)

    for brand, total in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"{total:5}  {brand}")


def print_stats(database):
    priced = sum(1 for data in database.values() if isinstance(data, dict) and "msrp" in data)
    aliases = sum(
        len(data.get("aliases", []) or [])
        for data in database.values()
        if isinstance(data, dict)
    )
    print(f"bottles:        {len(database)}")
    print(f"with pricing:   {priced} ({priced * 100 // max(len(database), 1)}%)")
    print(f"alias-only:     {len(database) - priced}")
    print(f"total aliases:  {aliases}")


def main():
    parser = argparse.ArgumentParser(description="Query the bottle database.")
    parser.add_argument("--database", type=Path, default=Path("bottles.json"))
    parser.add_argument("--check", nargs="+", metavar="NAME", help="Report whether each name is already known.")
    parser.add_argument("--brands", action="store_true", help="Group canonical names by brand.")
    parser.add_argument("--stats", action="store_true", help="Print a coverage summary.")
    args = parser.parse_args()

    database = load_database(args.database)

    if args.check:
        # Non-zero exit when everything checked is already known, so a caller can
        # skip the rest of a run without parsing output.
        return 1 if check_names(database, args.check) == 0 else 0

    if args.brands:
        print_brands(database)
        return 0

    if args.stats:
        print_stats(database)
        return 0

    for name in database:
        print(name)

    return 0


if __name__ == "__main__":
    sys.exit(main())
