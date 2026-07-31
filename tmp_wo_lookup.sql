SELECT "WO", "Name", "QB Num", "Order", "P. O. #", "Order Date", "Ship Date"
FROM public.wo_structured
WHERE "WO" ILIKE '%WO03-20260295%';
