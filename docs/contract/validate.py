#!/usr/bin/env python3
"""Validate term-bank entries against the frozen contract shape.

Usage: python docs/contract/validate.py <entry.json | dir-of-json ...>
Exits non-zero if any entry fails. Requires jsonschema>=4 (2020-12 support).
"""
import json, sys, glob, os
from jsonschema.validators import Draft202012Validator

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = json.load(open(os.path.join(HERE, "shape.schema.json")))
Draft202012Validator.check_schema(SCHEMA)
V = Draft202012Validator(SCHEMA)


def targets(args):
    for a in args or [os.path.join(HERE, "golden")]:
        yield from sorted(glob.glob(os.path.join(a, "*.json"))) if os.path.isdir(a) else [a]


def main():
    fails = 0
    for f in targets(sys.argv[1:]):
        errs = list(V.iter_errors(json.load(open(f))))
        print(f"{os.path.basename(f):32} {'PASS' if not errs else 'FAIL ' + errs[0].message}")
        fails += bool(errs)
    print(f"\n{'OK' if not fails else 'FAILED'}: {fails} invalid")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
