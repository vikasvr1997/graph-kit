"""Standalone chat server and evaluations, without importing graph workflows."""
import argparse
import asyncio
import json
import os


def main(argv=None):
    parser = argparse.ArgumentParser(description="Standalone chat assistant")
    parser.add_argument("command", choices=["serve", "eval"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model", default=os.getenv("CHAT_MODEL", "gemini-3.5-flash"))
    args = parser.parse_args(argv)
    os.environ["GRAPHKIT_ENABLED"] = "false"
    os.environ["CHAT_ENABLED"] = "true"
    os.environ["CHAT_MODEL"] = args.model
    if args.command == "serve":
        import uvicorn
        uvicorn.run("graphkit.api.application:app", host=args.host, port=args.port)
        return 0
    from graphkit.chat.agent import get_runner
    from graphkit.chat.eval import run_eval
    from graphkit.chat.eval import summary
    runner = get_runner(generation_model=args.model, graph_enabled=False)
    runs = asyncio.run(run_eval(runner))
    result = summary(runs)
    print(json.dumps(result, indent=2))
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
