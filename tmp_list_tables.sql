SELECT schemaname, tablename
FROM pg_tables
WHERE tablename ILIKE '%Outgoing%' OR tablename ILIKE '%WO%';
