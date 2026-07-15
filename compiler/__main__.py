"""CLI: compile a contract against a site binding.

  python -m compiler <requirement.yaml> <binding.yaml> [--target sql|rdmp]
                     [--out DIR] [--check] [--draft]

--check  run the strict gate + registry conformance + site feasibility and
         report; exit 1 if any problem (no compilation).
--draft  tolerate `note` criteria; output is prefixed with a banner that
         makes it non-executable by construction.
"""
import argparse
import os
import sys

import yaml

import registry as R
import requirement_schema as S

from . import (CompileError, check_feasibility, compile_rdmp, compile_sql,
               load_binding)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m compiler", description=__doc__)
    p.add_argument("contract")
    p.add_argument("binding")
    p.add_argument("--target", choices=["sql", "rdmp"], default="sql")
    p.add_argument("--out", help="directory to write one file per group")
    p.add_argument("--check", action="store_true", help="feasibility report only")
    p.add_argument("--draft", action="store_true")
    args = p.parse_args(argv)

    with open(args.contract) as f:
        contract = yaml.safe_load(f)
    try:
        binding = load_binding(args.binding)
    except CompileError as e:
        print("binding is invalid:\n  " + "\n  ".join(e.problems), file=sys.stderr)
        return 1

    if args.check:
        problems = (["[gate] " + e for e in S.check_contract(contract)]
                    + ["[registry] " + e for e in R.check_sources(contract)])
        if not problems:
            problems = ["[feasibility] " + e
                        for e in check_feasibility(contract, binding)]
        if problems:
            print(f"NOT executable at site '{binding.get('site')}':")
            for e in problems:
                print("  " + e)
            return 1
        print(f"OK: contract is executable at site '{binding.get('site')}'")
        return 0

    try:
        fn = compile_sql if args.target == "sql" else compile_rdmp
        results = fn(contract, binding, draft=args.draft)
    except CompileError as e:
        print("cannot compile:\n  " + "\n  ".join(e.problems), file=sys.stderr)
        return 1

    ext = "sql" if args.target == "sql" else "commands.yaml"
    key = "sql" if args.target == "sql" else "script"
    for r in results:
        if args.out:
            os.makedirs(args.out, exist_ok=True)
            path = os.path.join(args.out, f"{r['id']}.{ext}")
            with open(path, "w") as f:
                f.write(r[key])
            print(f"wrote {path}  ({r['name']})")
        else:
            print(f"===== {r['name']} (id {r['id']}) =====")
            print(r[key])
    return 0


if __name__ == "__main__":
    sys.exit(main())
