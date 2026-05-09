#!/usr/bin/env python3
import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path


def normalize(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def as_alias_list(value):
    if value is None:
        return []

    if isinstance(value, str):
        return [value.strip()] if value.strip() else []

    if isinstance(value, list):
        aliases = []

        for item in value:
            if isinstance(item, str) and item.strip():
                aliases.append(item.strip())

        return aliases

    return []


def dedupe_aliases(aliases):
    deduped = []
    seen = set()

    for alias in aliases:
        normalized = normalize(alias)

        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        deduped.append(alias)

    return deduped


def bottle_aliases(record):
    aliases = as_alias_list(record.get("aliases"))
    aliases.extend(as_alias_list(record.get("alias")))
    return aliases


def index_existing_bottles(database):
    index = {}

    for bottle_name, record in database.items():
        identifiers = [bottle_name]

        if isinstance(record, dict):
            identifiers.append(record.get("name"))
            identifiers.extend(bottle_aliases(record))

        for identifier in identifiers:
            normalized = normalize(identifier)

            if normalized:
                index.setdefault(normalized, set()).add(bottle_name)

    return index


def load_seed(path):
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, dict) and isinstance(payload.get("bottles"), list):
        return payload["bottles"]

    if isinstance(payload, list):
        return payload

    raise ValueError("Seed file must be a list or an object with a bottles list.")


def merge_alias_seed(database_path, seed_path, backup_dir):
    with database_path.open("r", encoding="utf-8") as f:
        database = json.load(f)

    seed_entries = load_seed(seed_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{database_path.name}.{timestamp}.bak"
    shutil.copy2(database_path, backup_path)

    existing_index = index_existing_bottles(database)
    created_count = 0
    updated_alias_count = 0
    skipped_count = 0
    possible_duplicate_count = 0

    for entry in seed_entries:
        if not isinstance(entry, dict):
            skipped_count += 1
            continue

        imported_name = str(entry.get("name") or "").strip()
        imported_aliases = dedupe_aliases(as_alias_list(entry.get("aliases")) + as_alias_list(entry.get("alias")))

        if not imported_name:
            skipped_count += 1
            continue

        identifiers = [imported_name, *imported_aliases]
        matches = set()

        for identifier in identifiers:
            matches.update(existing_index.get(normalize(identifier), set()))

        if len(matches) > 1:
            possible_duplicate_count += 1
            skipped_count += 1
            continue

        if len(matches) == 1:
            bottle_key = next(iter(matches))
            record = database[bottle_key]

            if not isinstance(record, dict):
                skipped_count += 1
                continue

            existing_aliases = bottle_aliases(record)
            existing_alias_norms = {normalize(alias) for alias in existing_aliases}
            new_aliases = [
                alias
                for alias in imported_aliases
                if normalize(alias) and normalize(alias) not in existing_alias_norms
            ]

            if new_aliases:
                # Preserve every existing alias spelling exactly as-is. The seed file is
                # supplemental only, so existing aliases are never removed during merge.
                record["aliases"] = as_alias_list(record.get("aliases")) + new_aliases
                updated_alias_count += len(new_aliases)

                for alias in new_aliases:
                    existing_index.setdefault(normalize(alias), set()).add(bottle_key)
            else:
                skipped_count += 1

            continue

        minimal_key = imported_name
        suffix = 2

        while minimal_key in database:
            minimal_key = f"{imported_name} ({suffix})"
            suffix += 1

        database[minimal_key] = {
            "name": imported_name,
            "aliases": imported_aliases,
        }
        created_count += 1

        for identifier in [minimal_key, imported_name, *imported_aliases]:
            existing_index.setdefault(normalize(identifier), set()).add(minimal_key)

    with database_path.open("w", encoding="utf-8") as f:
        json.dump(database, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return {
        "backup_path": str(backup_path),
        "created_count": created_count,
        "updated_alias_count": updated_alias_count,
        "skipped_count": skipped_count,
        "possible_duplicate_count": possible_duplicate_count,
    }


def main():
    parser = argparse.ArgumentParser(description="Merge a supplemental bottle alias seed into bottles.json.")
    parser.add_argument("seed_file", type=Path)
    parser.add_argument("--database", type=Path, default=Path("bottles.json"))
    parser.add_argument("--backup-dir", type=Path, default=Path("backups"))
    args = parser.parse_args()

    result = merge_alias_seed(args.database, args.seed_file, args.backup_dir)

    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
