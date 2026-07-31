DROP TABLE IF EXISTS public._import_so_woof_stage;
CREATE TABLE public._import_so_woof_stage (
  "WO/SO #" text,
  "Customer" text,
  "Invoice#" text,
  "Outgoing Form#" text,
  "Invoice Date" text
);
\copy public._import_so_woof_stage FROM 'C:/Users/Admin/Desktop/Receiving Log APP/tmp_so_woof_extract.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO public.combined_wo_outgoing_form_filing ("WO/SO #", "Customer", "Invoice#", "Outgoing Form#", "Invoice Date")
SELECT s."WO/SO #", s."Customer", s."Invoice#", s."Outgoing Form#", s."Invoice Date"
FROM public._import_so_woof_stage s
WHERE NOT EXISTS (
  SELECT 1
  FROM public.combined_wo_outgoing_form_filing t
  WHERE COALESCE(t."WO/SO #", '') = COALESCE(s."WO/SO #", '')
    AND COALESCE(t."Customer", '') = COALESCE(s."Customer", '')
    AND COALESCE(t."Invoice#", '') = COALESCE(s."Invoice#", '')
    AND COALESCE(t."Outgoing Form#", '') = COALESCE(s."Outgoing Form#", '')
    AND COALESCE(t."Invoice Date", '') = COALESCE(s."Invoice Date", '')
);
SELECT COUNT(*) AS imported_rows FROM public._import_so_woof_stage;
SELECT COUNT(*) AS total_rows FROM public.combined_wo_outgoing_form_filing;
DROP TABLE public._import_so_woof_stage;
