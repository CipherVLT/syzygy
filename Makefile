.PHONY: install run dev dev-run update uninstall clean

install:
	./build.sh

run:
	./build.sh --run

dev:
	./build.sh --dev

dev-run:
	./build.sh --dev --run

update:
	./build.sh --update

uninstall:
	./build.sh --uninstall

clean:
	rm -rf .venv dist build *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
