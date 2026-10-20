"""Compatibility entrypoint; graph CLI lives in graphkit.graph.cli."""
from graphkit.graph.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
