
    with
        occupation_coeficients as (
            select
                stage,
                status,
                tier,
                role,
                occupation
            from
            (
                select
                    stage,
                    status,
                    initcap(tier) as tier,
                    responsible,
                    dpm,
                    soe,
                    wfm,
                    qm,
                    se
                from values
                    ('discovery', 'ON_TRACK', 'tier 1', 0.2, 0, 0, 0, 0, 0),
                    ('discovery', 'ON_TRACK', 'tier 2', 0.2, 0, 0, 0, 0, 0),
                    ('discovery', 'ON_TRACK', 'tier 3', 0.3, 0, 0, 0, 0, 0),
                    ('discovery', 'ON_TRACK', 'tier 4', 0.4, 0, 0, 0, 0, 0),
                    ('discovery', 'AT_RISK', 'tier 1', 0.5, 0, 0, 0, 0, 0),
                    ('discovery', 'AT_RISK', 'tier 2', 0.5, 0, 0, 0, 0, 0),
                    ('discovery', 'AT_RISK', 'tier 3', 0.5, 0, 0, 0, 0, 0),
                    ('discovery', 'AT_RISK', 'tier 4', 0.7, 0, 0, 0, 0, 0),
                    ('discovery', 'BEHIND', 'tier 1', 0.5, 0, 0, 0, 0, 0),
                    ('discovery', 'BEHIND', 'tier 2', 0.5, 0, 0, 0, 0, 0),
                    ('discovery', 'BEHIND', 'tier 3', 0.5, 0, 0, 0, 0, 0),
                    ('discovery', 'BEHIND', 'tier 4', 0.7, 0, 0, 0, 0, 0),
                    ('discovery', 'BLOCKED_CLIENT', 'tier 1', 0.1, 0, 0, 0, 0, 0),
                    ('discovery', 'BLOCKED_CLIENT', 'tier 2', 0.1, 0, 0, 0, 0, 0),
                    ('discovery', 'BLOCKED_CLIENT', 'tier 3', 0.1, 0, 0, 0, 0, 0),
                    ('discovery', 'BLOCKED_CLIENT', 'tier 4', 0.1, 0, 0, 0, 0, 0),
                    ('scoping_solution_design', 'ON_TRACK', 'tier 1', 0.2, 0.3, 0.1, 0.5, 0.2, 0),
                    ('scoping_solution_design', 'ON_TRACK', 'tier 2', 0.2, 0.2, 0.3, 0.2, 0.2, 0),
                    ('scoping_solution_design', 'ON_TRACK', 'tier 3', 0.3, 0.2, 0.2, 0.2, 0.2, 0),
                    ('scoping_solution_design', 'ON_TRACK', 'tier 4', 0.5, 0.5, 0.5, 0.3, 0.2, 0.3),
                    ('scoping_solution_design', 'AT_RISK', 'tier 1', 0.5, 0.3, 0.2, 0.5, 0.2, 0),
                    ('scoping_solution_design', 'AT_RISK', 'tier 2', 0.5, 0.2, 0.3, 0.2, 0.2, 0),
                    ('scoping_solution_design', 'AT_RISK', 'tier 3', 0.5, 0.2, 0.2, 0.2, 0.2, 0),
                    ('scoping_solution_design', 'AT_RISK', 'tier 4', 0.5, 0.5, 0.5, 0.3, 0.2, 0.3),
                    ('scoping_solution_design', 'BEHIND', 'tier 1', 0.2, 0.3, 0.2, 0.5, 0.2, 0),
                    ('scoping_solution_design', 'BEHIND', 'tier 2', 0.5, 0.2, 0.3, 0.2, 0.2, 0),
                    ('scoping_solution_design', 'BEHIND', 'tier 3', 0.5, 0.2, 0.2, 0.2, 0.2, 0),
                    ('scoping_solution_design', 'BEHIND', 'tier 4', 0.5, 0.5, 0.5, 0.3, 0.2, 0.3),
                    ('scoping_solution_design', 'BLOCKED_CLIENT', 'tier 1', 0.1, 0, 0, 0, 0, 0),
                    ('scoping_solution_design', 'BLOCKED_CLIENT', 'tier 2', 0.1, 0, 0, 0, 0, 0),
                    ('scoping_solution_design', 'BLOCKED_CLIENT', 'tier 3', 0.1, 0, 0, 0, 0, 0),
                    ('scoping_solution_design', 'BLOCKED_CLIENT', 'tier 4', 0.5, 0.3, 0.3, 0.3, 0, 0),
                    ('building', 'ON_TRACK', 'tier 1', 0.3, 0.3, 0.3, 0.5, 0.3, 0),
                    ('building', 'ON_TRACK', 'tier 2', 0.2, 0.2, 0.3, 0.2, 0.2, 0),
                    ('building', 'ON_TRACK', 'tier 3', 0.3, 0.5, 0.8, 0.5, 0.3, 0),
                    ('building', 'ON_TRACK', 'tier 4', 0.5, 1, 1, 0.5, 0.3, 0.7),
                    ('building', 'AT_RISK', 'tier 1', 0.3, 0.3, 0.5, 0.5, 0.3, 0),
                    ('building', 'AT_RISK', 'tier 2', 0.5, 0.2, 0.3, 0.2, 0.2, 0),
                    ('building', 'AT_RISK', 'tier 3', 0.3, 0.8, 1, 0.5, 0.3, 0),
                    ('building', 'AT_RISK', 'tier 4', 1, 1, 1, 0.5, 0.2, 0.7),
                    ('building', 'BEHIND', 'tier 1', 0.3, 0.3, 0.5, 0.5, 0.3, 0),
                    ('building', 'BEHIND', 'tier 2', 0.5, 0.2, 0.3, 0.2, 0.2, 0),
                    ('building', 'BEHIND', 'tier 3', 0.3, 0.8, 1, 0.5, 0.3, 0),
                    ('building', 'BEHIND', 'tier 4', 1, 1, 1, 0.5, 0.2, 0.7),
                    ('building', 'BLOCKED_CLIENT', 'tier 1', 0.5, 0.2, 0, 0, 0, 0),
                    ('building', 'BLOCKED_CLIENT', 'tier 2', 0.5, 0.2, 0.3, 0.2, 0.2, 0),
                    ('building', 'BLOCKED_CLIENT', 'tier 3', 0.5, 0.2, 0, 0, 0, 0),
                    ('building', 'BLOCKED_CLIENT', 'tier 4', 0.5, 0.3, 0.5, 0.3, 0.2, 0.5),
                    ('stabilisation_delivery', 'ON_TRACK', 'tier 1', 0.3, 0.3, 0.1, 0.3, 0, 0),
                    ('stabilisation_delivery', 'ON_TRACK', 'tier 2', 0.3, 0.2, 0.2, 0.2, 0, 0),
                    ('stabilisation_delivery', 'ON_TRACK', 'tier 3', 0.5, 0.3, 0.2, 0.2, 0.2, 0),
                    ('stabilisation_delivery', 'ON_TRACK', 'tier 4', 0.5, 0.5, 1, 0.3, 0.2, 0.5),
                    ('stabilisation_delivery', 'AT_RISK', 'tier 1', 0.5, 0.5, 0.1, 0.3, 0.2, 0),
                    ('stabilisation_delivery', 'AT_RISK', 'tier 2', 0.5, 0.3, 0.5, 0.5, 0.2, 0),
                    ('stabilisation_delivery', 'AT_RISK', 'tier 3', 0.5, 0.5, 0.8, 0.5, 0.2, 0),
                    ('stabilisation_delivery', 'AT_RISK', 'tier 4', 0.5, 1, 1, 0.3, 0.2, 0.7),
                    ('stabilisation_delivery', 'BEHIND', 'tier 1', 0.5, 0.5, 0.5, 0.5, 0.2, 0),
                    ('stabilisation_delivery', 'BEHIND', 'tier 2', 0.5, 0.3, 0.5, 0.5, 0.2, 0),
                    ('stabilisation_delivery', 'BEHIND', 'tier 3', 0.5, 0.5, 0.8, 0.5, 0.2, 0),
                    ('stabilisation_delivery', 'BEHIND', 'tier 4', 0.5, 1, 1, 0.3, 0.2, 0.7),
                    ('stabilisation_delivery', 'BLOCKED_CLIENT', 'tier 1', 0.3, 0.2, 0.2, 0.5, 0.2, 0),
                    ('stabilisation_delivery', 'BLOCKED_CLIENT', 'tier 2', 0.3, 0.2, 0.2, 0.5, 0.2, 0),
                    ('stabilisation_delivery', 'BLOCKED_CLIENT', 'tier 3', 0.3, 0.2, 0.2, 0.2, 0.2, 0),
                    ('stabilisation_delivery', 'BLOCKED_CLIENT', 'tier 4', 0.5, 0.3, 0.5, 0.3, 0.2, 0.2),
                    ('close_out_retrospective', 'ON_TRACK', 'tier 1', 0.2, 0.1, 0.1, 0.1, 0.1, 0),
                    ('close_out_retrospective', 'ON_TRACK', 'tier 2', 0.2, 0.1, 0.1, 0.1, 0.1, 0),
                    ('close_out_retrospective', 'ON_TRACK', 'tier 3', 0.2, 0.1, 0.1, 0.1, 0.1, 0),
                    ('close_out_retrospective', 'ON_TRACK', 'tier 4', 0.2, 0.1, 0.1, 0.1, 0.1, 0),
                    ('close_out_retrospective', 'AT_RISK', 'tier 1', 0.2, 0.1, 0.1, 0.1, 0.1, 0),
                    ('close_out_retrospective', 'AT_RISK', 'tier 2', 0.2, 0.1, 0.1, 0.1, 0.1, 0),
                    ('close_out_retrospective', 'AT_RISK', 'tier 3', 0.2, 0.1, 0.1, 0.1, 0.1, 0),
                    ('close_out_retrospective', 'AT_RISK', 'tier 4', 0.2, 0.1, 0.1, 0.1, 0.1, 0),
                    ('close_out_retrospective', 'BEHIND', 'tier 1', 0.2, 0.1, 0.1, 0.1, 0.1, 0),
                    ('close_out_retrospective', 'BEHIND', 'tier 2', 0.2, 0.1, 0.1, 0.1, 0.1, 0),
                    ('close_out_retrospective', 'BEHIND', 'tier 3', 0.2, 0.1, 0.1, 0.1, 0.1, 0),
                    ('close_out_retrospective', 'BEHIND', 'tier 4', 0.2, 0.1, 0.1, 0.1, 0.1, 0),
                    ('close_out_retrospective', 'BLOCKED_CLIENT', 'tier 1', 0.2, 0, 0, 0, 0, 0),
                    ('close_out_retrospective', 'BLOCKED_CLIENT', 'tier 2', 0.2, 0, 0, 0, 0, 0),
                    ('close_out_retrospective', 'BLOCKED_CLIENT', 'tier 3', 0.2, 0, 0, 0, 0, 0),
                    ('close_out_retrospective', 'BLOCKED_CLIENT', 'tier 4', 0.2, 0, 0, 0, 0, 0)
                as t(stage, status, tier, responsible, dpm, soe, wfm, qm, se)
            )
            unpivot ( occupation for role in (responsible, dpm, soe, wfm, qm, se))
        ),
    
        project_staffing as (
            select
                cast(_airbyte_data:project_id as string) as project_id,
                cast(_airbyte_data:name as string) as project_name,
                cast(_airbyte_data:tier as string) as tier,
                cast(_airbyte_data:sunday_id as string) as sunday_id,
                cast(_airbyte_data:responsible_name as string) as responsible_name,
                cast(_airbyte_data:responsible_user_id as string) as responsible_user_id,
                cast(_airbyte_data:director_name as string) as director_name,
                cast(_airbyte_data:director_user_id as string) as director_user_id,
                cast(_airbyte_data:dpm_name as string) as dpm_name,
                cast(_airbyte_data:dpm_user_id as string) as dpm_user_id,
                cast(_airbyte_data:soe_name as string) as soe_name,
                cast(_airbyte_data:soe_user_id as string) as soe_user_id,
                cast(_airbyte_data:wfm_name as string) as wfm_name,
                cast(_airbyte_data:wfm_user_id as string) as wfm_user_id,
                cast(_airbyte_data:qm_name as string) as qm_name,
                cast(_airbyte_data:qm_user_id as string) as qm_user_id,
                cast(_airbyte_data:bizdev_name as string) as bizdev_name,
                cast(_airbyte_data:bizdev_user_id as string) as bizdev_user_id,
                cast(_airbyte_data:team_json as string) as team_json
            from dmn_core_analytics.raw_airbyte._airbyte_raw_tt_projects_view
            qualify
                row_number() over (
                    partition by project_id order by _airbyte_emitted_at desc
                )
                = 1
        ),
    
        user_roles as (
            select
                cast(_airbyte_data:user_id as string) as user_id,
                cast(_airbyte_data:rolename as string) as user_role,
                cast(_airbyte_data:email as string) as user_email,
                cast(_airbyte_data:name as string) as user_name
            from dmn_core_analytics.raw_airbyte._airbyte_raw_tt_users_view
            qualify row_number() over (partition by user_id order by _airbyte_emitted_at desc) = 1
        ),
    
        unpivot_staffing as (
            select distinct project_id, user_id, role as project_role
            from
                (
                    select project_id, 'responsible' as role ,responsible_user_id as user_id
                    from project_staffing
    
                    union all
                    /*
                    select project_id, 'director' as role, director_user_id as user_id
                    from project_staffing
    
                    union all
    
                    select project_id, 'bizdev' as role, bizdev_user_id as user_id
                    from project_staffing
    
                    union all
                    */
                    select project_id, 'dpm' as role, dpm_user_id as user_id
                    from project_staffing
    
                    union all
    
                    select project_id, 'soe' as role, soe_user_id as user_id
                    from project_staffing
    
                    union all
    
                    select project_id, 'wfm' as role, wfm_user_id as user_id
                    from project_staffing
    
                    union all
    
                    select project_id, 'qm' as role, qm_user_id as user_id
                    from project_staffing
    
                    union all
    
                    select project_id, 'other' as role, team_member:userId::string as user_id
                    from
                        (
                            select
                                project_id,
                                explode(
                                    cast(parse_json(team_json) as array<variant>)
                                ) as team_member
                            from project_staffing
                        )
                )
            where user_id is not null and user_id != ''
        ),
    
        staffing_join as (
            select
                unpivot_staffing.project_id,
                unpivot_staffing.user_id,
                user_role, user_email, user_name,
                case
                    when project_role != 'other' then project_role
                    when user_role = 'Quality & Training' then 'qm'
                    when user_role = 'Delivery Project Manager' then 'dpm'
                    when user_role in ('Solution Engineer', 'Senior Solution Engineer') then 'soe'
                    when user_role in ('Workforce Coordinator', 'Workforce Manager') then 'wfm'
                    when user_role in ('Software Engineer', 'Software Engineer Lead') then 'se'
                else 'other'
                end as project_role
            from unpivot_staffing left join user_roles on unpivot_staffing.user_id = user_roles.user_id
        ),
    
        orders as (
            select 
                id, 
                name,
                status,
                stage,
                coalesce(c.tier, a.tier, 'Tier 2') as tier
            from svc_solution.ods.delivery_order_act as a 
            left join
            (
                select
                    cast(_airbyte_data:project_id as string) as project_id,
                    cast(_airbyte_data:tier as string) as tier
                from dmn_core_analytics.raw_airbyte._airbyte_raw_tt_projects_view
                qualify row_number() over (partition by project_id order by _airbyte_emitted_at desc) = 1
            ) as c on a.id = c.project_id
            where a.client_id not in ('019889a2-485a-74db-a7eb-9b5c0dcc8e04', '0198a43d-3b6f-7994-a649-bded73854d96')
                and id not in ('019b9e50-301e-72d8-ba63-6c042921a4cd', '019b9e54-46a9-761d-bcb8-137439f96eb2', '019b9e54-eed8-7fd6-a2fe-0529ad346764', '019b9e55-9365-7e0e-b4b8-14b9ee15dbc1', '019b9e56-c7f4-7565-860d-088423b58b95', '019bb68f-0dcc-7c7c-8720-e11e4253f2b0')
                and status not in ('ARCHIVED', 'COMPLETED', 'CANCELED')
        ),
    
        users_occupation as (
            select
                user_id,
                sum(occupation/role_amount) as occupation
            from
            (
                select
                    project_id,
                    user_id,
                    user_name,
                    user_email,
                    project_role,
                    status,
                    stage,
                    tier,
                    sum(1) over (partition by project_id, project_role) as role_amount 
                from staffing_join inner join orders on staffing_join.project_id = orders.id
            ) as a
            left join occupation_coeficients on occupation_coeficients.role = a.project_role and occupation_coeficients.tier = a.tier and occupation_coeficients.stage = a.stage and occupation_coeficients.status = a.status
            group by user_id
        ),
    
        employees as (
            select
                user_roles.*,
                case
                    when user_role = 'Quality & Training' then 'qm'
                    when user_role = 'Delivery Project Manager' then 'dpm'
                    when user_role in ('Solution Engineer', 'Senior Solution Engineer') then 'soe'
                    when user_role in ('Workforce Coordinator', 'Workforce Manager') then 'wfm'
                    when user_role in ('Software Engineer', 'Software Engineer Lead') then 'se'
                else 'other'
                end as project_role
            from
            (
                select distinct
                    cast(_airbyte_data:`/root/email`:value as string) as email
                from svc_finance.raw_hibob._airbyte_raw_employees
                where _airbyte_emitted_at::date >= current_date() - interval 1 day
            ) as emps
            inner join user_roles on emps.email = user_roles.user_email
            where user_role in ('Quality & Training', 'Delivery Project Manager', 'Solution Engineer', 'Senior Solution Engineer', 'Workforce Coordinator', 'Workforce Manager', 'Software Engineer', 'Software Engineer Lead')
    
        ),
    
        vacations as (
            select distinct
                email,
                vacation_date
            from
            (
                select
                    employee_id,
                    explode(filter(sequence(start_date, end_date), d -> dayofweek(d) not in (1, 7))) as vacation_date
                from
                (
                    select
                        cast(_airbyte_data:employeeId as string) as employee_id,
                        cast(_airbyte_data:startDate as date) as start_date,
                        cast(_airbyte_data:endDate as date) as end_date
                    from svc_finance.raw_hibob._airbyte_raw_whos_out_next_7_days
                    where date(_airbyte_emitted_at)= (select date(max(_airbyte_emitted_at)) from svc_finance.raw_hibob._airbyte_raw_whos_out_next_7_days)
                )
            ) as v 
            inner join 
            (
                select
                    cast(_airbyte_data:id as string) as id,
                    max_by(cast(_airbyte_data:`/root/email`:value as string), _airbyte_emitted_at) as email
                from svc_finance.raw_hibob._airbyte_raw_employees
                group by 1
            ) as ie on v.employee_id = ie.id
            where vacation_date between current_date() and current_date() + interval 6 days
        ),
    
        final_table as (
            select
                employees.*,
                coalesce(occupation, 0.) as project_occupation,
                coalesce(pto, 0.) as pto,
                coalesce(occupation, 0.) + coalesce(pto, 0.) as occupation,
                if(next_work_day = current_date()::string, 'today', coalesce(next_work_day, 'today')) as next_work_day 
            from employees left join users_occupation on employees.user_id = users_occupation.user_id
            left join 
            (
                select 
                    email, 
                    sum(1)/5 as pto,
                    coalesce(array_min(array_except(filter(sequence(current_date(), current_date() + interval 6 days), d -> dayofweek(d) not in (1, 7)),array_agg(vacation_date)))::string, 'week+') as next_work_day
                    from vacations group by email
            ) as v on employees.user_email = v.email
        )
    
        
    
    select * from final_table order by occupation asc
    ```