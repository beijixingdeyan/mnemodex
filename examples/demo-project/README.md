# demo-project

A deliberately tiny, multi-language toy repository for trying out
**mnemodex**. It is not meant to be useful — it exists so you can run the
whole memory workflow against a small codebase without touching a real
project.

The repo is a pretend "auth token service": `service/` issues short-lived
tokens backed by an LRU cache, with a TypeScript web client (`web/`) and
Rust/Go snippets of the same idea. A couple of facts are worth remembering
(cache policy, token TTL) — exactly the kind of thing mnemodex is for.

## The six commands to try

From this directory, with Python on your `PATH`:

```console
python3 -m mnemodex init
```

Add two memories — one decision, one gotcha:

```console
python3 -m mnemodex add "cache-policy" "TokenCache is LRU with max_entries=128; eviction uses a clock-ish policy" --kind decision
python3 -m mnemodex add "token-ttl" "Tokens are capped at a 60s TTL; validate() rejects anything older" --kind gotcha
```

Index the code into the knowledge graph, then ask:

```console
python3 -m mnemodex index
python3 -m mnemodex ask "what does the cache do" --budget 4000
python3 -m mnemodex ask "how long does a token live" --budget 4000
```

Browse memory and knowledge graph in the web UI:

```console
python3 -m mnemodex serve    # open http://127.0.0.1:7331
```

Or recall raw memory:

```console
python3 -m mnemodex recall
```

`--budget 4000` caps how much context mnemodex pulls into each answer —
handy if `ask` feels slow or noisy.

There is no build step and nothing gets installed; the whole demo lives in
this directory, and `make demo` replays the tour. Cleanup is just deleting
the folder.