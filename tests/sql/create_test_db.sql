
-- BASH COMMANDS

-- Option 1: Connect as the postgres user (might prompt for password)
-- psql -U postgres
-- Option 2: If using Homebrew on macOS, you might just type:
-- psql postgres
-- Option 3: If connecting locally and your OS user matches a PG user:
-- psql -d postgres 


-- Create the user role 'test_user' with login rights and the password 'test_pass'
-- (Matches the user/pass in your conftest.py's TEST_DATABASE_URL)
CREATE ROLE test_user WITH LOGIN PASSWORD 'test_pass';

-- Create the database named 'test_db'
-- (Matches the database name in your conftest.py's TEST_DATABASE_URL)
CREATE DATABASE test_db;

-- Grant ownership of the 'test_db' database to the 'test_user' role
-- (This gives the test user necessary permissions like connect, create tables etc.)
ALTER DATABASE test_db OWNER TO test_user;