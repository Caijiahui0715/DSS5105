-- 2026-10-10: Sentosa Cove / 市中心扩展后, 部分房源周边没有 MRT,
-- mrt_* 四列允许 NULL ("附近没有 MRT" 是事实, 不是缺数据)。
-- 用 to_regclass 保护: 测试库(<DB_NAME>_test)里没有 public.listings 时自动跳过。
DO $$
BEGIN
  IF to_regclass('public.listings') IS NOT NULL THEN
    ALTER TABLE public.listings ALTER COLUMN mrt_station DROP NOT NULL;
    ALTER TABLE public.listings ALTER COLUMN mrt_distance_m DROP NOT NULL;
    ALTER TABLE public.listings ALTER COLUMN mrt_minutes_reported DROP NOT NULL;
    ALTER TABLE public.listings ALTER COLUMN mrt_operation_status DROP NOT NULL;
  END IF;
END $$;
