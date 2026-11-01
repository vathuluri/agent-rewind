import argparse
import json
from pathlib import Path
from .store import Store
from .demo import start_demo, fork_demo
from .server import serve


def main():
    parser = argparse.ArgumentParser(description="Inspect and fork recorded agent trajectories.")
    parser.add_argument("--db", default="agent-rewind.db", help="Local SQLite file")
    sub = parser.add_subparsers(dest="command", required=True)
    web = sub.add_parser("serve"); web.add_argument("--port", type=int, default=8765)
    sub.add_parser("demo")
    export = sub.add_parser("export"); export.add_argument("run_id"); export.add_argument("--out", required=True)
    args = parser.parse_args()
    store = Store(args.db)
    if args.command == "serve":
        serve(store, args.port)
    elif args.command == "demo":
        baseline = start_demo(store)
        branch = fork_demo(store, baseline, 1, "evidence-first")
        print(json.dumps(store.compare(baseline, branch), indent=2))
    else:
        Path(args.out).write_text(json.dumps(store.get(args.run_id), indent=2), encoding="utf-8")
        print(f"Exported recorded trajectory to {args.out}")


if __name__ == "__main__":
    main()
