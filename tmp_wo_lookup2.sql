SELECT "WO", "Name", "QB Num", "Order", "P. O. #", "Order Date", "Ship Date"
FROM public.wo_structured
WHERE "WO" ILIKE '%20260295%' OR "Name" ILIKE '%Boston Scientific%' OR "Order" ILIKE '%20260295%' OR "QB Num" ILIKE '%20260295%';
