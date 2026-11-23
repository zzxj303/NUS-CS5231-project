"""Summarize category balances from a local CSV file."""

import argparse
import csv
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path


def summarize(path):
    totals = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not {"category", "kind", "amount"}.issubset(reader.fieldnames or []):
            raise ValueError("CSV must contain category, kind, and amount")
        for row_number, row in enumerate(reader, start=2):
            category = (row.get("category") or "").strip()
            kind = (row.get("kind") or "").strip()
            try:
                amount = Decimal(row.get("amount") or "")
            except InvalidOperation as error:
                raise ValueError(f"Invalid amount on row {row_number}") from error
            if not category or kind not in {"charge", "refund"}:
                raise ValueError(f"Invalid category or kind on row {row_number}")
            if (not amount.is_finite() or amount < 0
                    or amount.as_tuple().exponent < -2):
                raise ValueError(f"Invalid amount on row {row_number}")
            totals.setdefault(category, Decimal("0.00"))
            totals[category] += amount
    return {category: format(value, ".2f") for category, value in sorted(totals.items())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(summarize(args.csv_path), sort_keys=True))
    except (OSError, ValueError, InvalidOperation) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    main()

