-- Quick read-only state check: which collision.* tables/types exist on
-- whatever branch this is run against. Used before every migration apply
-- per the shared-staging discipline in WORKLOG.md/README.md.
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'collision' ORDER BY table_name;

SELECT typname FROM pg_type
JOIN pg_namespace ON pg_namespace.oid = pg_type.typnamespace
WHERE pg_namespace.nspname = 'collision' ORDER BY typname;

SELECT rolname FROM pg_roles WHERE rolname = 'collision_app';

SELECT (SELECT count(*) FROM collision.customer) AS customer_count
WHERE EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='collision' AND table_name='customer');
