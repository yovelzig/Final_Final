-- Runs once, automatically, when the stock-db container initializes an
-- empty data volume (mounted into /docker-entrypoint-initdb.d/ by
-- docker-compose.yml). Creates the separate database used by the
-- PostgreSQL integration test suite so it never touches the dev database.
CREATE DATABASE stock_research_test;
