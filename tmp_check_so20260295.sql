SELECT "WO/SO #", "Customer", "Invoice#", "Outgoing Form#", "Invoice Date"
FROM public."Combined WO-Outgoing Form Filing 2022-2025"
WHERE "WO/SO #" ILIKE '%SO-20260295%';
