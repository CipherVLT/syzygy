.PHONY: install run clean

install:
	./build.sh

run:
	./build.sh --run

clean:
	rm -rf .venv dist build *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
