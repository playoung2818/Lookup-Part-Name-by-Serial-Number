SELECT "WO/SO #", "Customer", "Invoice#", "Outgoing Form#", "Invoice Date"
FROM public."Combined WO-Outgoing Form Filing 2022-2025"
WHERE "WO/SO #" ILIKE '%WO03-20260295%';
