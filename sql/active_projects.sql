select 
    id,
    stage,
    status,
    stage in ('building', 'stabilisation_delivery')  and status not in ('ARCHIVED', 'CANCELED', 'COMPLETED') as is_active
from svc_solution.ods.delivery_order_act