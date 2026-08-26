# -- mnemodex demo replay ---------------------------------------------
# Every target shells out to `python3 -m mnemodex`; no build step.

.PHONY: init add index ask serve recall demo

init:
	python3 -m mnemodex init

add:
	python3 -m mnemodex add "cache-policy" "TokenCache is LRU with max_entries=128; eviction is clock-ish" --kind decision
	python3 -m mnemodex add "token-ttl" "Tokens are capped at a 60s TTL" --kind gotcha

index:
	python3 -m mnemodex index

ask:
	python3 -m mnemodex ask "what does the cache do" --budget 4000
	python3 -m mnemodex ask "how long does a token live" --budget 4000

serve:
	python3 -m mnemodex serve

recall:
	python3 -m mnemodex recall --budget 4000

# Tour of the six commands; `serve` is left out because it blocks.
demo: init add index ask recall
	@echo "demo done — run 'make serve' for the web UI at http://127.0.0.1:7331"