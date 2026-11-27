PANEL ?= panel
BENCH_METHODS = judge,jury,chateval,committee
BENCH_SEEDS = 0,1,2

.PHONY: bench bench-dev

bench:
	$(PANEL) bench pairwise --split test --seeds $(BENCH_SEEDS) --methods $(BENCH_METHODS)

bench-dev:
	$(PANEL) bench pairwise --split dev --seeds $(BENCH_SEEDS) --methods $(BENCH_METHODS)
