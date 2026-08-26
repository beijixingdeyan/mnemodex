"""The mnemodex command-line interface.

Usage::

    mnemodex init                 create the store for this repository
    mnemodex index                build the code knowledge graph + index
    mnemodex add "<fact>"         remember a decision / gotcha / tip
    mnemodex recall "<topic>"     search memory + code
    mnemodex ask "<topic>"        compressed context pack (agent-ready)
    mnemodex search "<topic>"     find files (TF-IDF)
    mnemodex symbol <name>        resolve a symbol to its definitions
    mnemodex graph                knowledge graph (json / dot / text)
    mnemodex serve                run the MCP server (stdio or SSE)
    mnemodex web                  zero-dependency web UI
    mnemodex export               memory / agent files / index summary
    mnemodex forget <id|--query>  delete memory
    mnemodex list                 list memory
    mnemodex stats | doctor | gc  housekeeping
    mnemodex gif                  regenerate the README demo GIF
    mnemodex completion          print a shell completion script

All commands return 0 on success, non-zero on failure.
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from typing import Any, Dict, List, Optional, Sequence

from . import util
from .errors import MnemodexError, NotInitializedError, StoreCorruptError
from .log import configure as configure_log
from .version import __version__

DAY = 86400


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mnemodex",
        description="The memory index for AI coding agents. Zero dependencies.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"mnemodex {__version__}")
    parser.add_argument("--cwd", default=None, help="run as if started in this directory")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warn", "error", "quiet"])
    parser.add_argument("--log-file", default=None, help="write logs to a file")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create the store for this repository")
    p.add_argument("--force", action="store_true", help="recreate an existing store")
    p.add_argument("--no-gitignore", action="store_true", help="do not touch the repo .gitignore")
    p.add_argument("--example", action="store_true", help="seed 4 example memory entries")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("index", help="build/refresh the code index and knowledge graph")
    p.add_argument("--config", default=None, help="JSON file with indexer options")
    p.set_defaults(fn=cmd_index)

    p = sub.add_parser("add", help="remember a fact about this repository")
    p.add_argument("text", nargs="*", help="the fact (or use --file)")
    p.add_argument("--file", default=None, help="read the fact from a file")
    p.add_argument("--kind", default=None, choices=["decision", "gotcha", "tip", "api", "convention", "task", "note"])
    p.add_argument("--tags", default=None, help="comma-separated tags")
    p.add_argument("--importance", type=int, default=3, choices=range(1, 6))
    p.add_argument("--ttl", type=int, default=None, help="days until expiry")
    p.add_argument("--ref", default=None, help="repo-relative path the fact concerns")
    p.add_argument("--line", type=int, default=None, help="line number in --ref")
    p.add_argument("--no-autocategorize", action="store_true")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("recall", aliases=["ask"], help="search memory + code index")
    p.add_argument("query", nargs="+")
    p.add_argument("--kind", default=None, choices=["decision", "gotcha", "tip", "api", "convention", "task", "note"])
    p.add_argument("--tag", default=None)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--budget", type=int, default=None, help="token budget for `ask` mode")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.set_defaults(fn=cmd_recall)

    p = sub.add_parser("search", help="find files by free-text query")
    p.add_argument("query", nargs="+")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--language", default=None)
    p.add_argument("--path", default=None, help="restrict to a path prefix")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("symbol", help="resolve a symbol to its definitions")
    p.add_argument("name")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_symbol)

    p = sub.add_parser("graph", help="inspect the knowledge graph")
    p.add_argument("--format", choices=["json", "dot", "text"], default="text")
    p.add_argument("--path", default=None, help="focus on one file/symbol (dot)")
    p.add_argument("--path-a", default=None, help="shortest path from…")
    p.add_argument("--path-b", default=None, help="…to this node id")
    p.add_argument("--hops", type=int, default=2, help="neighbourhood radius for a node")
    p.add_argument("--components", action="store_true", help="list connected components")
    p.add_argument("--out", default=None, help="write DOT to a file")
    p.set_defaults(fn=cmd_graph)

    p = sub.add_parser("serve", help="run the MCP server")
    p.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8766)
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("web", help="start the zero-dependency web UI")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_web)

    p = sub.add_parser("export", help="export memory / agent files / index")
    p.add_argument("what", nargs="?", choices=["memory", "agent", "index"], default="memory")
    p.add_argument("--format", choices=["md", "json"], default="md")
    p.add_argument("--out", default=None, help="write to a file instead of stdout")
    p.add_argument("--kind", default=None)
    p.add_argument("--tag", default=None)
    p.add_argument("--targets", default=None, help="agent export: claude,codex,cursor")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("forget", help="delete memory entries")
    p.add_argument("id", nargs="?", default=None)
    p.add_argument("--query", default=None, help="forget everything matching a query")
    p.set_defaults(fn=cmd_forget)

    p = sub.add_parser("list", help="list memory entries")
    p.add_argument("--kind", default=None)
    p.add_argument("--tag", default=None)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("stats", help="store statistics")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_stats)

    p = sub.add_parser("doctor", help="check the installation and store health")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("gc", help="garbage-collect memory: TTLs, dedupe, cap")
    p.add_argument("--quiet", action="store_true", help="only print the summary line")
    p.set_defaults(fn=cmd_gc)

    p = sub.add_parser("gif", help="regenerate the README demo GIF (self-contained)")
    p.add_argument("--out", default=None, help="output path (default docs/demo.gif)")
    p.add_argument("--width", type=int, default=860)
    p.add_argument("--height", type=int, default=460)
    p.add_argument("--fps", type=int, default=12)
    p.add_argument("--frames", type=int, default=0, help="frame count (0 = auto)")
    p.set_defaults(fn=cmd_gif)

    p = sub.add_parser("completion", help="print a shell completion script")
    p.add_argument("shell", nargs="?", default=None, help="bash|zsh|fish|powershell (default bash)")
    p.add_argument("--shell", dest="shell_flag", choices=["bash", "zsh", "fish", "powershell"], default=None)
    p.set_defaults(fn=cmd_completion)

    p = sub.add_parser("version", help="print version and environment info")
    p.set_defaults(fn=cmd_version)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Our UI language includes ✓ ⚖ 🧠 etc.; pin UTF-8 regardless of the
    # console codepage (avoids UnicodeEncodeError on GBK/CP1252 terminals
    # and makes `mnemodex | less` byte-stable).
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cwd:
        os.chdir(args.cwd)
    configure_log(args.log_level, args.log_file)
    from .log import get_logger

    log = get_logger()
    try:
        return int(args.fn(args, log) or 0)
    except NotInitializedError as exc:
        print(exc.pretty(), file=sys.stderr)
        return exc.exit_code
    except StoreCorruptError as exc:
        print(exc.pretty(), file=sys.stderr)
        return exc.exit_code
    except MnemodexError as exc:
        print(exc.pretty(), file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except BrokenPipeError:
        return 141
    except Exception as exc:  # pragma: no cover - last resort
        print(f"unexpected error: {exc!r}", file=sys.stderr)
        return 1


def _session(args) -> Any:
    from .session import Session

    return Session()


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_init(args, log) -> int:
    from . import config as config_mod
    from .console import box, paint, status

    cwd = os.path.abspath(os.getcwd())
    store_dir = os.path.join(cwd, config_mod.DEFAULT_STORE_DIR)
    if os.path.exists(store_dir) and not args.force:
        print(paint(f"store already exists: {store_dir}", "yellow"))
        print("  → run `mnemodex index` to build the index, or `--force` to recreate.")
        return 1
    if args.force:
        import shutil

        shutil.rmtree(store_dir, ignore_errors=True)
    os.makedirs(store_dir, exist_ok=True)
    config = config_mod.default_config()
    config_mod.write_config(store_dir, config)
    touched_gitignore = False
    if not args.no_gitignore:
        touched_gitignore = config_mod.gitignore_append(cwd, config_mod.DEFAULT_STORE_DIR)
    print(box(paint("mnemodex initialized", "bold") + "\n" + paint("memory index ready for this repository", "dim")))
    print(status(f"store created at {store_dir}"))
    if touched_gitignore:
        print(status(".gitignore updated (the store stays out of git)"))
    if args.example:
        from .memory import Memory

        mem = Memory(store_dir)
        samples = [
            ("decision", ["cache"], "We decided to cache auth tokens for 5 minutes to keep hot-path latency under 50ms."),
            ("gotcha", ["cache", "cookies"], "Gotcha: cookie hashes are stable only within one release; cache keys must include the schema version."),
            ("tip", ["docker"], "Tip: the dev image is ~3x smaller when built with --mount=type=cache for the package cache."),
            ("convention", ["style"], "Convention: public functions must be documented; new code follows sections A and B of CONTRIBUTING.md."),
        ]
        for kind, tags, text in samples:
            mem.add(text, kind=kind, tags=tags, source="example")
        print(status("seeded 4 example memory entries"))
    print(paint("\nnext steps:", "dim"))
    print("  mnemodex index   # build the code knowledge graph")
    print("  mnemodex add \"<fact>\" --kind decision")
    print("  mnemodex ask \"cache eviction\"   # agent-ready context")
    return 0


def cmd_index(args, log) -> int:
    from .console import paint, section, status
    from .indexer import IndexBuilder

    session = _session(args)
    config = dict(session.config)
    if args.config:
        data = util.read_json(args.config)
        if isinstance(data, dict):
            for k, v in data.items():
                config[k] = v
    print(paint(f"indexing {session.repo_root} …", "bold"))
    builder = IndexBuilder(session.repo_root, config, progress=lambda m: log.info(m))
    result = builder.build()
    path = os.path.join(session.store_dir, "index.json")
    util.atomic_write_json(path, result)
    session.reload_index()
    summary = result["summary"]
    print(status(f"indexed {summary['files']} files in {summary['duration_ms']} ms"))
    print(section("summary"))
    print(
        f"  files      {summary['files']}\n"
        f"  lines      {summary['lines']:,}\n"
        f"  symbols    {summary['symbols']}\n"
        f"  edges      {summary['edges']}\n"
        f"  languages  {', '.join(f'{k} ({v})' for k, v in list(summary.get('languages', {}).items())[:8])}"
    )
    print(status(f"index written to {os.path.join(session.store_dir, 'index.json')}"))
    return 0


def cmd_add(args, log) -> int:
    from .console import paint, status
    from .store import KIND_META

    session = _session(args)
    text = " ".join(args.text)
    if args.file:
        text = util.read_text_file(os.path.abspath(args.file))
    tags = [t for t in (args.tags or "").split(",") if t]
    result = session.add_memory(
        text,
        kind=args.kind,
        tags=tags,
        file=args.ref,
        line=args.line,
        source="cli",
        importance=args.importance,
        ttl=args.ttl,
    )
    entry = result["entry"]
    if result.get("duplicate"):
        print(paint(f"already knew that — entry {entry['id']} was a duplicate, nothing written.", "yellow"))
        return 0
    meta = KIND_META.get(entry["kind"], {})
    print(status(f"remembered {paint(entry['kind'], 'cyan')} {meta.get('icon', '')}  {entry['id']}"))
    print(f"  {entry['text'][:120]}")
    if entry.get("file"):
        print(f"  → {entry['file']}{':' + str(entry['line']) if entry.get('line') else ''}")
    return 0


def cmd_recall(args, log) -> int:
    from .console import paint, section, table
    from .store import KIND_META

    session = _session(args)
    query = " ".join(args.query)
    kind = args.kind
    pack = None
    if query and args.budget:
        pack = session.context_pack(query, args.budget)
        if not args.json:
            print(pack.render())
            return 0
    memory = session.memory.recall(query=query or None, kind=kind, tag=args.tag, limit=args.limit)
    files = []
    if query and not kind:
        try:
            files = session.search(query, limit=min(args.limit, 10))
        except Exception:
            files = []
    if args.json:
        out = {
            "query": query,
            "memory": memory,
            "files": [f.to_dict() for f in files],
        }
        if pack is not None:
            out["context"] = pack.render()
        print(util.format_json(out))
        return 0
    if memory:
        print(section("memory"))
        rows = []
        for e in memory:
            meta = KIND_META.get(e.get("kind", "note"), {})
            where = f"{e.get('file')}:{e.get('line')}" if e.get("file") else "repo"
            rows.append(
                [
                    e["id"][:8],
                    paint(meta.get("label", e.get("kind", "")), "cyan"),
                    util.truncate(e.get("text", ""), 58),
                    where,
                    util.time_ago(e.get("created_at", 0)),
                ]
            )
        print(table(rows, ["id", "kind", "text", "location", "age"]))
    if files:
        print(section("code index"))
        rows = []
        for r in files:
            rows.append(
                [
                    r.path,
                    r.file.language if r.file else "",
                    f"{r.score:.2f}",
                    ", ".join(k for k, v in r.reasons.items() if v > 0)[:30],
                ]
            )
        print(table(rows, ["file", "lang", "score", "matched"]))
    if not memory and not files:
        print("(nothing found — consider `mnemodex add \"…\"` to record what you learn)")
    return 0


def cmd_search(args, log) -> int:
    from .console import paint, table

    session = _session(args)
    query = " ".join(args.query)
    results = session.search(query, limit=args.limit, language=args.language, path_prefix=args.path)
    if args.json:
        print(util.format_json([r.to_dict() for r in results]))
        return 0
    rows = []
    for r in results:
        rows.append(
            [
                paint(r.path, "white"),
                r.file.language if r.file else "",
                f"{r.score:.2f}",
                "content" if r.reasons.get("content") else "",
            ]
        )
    print(table(rows, ["file", "lang", "score", "signal"]))
    return 0


def cmd_symbol(args, log) -> int:
    from .console import paint, table

    session = _session(args)
    hits = session.lookup_symbol(args.name, fuzzy=True)
    if args.json:
        print(util.format_json([h.to_dict() for h in hits]))
        return 0
    if not hits:
        print(f"no symbol named {args.name!r} found. Try `mnemodex search {args.name}`.")
        return 1
    rows = []
    for h in hits:
        rows.append([paint(h.name, "cyan"), h.kind, f"{h.path}:{h.line}", h.signature])
    print(table(rows, ["name", "kind", "location", "signature"]))
    return 0


def cmd_graph(args, log) -> int:
    from .console import paint, section, tree

    session = _session(args)
    graph = session.graph()
    if args.format == "json":
        print(util.format_json(graph.to_dict()))
        return 0
    if args.format == "dot":
        dot = graph.to_dot(focus_files=[args.path] if args.path else None)
        if args.out:
            util.atomic_write_text(args.out, dot)
            print(f"wrote {args.out}")
        else:
            print(dot)
        return 0
    # text mode
    if args.path:
        node = graph.get(args.path) or next(
            (n for n in graph.nodes.values() if args.path in (n.id, n.attrs.get("name", ""))), None
        )
        if node is None:
            print(f"node not found: {args.path}")
            return 1
        neighbours = graph.k_hop(node.id, args.hops)
        print(section(f"neighbourhood of {node.id} (≤{args.hops} hops)"))
        for nid, dist in sorted(neighbours.items(), key=lambda kv: kv[1]):
            n = graph.get(nid)
            label = n.attrs.get("name") if n else nid
            print(f"{'  ' * dist}{'└─ ' if dist else ''}{paint(str(label), 'cyan' if n.kind == 'symbol' else 'white')}")
        return 0
    if args.path_a and args.path_b:
        path = graph.shortest_path(args.path_a, args.path_b)
        if path is None:
            print("no path between those nodes")
            return 1
        print(section("shortest path"))
        print(tree(path))
        return 0
    if args.components:
        comps = graph.connected_components()
        print(f"{len(comps)} connected components")
        for i, comp in enumerate(sorted(comps, key=len, reverse=True)[:10], start=1):
            names = [graph.get(c).attrs.get("name", c) for c in comp[:8]]
            print(f"  component {i} ({len(comp)}): {', '.join(map(str, names))}{'…' if len(comp) > 8 else ''}")
        return 0
    pr = graph.page_rank(iterations=15)
    top = sorted(((s, n) for n in graph.nodes.values() for s in [pr.get(n.id, 0)]), key=lambda t: -t[0])[:10]
    print(section("top nodes by page-rank"))
    for score, node in top[:10]:
        label = node.attrs.get("name") or node.id
        print(f"  {score:.4f}  {node.kind:8s} {label}")
    print(section("graph totals"))
    print(f"  nodes {len(graph.nodes)} · edges {len(graph.edges)} · files {len(graph.files())} · symbols {len(graph.symbols())}")
    return 0


def cmd_serve(args, log) -> int:
    from .mcp import server_for_session

    session = _session(args)
    server = server_for_session(session)
    if args.transport == "sse":
        server.serve_sse(args.host, args.port)
    else:
        server.serve_stdio()
    return 0


def cmd_web(args, log) -> int:
    from .webui import run_webui

    session = _session(args)
    host = args.host or session.config.get("web_host", "127.0.0.1")
    port = int(args.port or session.config.get("web_port", 8765))
    url = f"http://{host}:{port}"
    if not args.no_browser:
        threading_open(url)
    print(f"mnemodex web UI → {url}  (Ctrl+C to stop)")
    return run_webui(session, host, port)


def threading_open(url: str) -> None:
    import threading

    threading.Timer(0.6, lambda: webbrowser.open(url)).start()


def cmd_export(args, log) -> int:
    from .console import status
    from .exporters import agent_files as af
    from .exporters import export_index_summary, export_memory, write_agent_files

    session = _session(args)
    if args.what == "memory":
        content = export_memory(session, args.format, args.kind, args.tag)
    elif args.what == "index":
        content = export_index_summary(session)
    else:
        if args.dry_run:
            paths = write_agent_files(session, targets=(args.targets or "").split(",") if args.targets else None, dry_run=True)
            for p in paths:
                print(status(p))
            return 0
        written = write_agent_files(session, targets=(args.targets or "").split(",") if args.targets else None)
        for p in written:
            print(status(f"wrote {os.path.join(session.repo_root, p)}"))
        return 0
    if args.out:
        path = os.path.abspath(args.out)
        util.atomic_write_text(path, content)
        print(status(f"wrote {path}"))
    else:
        print(content)
    return 0


def cmd_forget(args, log) -> int:
    from .console import status

    session = _session(args)
    if args.query:
        removed = session.memory.forget_matching(args.query)
        print(status(f"forgot {removed} entries matching {args.query!r}"))
        return 0
    if not args.id:
        print("usage: mnemodex forget <id>  or  mnemodex forget --query \"<text>\"")
        return 2
    ok = session.memory.forget(args.id)
    if ok:
        print(status(f"forgot {args.id}"))
    else:
        print(f"no entry with id {args.id}")
        return 1
    return 0


def cmd_list(args, log) -> int:
    from .console import table
    from .store import KIND_META

    session = _session(args)
    entries = session.memory.recall(kind=args.kind, tag=args.tag, limit=args.limit)
    rows = []
    for e in entries:
        meta = KIND_META.get(e.get("kind", "note"), {})
        rows.append(
            [
                e["id"][:8],
                f"{meta.get('label', e.get('kind', ''))}",
                util.truncate(e.get("text", ""), 52),
                ",".join(e.get("tags", [])[:3]),
                util.time_ago(e.get("created_at", 0)),
            ]
        )
    print(table(rows, ["id", "kind", "text", "tags", "age"]))
    return 0


def cmd_stats(args, log) -> int:
    from .console import section, table

    session = _session(args)
    stats = session.stats()
    if args.json:
        print(util.format_json(stats))
        return 0
    mem = stats["memory"]
    print(section("memory"))
    print(table([[k, str(v)] for k, v in mem.items()]))
    idx = stats["index"]
    if idx:
        print(section("code index"))
        rows = [
            ["files", idx.get("files", 0)],
            ["lines", f"{idx.get('lines', 0):,}"],
            ["symbols", idx.get("symbols", 0)],
            ["edges", idx.get("edges", 0)],
            ["duration", f"{idx.get('duration_ms', 0)} ms"],
        ]
        print(table(rows))
        print(section("languages"))
        print(table([[k, str(v)] for k, v in sorted(idx.get("languages", {}).items(), key=lambda kv: -kv[1])[:10]]))
    else:
        print("(no index yet — run `mnemodex index`)")
    return 0


def cmd_doctor(args, log) -> int:
    from .console import paint, section, status

    print(section("python"))
    print(status(f"python {sys.version.split()[0]}"))
    print(status(f"mnemodex {__version__}"))
    errors = 0
    try:
        session = _session(args)
        print(section("store"))
        print(status(f"store at {session.store_dir}"))
        print(status(f"repo root {session.repo_root}"))
        try:
            session.require_index()
            print(status("index present"))
        except Exception:
            errors += 1
            print(status("index missing — run `mnemodex index`", ok=False))
        n = session.memory.store.count()
        print(status(f"{n} memory entries"))
    except NotInitializedError:
        errors += 1
        print(status("no store in this repository — run `mnemodex init`", ok=False))
    print(section("system"))
    from .gitlog import _git_available

    print(status("git available" if _git_available() else "git NOT available (optional)", ok=_git_available()))
    try:
        import importlib.util

        has_embedding = importlib.util.find_spec("numpy")
        if has_embedding is None:
            print(status("zero third-party dependencies in use (pure stdlib ✓)"))
    except Exception:
        pass
    print(paint("\ndiagnosis complete.", "dim"))
    return 0 if errors == 0 else 1


def cmd_gc(args, log) -> int:
    from .console import section, status

    session = _session(args)
    report = session.memory.store.gc()
    if not args.quiet:
        print(section("garbage collection"))
    print(status(f"kept {report['after']} entries (removed {report['expired']} expired, {report['deduped']} dupes)"))
    return 0


def cmd_gif(args, log) -> int:
    from .gif import render_demo_gif

    out = args.out or os.path.join(args.cwd or os.getcwd(), "docs", "demo.gif")
    log.info(f"rendering demo GIF to {out}")
    path = render_demo_gif(out, width=args.width, height=args.height, fps=args.fps, frames=args.frames)
    print(f"wrote {path}")
    return 0


def cmd_completion(args, log) -> int:
    shell = args.shell or args.shell_flag or "bash"
    script = COMPLETIONS.get(shell, "")
    print(script)
    return 0


def cmd_version(args, log) -> int:
    from .console import paint

    print(paint(f"mnemodex {__version__}", "bold"))
    print(f"python       {sys.version.split()[0]}")
    print(f"platform     {sys.platform}")
    try:
        session = _session(args)
        print(f"store        {session.store_dir}")
        print(f"repo root    {session.repo_root}")
    except NotInitializedError:
        print("store        (none in this directory)")
    return 0


# ---------------------------------------------------------------------------
# shell completions
# ---------------------------------------------------------------------------

_COMPLETE_COMMANDS = "init index add recall ask search symbol graph serve web export forget list stats doctor gc gif version completion"

COMPLETIONS = {
    "bash": f"""# bash completion for mnemodex — add to ~/.bashrc: source <(mnemodex completion --shell bash)
_mnemodex() {{
    local cur prev
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"
    case "$prev" in
        --kind) COMPREPLY=( $(compgen -W "decision gotcha tip api convention task note" -- "$cur") ); return ;;
        --format) COMPREPLY=( $(compgen -W "md json" -- "$cur") ); return ;;
        --transport) COMPREPLY=( $(compgen -W "stdio sse" -- "$cur") ); return ;;
        --shell) COMPREPLY=( $(compgen -W "bash zsh fish powershell" -- "$cur") ); return ;;
    esac
    if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "--cwd --log-level --log-file --help --version" -- "$cur") )
    else
        COMPREPLY=( $(compgen -W "{_COMPLETE_COMMANDS}" -- "$cur") )
    fi
}}
complete -F _mnemodex mnemodex
""",
    "zsh": f"""#compdef mnemodex
_mnemodex() {{
  local -a commands
  commands=({_COMPLETE_COMMANDS})
  _describe 'command' commands
}}
_mnemodex "$@"
""",
    "fish": f"""# fish completion for mnemodex — add to ~/.config/fish/completions/mnemodex.fish
complete -c mnemodex -f -a "{_COMPLETE_COMMANDS}"
complete -c mnemodex -l kind -a "decision gotcha tip api convention task note"
complete -c mnemodex -l transport -a "stdio sse"
""",
    "powershell": """# PowerShell completion for mnemodex
Register-ArgumentCompleter -Native -CommandName mnemodex -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    '""" + _COMPLETE_COMMANDS + """'.Split(' ') | Where-Object { $_ -like "$wordToComplete*" }
}
""",
}


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())