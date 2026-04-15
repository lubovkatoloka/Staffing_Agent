-- Project staffing: one row per project_id with pivoted role lists (users_list).
-- Paste updates from Notion Decision Logic. Env: STAFFING_PROJECT_STAFFING_SQL_PATH

with
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
                select project_id, 'responsible' as role, responsible_user_id as user_id
                from project_staffing

                union all

                select project_id, 'director' as role, director_user_id as user_id
                from project_staffing

                union all

                select project_id, 'bizdev' as role, bizdev_user_id as user_id
                from project_staffing

                union all

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
            project_id,
            project_role,
            listagg(
                distinct
                case
                    when project_role != 'other' then user_name
                    when user_role = 'Quality & Training' then concat(user_name, ' - qm')
                    when user_role = 'Delivery Project Manager' then concat(user_name, ' - dpm')
                    when user_role in ('Solution Engineer', 'Senior Solution Engineer') then concat(user_name, ' - soe')
                    when user_role in ('Workforce Coordinator', 'Workforce Manager') then concat(user_name, ' - wfm')
                    when user_role = 'Software Engineer' then concat(user_name, ' - se')
                    else concat(user_name, ' - ', user_role)
                end,
                ', '
            ) as users_list
        from
            (
                select
                    unpivot_staffing.*,
                    user_role,
                    user_email,
                    user_name
                from unpivot_staffing
                left join user_roles on unpivot_staffing.user_id = user_roles.user_id
            )
        group by 1, 2
    ),

    timespend as (
        select distinct
            project_id
        from dmn_core_analytics.ods.delivery_teams_work_hours_log
        where report_dt >= current_date() - interval 7 days
    ),

    costs as (
        select distinct
            delivery_order_id as project_id
        from dmn_core_analytics.cdm.all_costs
        where work_dt >= current_date() - interval 7 days
            and payment_status in ('paid', 'deferred')
            and delivery_order_id is not null
    ),

    orders as (
        select
            a.id,
            a.name,
            client_name,
            status,
            stage,
            coalesce(a.tier, c.tier) as tier,
            created_at::date as created_at,
            dl.deadline::date as deadline,
            er as expected_revenue,
            timespend.project_id is not null as has_timespend,
            costs.project_id is not null as has_costs,
            timespend.project_id is not null or costs.project_id is not null as has_time_or_costs,
            attio.name as deal_name,
            attio.attio_id
        from svc_solution.ods.delivery_order_act as a
        left join (
            select
                delivery_order_id,
                max_by(last_version_deadline, plan_week_dt) as deadline,
                max_by(last_version_target_items_count * price_per_item, plan_week_dt) as er
            from dmn_core_analytics.cdm.delivery_plan_act
            group by delivery_order_id
        ) as dl on a.id = dl.delivery_order_id
        left join (
            select id as client_id, name as client_name
            from svc_solution.ods.delivery_order_client_act
        ) as b on a.client_id = b.client_id
        left join (
            select
                cast(_airbyte_data:project_id as string) as project_id,
                cast(_airbyte_data:tier as string) as tier
            from dmn_core_analytics.raw_airbyte._airbyte_raw_tt_projects_view
            qualify row_number() over (partition by project_id order by _airbyte_emitted_at desc) = 1
        ) as c on a.id = c.project_id
        left join timespend on a.id = timespend.project_id
        left join costs on a.id = costs.project_id
        left join (
            select id, any_value(name) as name, any_value(attio_id) as attio_id
            from svc_solution.ods.delivery_order_deal_link
            group by 1
        ) as attio on a.deal_id = attio.id
        where a.client_id not in ('019889a2-485a-74db-a7eb-9b5c0dcc8e04', '0198a43d-3b6f-7994-a649-bded73854d96')
            and a.id not in (
                '019b9e50-301e-72d8-ba63-6c042921a4cd',
                '019b9e54-46a9-761d-bcb8-137439f96eb2',
                '019b9e54-eed8-7fd6-a2fe-0529ad346764',
                '019b9e55-9365-7e0e-b4b8-14b9ee15dbc1',
                '019b9e56-c7f4-7565-860d-088423b58b95',
                '019bb68f-0dcc-7c7c-8720-e11e4253f2b0'
            )
            -- Только активные заказы (как в occupation.sql); иначе тянутся COMPLETED/ARCHIVED/CANCELED в списки ролей.
            and coalesce(a.status, '') not in ('ARCHIVED', 'COMPLETED', 'CANCELED')
    ),

    final_table as (
        select
            staffing_join.*,
            name,
            client_name,
            status,
            stage,
            tier,
            created_at,
            deadline,
            expected_revenue,
            has_timespend,
            has_costs,
            has_time_or_costs,
            deal_name,
            attio_id
        from staffing_join
        inner join orders on staffing_join.project_id = orders.id
    )

select
    project_id,
    any_value(name) as name,
    any_value(client_name) as client_name,
    any_value(status) as status,
    any_value(stage) as stage,
    any_value(tier) as tier,
    any_value(created_at) as created_at,
    any_value(deadline) as deadline,
    any_value(expected_revenue) as expected_revenue,
    any_value(has_timespend) as has_timespend,
    any_value(has_costs) as has_costs,
    any_value(has_time_or_costs) as has_time_or_costs,
    any_value(deal_name) as deal_name,
    any_value(attio_id) as attio_id,
    max(if(project_role = 'responsible', users_list, '')) as responsible,
    max(if(project_role = 'director', users_list, '')) as director,
    max(if(project_role = 'bizdev', users_list, '')) as bizdev,
    max(if(project_role = 'dpm', users_list, '')) as dpm,
    max(if(project_role = 'soe', users_list, '')) as soe,
    max(if(project_role = 'wfm', users_list, '')) as wfm,
    max(if(project_role = 'qm', users_list, '')) as qm,
    max(if(project_role = 'other', users_list, '')) as other
from final_table
group by project_id
