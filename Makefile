.PHONY: up down test logs

up:            ## start the whole demo (http://localhost:8080)
	docker compose up -d --build

down:
	docker compose down

test: up       ## run the test bench against the running stack
	docker compose --profile test run --rm --build tests
	./tests/restart_check.sh

logs:
	docker compose logs -f gateway app
