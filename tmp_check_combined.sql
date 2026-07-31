SELECT EXISTS (
  SELECT 1
  FROM information_schema.tables
  WHERE table_schema = 'public'
    AND table_name = 'Combined WO-Outgoing Form Filing 2022-2025'
);
