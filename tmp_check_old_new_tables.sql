SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('Combined WO-Outgoing Form Filing 2022-2025', 'combined_wo_outgoing_form_filing');
