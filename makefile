# Launch the coaching CLI, clean a PGN, or run the test suite.
#
# Examples:
#   make test
#   make pilot              # Interactive session on the built-in sample game
#   make start              # Clipboard, or paste once the prompt is running
#   make start games/2.pgn  # Load a PGN file
#   make cleanup            # Cleans PGN from clipboard or prompts
#   make cleanup games/2.pgn

.PHONY: start cleanup clean test pilot

ifeq (start,$(firstword $(MAKECMDGOALS)))
  PGN_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  $(eval $(PGN_ARGS):;@:)
endif

ifeq (cleanup,$(firstword $(MAKECMDGOALS)))
  PGN_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  $(eval $(PGN_ARGS):;@:)
endif

test:
	@.venv/bin/python run_tests.py $(ARGS)

pilot:
	@.venv/bin/python dupont/cli.py < tests/pilot-game.pgn

start:
	@TARGET_PGN="$$PGN"; \
	if [ -z "$$TARGET_PGN" ] && [ -n "$(PGN_ARGS)" ]; then \
		TARGET_PGN="$(PGN_ARGS)"; \
	fi; \
	if [ -n "$$TARGET_PGN" ]; then \
		.venv/bin/python dupont/cli.py "$$TARGET_PGN"; \
	else \
		.venv/bin/python dupont/cli.py; \
	fi

cleanup:
	@TARGET_PGN="$$PGN"; \
	if [ -z "$$TARGET_PGN" ] && [ -n "$(PGN_ARGS)" ]; then \
		TARGET_PGN="$(PGN_ARGS)"; \
	fi; \
	if [ -n "$$OUT" ]; then \
		if [ -n "$$TARGET_PGN" ]; then \
			.venv/bin/python dupont/pgn_cleaner.py "$$TARGET_PGN" -o "$$OUT"; \
		else \
			.venv/bin/python dupont/pgn_cleaner.py -o "$$OUT"; \
		fi; \
	else \
		if [ -n "$$TARGET_PGN" ]; then \
			.venv/bin/python dupont/pgn_cleaner.py "$$TARGET_PGN"; \
		else \
			.venv/bin/python dupont/pgn_cleaner.py; \
		fi; \
	fi

clean: cleanup
