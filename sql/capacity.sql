WITH
  pto_data AS (
    SELECT
      LOWER(TRIM(CAST(_airbyte_data:employeeDisplayName AS STRING))) AS display_name,
      CAST(CAST(_airbyte_data:startDate AS STRING) AS DATE) AS pto_start,
      CAST(CAST(_airbyte_data:endDate AS STRING) AS DATE) AS pto_end
    FROM svc_finance.raw_hibob._airbyte_raw_whos_out_next_7_days
    WHERE CAST(_airbyte_emitted_at AS DATE) >= CURRENT_DATE() - INTERVAL 1 DAY
      AND CAST(_airbyte_data:status AS STRING) = 'approved'
  ),
  pto_today AS (
    SELECT display_name, pto_end FROM pto_data
    WHERE pto_start <= CURRENT_DATE() AND pto_end >= CURRENT_DATE()
  ),
  pto_upcoming AS (
    SELECT display_name, pto_start, pto_end FROM pto_data
    WHERE pto_start > CURRENT_DATE() AND pto_start <= DATE_ADD(CURRENT_DATE(), 14)
  ),
  active_orders AS (
    SELECT a.id AS project_id, a.name AS project_name, a.status, a.stage,
           INITCAP(COALESCE(c.tier, 'Tier 2')) AS tier
    FROM svc_solution.ods.delivery_order_act a
    LEFT JOIN (
      SELECT CAST(_airbyte_data:project_id AS STRING) AS project_id,
             CAST(_airbyte_data:tier AS STRING) AS tier
      FROM dmn_core_analytics.raw_airbyte._airbyte_raw_tt_projects_view
      QUALIFY ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY _airbyte_emitted_at DESC) = 1
    ) c ON a.id = c.project_id
    WHERE a.status NOT IN ('ARCHIVED', 'CANCELED', 'COMPLETED')
      AND a.client_id NOT IN (
        '019889a2-485a-74db-a7eb-9b5c0dcc8e04',
        '0198a43d-3b6f-7994-a649-bded73854d96'
      )
  ),
  project_team AS (
    SELECT
      CAST(_airbyte_data:project_id AS STRING) AS project_id,
      CAST(_airbyte_data:responsible_user_id AS STRING) AS responsible_user_id,
      CAST(_airbyte_data:dpm_user_id AS STRING) AS dpm_user_id,
      CAST(_airbyte_data:soe_user_id AS STRING) AS soe_user_id,
      CAST(_airbyte_data:wfm_user_id AS STRING) AS wfm_user_id,
      CAST(_airbyte_data:qm_user_id AS STRING) AS qm_user_id,
      CAST(_airbyte_data:team_json AS STRING) AS team_json
    FROM dmn_core_analytics.raw_airbyte._airbyte_raw_tt_projects_view
    QUALIFY ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY _airbyte_emitted_at DESC) = 1
  ),
  user_assignments AS (
    SELECT DISTINCT project_id, user_id FROM (
      SELECT project_id, responsible_user_id AS user_id FROM project_team UNION ALL
      SELECT project_id, dpm_user_id FROM project_team UNION ALL
      SELECT project_id, soe_user_id FROM project_team UNION ALL
      SELECT project_id, wfm_user_id FROM project_team UNION ALL
      SELECT project_id, qm_user_id FROM project_team UNION ALL
      SELECT project_id, CAST(team_member:userId AS STRING) AS user_id
      FROM (
        SELECT project_id, EXPLODE(CAST(PARSE_JSON(team_json) AS ARRAY<VARIANT>)) AS team_member
        FROM project_team WHERE team_json IS NOT NULL AND team_json != ''
      ) t
    ) u
    WHERE user_id IS NOT NULL AND user_id != ''
  ),
  users AS (
    SELECT
      CAST(_airbyte_data:user_id AS STRING) AS user_id,
      CAST(_airbyte_data:rolename AS STRING) AS user_role,
      CAST(_airbyte_data:email AS STRING) AS user_email,
      CAST(_airbyte_data:name AS STRING) AS user_name
    FROM dmn_core_analytics.raw_airbyte._airbyte_raw_tt_users_view
    QUALIFY ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY _airbyte_emitted_at DESC) = 1
  ),
  active_employees AS (
    SELECT DISTINCT CAST(_airbyte_data:`/root/email`:value AS STRING) AS email
    FROM svc_finance.raw_hibob._airbyte_raw_employees
    WHERE CAST(_airbyte_emitted_at AS DATE) >= CURRENT_DATE() - INTERVAL 1 DAY
  ),
  staffing_pool AS (
    SELECT u.user_id, u.user_name, u.user_email, u.user_role,
      CASE
        WHEN u.user_role IN ('Solution Engineer','Senior Solution Engineer') THEN 'SoE/SSoE'
        WHEN u.user_role = 'Delivery Project Manager' THEN 'DPM'
        WHEN u.user_role IN ('Workforce Coordinator','Workforce Manager') THEN 'WFM/WFC'
        WHEN u.user_role IN ('Quality & Training','Quality Coordinator') THEN 'QM/QC'
        WHEN u.user_role IN ('Software Engineer','Software Engineer Lead') THEN 'SE'
      END AS role_group
    FROM users u
    INNER JOIN active_employees ae ON u.user_email = ae.email
    WHERE u.user_role IN (
      'Solution Engineer','Senior Solution Engineer',
      'Delivery Project Manager',
      'Workforce Coordinator','Workforce Manager',
      'Quality & Training','Quality Coordinator',
      'Software Engineer','Software Engineer Lead'
    )
  )
SELECT
  sp.user_id, sp.user_name, sp.user_email, sp.role_group,
  ao.project_id, ao.project_name, ao.tier, ao.stage, ao.status,
  CASE WHEN pt.display_name IS NOT NULL THEN 1 ELSE 0 END AS on_pto_today,
  date_format(pt.pto_end, 'yyyy-MM-dd') AS pto_today_end,
  CASE WHEN pu.display_name IS NOT NULL THEN 1 ELSE 0 END AS on_pto_upcoming,
  date_format(pu.pto_start, 'yyyy-MM-dd') AS pto_upcoming_start,
  date_format(pu.pto_end, 'yyyy-MM-dd') AS pto_upcoming_end
FROM staffing_pool sp
LEFT JOIN user_assignments ua ON sp.user_id = ua.user_id
LEFT JOIN active_orders ao ON ua.project_id = ao.project_id
LEFT JOIN pto_today pt ON pt.display_name = LOWER(TRIM(sp.user_name))
LEFT JOIN pto_upcoming pu ON pu.display_name = LOWER(TRIM(sp.user_name))
ORDER BY sp.role_group, sp.user_name
