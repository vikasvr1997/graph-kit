"""Independent SQL references and unambiguous complex freight questions."""
CASES = [
{
'id':'customer_lane_margin',
'question': 'Across all loads, which 10 customer-type and origin-state groups have the largest revenue minus fuel spending? Join customers to loads and routes. Sum fuel_purchases.total_cost through trips.load_id, treating missing fuel as zero. Count each load and its revenue once. Return customer_type, origin_state, load_count, revenue, fuel_cost, margin, with money rounded to 2 decimals. Order by margin descending, then customer_type and origin_state ascending. This is revenue minus fuel only, not net profit.',
'sql': '''WITH fuel_by_trip AS (
 SELECT trip_id, SUM(total_cost) AS fuel_cost FROM {fuel_purchases} GROUP BY trip_id
), fuel_by_load AS (
 SELECT t.load_id, SUM(COALESCE(f.fuel_cost,0)) AS fuel_cost FROM {trips} t
 LEFT JOIN fuel_by_trip f ON t.trip_id=f.trip_id GROUP BY t.load_id
)
SELECT c.customer_type, r.origin_state, COUNT(*) AS load_count,
 ROUND(SUM(l.revenue),2) AS revenue, ROUND(SUM(COALESCE(f.fuel_cost,0)),2) AS fuel_cost,
 ROUND(SUM(l.revenue)-SUM(COALESCE(f.fuel_cost,0)),2) AS margin
FROM {loads} l JOIN {customers} c ON l.customer_id=c.customer_id
JOIN {routes} r ON l.route_id=r.route_id LEFT JOIN fuel_by_load f ON l.load_id=f.load_id
GROUP BY c.customer_type,r.origin_state ORDER BY margin DESC,c.customer_type,r.origin_state LIMIT 10'''
},
{
'id':'facility_operator_delays',
'question':'Across operational events with a matching trip, driver and facility, which 10 facility-state and driver-employment-status groups have the most detention minutes? Join events.trip_id to trips, trips.driver_id to drivers, and events.facility_id to facilities. Return state, employment_status, event_count, late_events (on_time_flag=false), detention_minutes (sum, missing treated as zero). Order by detention_minutes descending, then state and employment_status ascending.',
'sql': '''SELECT f.state,d.employment_status,COUNT(*) AS event_count,
 SUM(CASE WHEN e.on_time_flag=FALSE THEN 1 ELSE 0 END) AS late_events,
 SUM(COALESCE(e.detention_minutes,0)) AS detention_minutes
FROM {events} e JOIN {trips} t ON e.trip_id=t.trip_id
JOIN {drivers} d ON t.driver_id=d.driver_id JOIN {facilities} f ON e.facility_id=f.facility_id
GROUP BY f.state,d.employment_status ORDER BY detention_minutes DESC,f.state,d.employment_status LIMIT 10'''
},
{
'id':'customer_service',
'question':'For each customer_type and primary_freight_type, summarize all loads and their operational events. Return customer_type, primary_freight_type, load_count, loads_with_late_event (at least one event whose on_time_flag=false), revenue (sum loads.revenue once per load, rounded to 2 decimals), detention_minutes (sum event detention, missing treated as zero). Include loads without events. Order by loads_with_late_event descending, then customer_type and primary_freight_type ascending. Limit 10.',
'sql': '''WITH event_by_load AS (
 SELECT load_id, MAX(CASE WHEN on_time_flag=FALSE THEN 1 ELSE 0 END) AS has_late,
 SUM(COALESCE(detention_minutes,0)) AS detention_minutes FROM {events} GROUP BY load_id
)
SELECT c.customer_type,c.primary_freight_type,COUNT(*) AS load_count,
 SUM(COALESCE(e.has_late,0)) AS loads_with_late_event,ROUND(SUM(l.revenue),2) AS revenue,
 SUM(COALESCE(e.detention_minutes,0)) AS detention_minutes
FROM {customers} c JOIN {loads} l ON c.customer_id=l.customer_id
LEFT JOIN event_by_load e ON l.load_id=e.load_id
GROUP BY c.customer_type,c.primary_freight_type
ORDER BY loads_with_late_event DESC,c.customer_type,c.primary_freight_type LIMIT 10'''
},
{
'id':'driver_fuel_detention',
'question':'Which 10 drivers have the greatest fuel spending across their trips? Aggregate fuel_purchases.total_cost by trip_id and events.detention_minutes by trip_id separately before joining to trips and drivers to avoid multiplying rows. Include trips without fuel purchases or events, treating missing amounts as zero. Return driver_id, employment_status, trip_count, miles (sum actual_distance_miles), fuel_cost (rounded to 2 decimals), detention_minutes. Order by fuel_cost descending then driver_id ascending.',
'sql': '''WITH fuel_by_trip AS (SELECT trip_id,SUM(total_cost) AS fuel_cost FROM {fuel_purchases} GROUP BY trip_id),
 event_by_trip AS (SELECT trip_id,SUM(COALESCE(detention_minutes,0)) AS detention_minutes FROM {events} GROUP BY trip_id)
SELECT d.driver_id,d.employment_status,COUNT(*) AS trip_count,SUM(t.actual_distance_miles) AS miles,
 ROUND(SUM(COALESCE(f.fuel_cost,0)),2) AS fuel_cost,SUM(COALESCE(e.detention_minutes,0)) AS detention_minutes
FROM {trips} t JOIN {drivers} d ON t.driver_id=d.driver_id
LEFT JOIN fuel_by_trip f ON t.trip_id=f.trip_id LEFT JOIN event_by_trip e ON t.trip_id=e.trip_id
GROUP BY d.driver_id,d.employment_status ORDER BY fuel_cost DESC,d.driver_id LIMIT 10'''
},
{
'id':'lane_efficiency',
'question':'Which 10 origin-state and destination-state lanes have the longest average actual trip duration? Join routes to loads using route_id and trips to loads using load_id. Return origin_state, destination_state, trip_count, miles (sum actual_distance_miles), avg_duration_hours (average actual_duration_hours rounded to 2 decimals), avg_mpg (average average_mpg rounded to 2 decimals). Order by avg_duration_hours descending then origin_state and destination_state ascending.',
'sql': '''SELECT r.origin_state,r.destination_state,COUNT(*) AS trip_count,
 SUM(t.actual_distance_miles) AS miles,ROUND(AVG(t.actual_duration_hours),2) AS avg_duration_hours,
 ROUND(AVG(t.average_mpg),2) AS avg_mpg FROM {routes} r JOIN {loads} l ON r.route_id=l.route_id
JOIN {trips} t ON l.load_id=t.load_id GROUP BY r.origin_state,r.destination_state
ORDER BY avg_duration_hours DESC,r.origin_state,r.destination_state LIMIT 10'''
},
]
