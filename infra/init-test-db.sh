#!/bin/bash
# Creates the separate test database. CONVENTIONS.md §13: tests never run
# against the dev database — BonviZvonki did that and test rows leaked into
# the UI among real client records.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-SQL
    CREATE DATABASE ${POSTGRES_TEST_DB:-bonvicall_test};
SQL
