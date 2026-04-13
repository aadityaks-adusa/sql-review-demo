-- Wrong naming convention: should be DM<x.y.z>__<description>.sql
-- This file name will trigger a HARD_BLOCK naming violation in the scanner.

UPDATE promotions.cpt_promotion
SET    active_fl    = 'N',
       audt_upd_dt_tm = CURRENT_TIMESTAMP,
       audt_upd_id    = CURRENT_USER
WHERE  end_dt < CURRENT_DATE
  AND  active_fl = 'Y';
