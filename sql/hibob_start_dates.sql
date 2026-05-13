-- HiBob work start date per employee (Airbyte raw). Env: STAFFING_HIBOB_START_DATES_SQL_PATH
-- If Databricks column layout differs from Step 0 verify, adjust only the two CAST(_airbyte_data:...) lines below
-- (email uses the same `_airbyte_data:\`/root/email\`:value` pattern as sql/capacity.sql active_employees;
-- start date uses `_airbyte_data:\`/work/startDate\`:value` (no `/root/` prefix; asymmetric vs email).

WITH hibob_start AS (
    SELECT
        LOWER(TRIM(CAST(_airbyte_data:`/root/email`:value AS STRING))) AS email,
        CAST(_airbyte_data:`/work/startDate`:value AS STRING) AS start_date_raw
    FROM svc_finance.raw_hibob._airbyte_raw_employees
    QUALIFY ROW_NUMBER() OVER (PARTITION BY email ORDER BY _airbyte_emitted_at DESC) = 1
)
SELECT
    email,
    start_date_raw
FROM
    hibob_start
