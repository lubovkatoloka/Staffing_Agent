
    with 
    
    user_roles_pre as (
            select
                cast(_airbyte_data:user_id as string) as user_id,
                cast(_airbyte_data:rolename as string) as user_role,
                cast(_airbyte_data:email as string) as user_email,
                cast(_airbyte_data:name as string) as user_name
            from dmn_core_analytics.raw_airbyte._airbyte_raw_tt_users_view
            qualify row_number() over (partition by user_id order by _airbyte_emitted_at desc) = 1
        ),
    
    user_id_email_link as (
        select 
            user_email, 
            any_value(user_role) ignore nulls as user_role,
            any_value(user_name) ignore nulls as user_name    
            from user_roles_pre
            group by user_email
            having user_role in ('Senior Solution Engineer', 'Solution Engineer', 'Solution Data Analyst', 'Project Analyst', 'Delivery Director', 'Director', 'Quality Coordinator', 'Q&T', 'Delivery Project Manager', 'Workforce Coordinator', 'Workforce Manager', 'Software Engineer', 'Quality & Training')
    ),
    
        vacations as (
            select distinct user_name, user_role
            from
                (
                    select distinct
                        cast(_airbyte_data:employeeemail as string) as user_email
                    from svc_finance.raw_hibob._airbyte_raw_out_today
                    where
                        cast(_airbyte_data:policytypedisplayname as string) != 'Business trip'
                        and _airbyte_emitted_at::date = current_date()
                ) as v
            inner join user_id_email_link on v.user_email = user_id_email_link.user_email
        )
    
    select * from vacations
    ```