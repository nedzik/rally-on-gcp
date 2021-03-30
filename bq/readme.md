# Sample Queries

Please, feel free to share your queries. 

## General Flow of Rally Events

Replace ```<value>``` with the path to your subproject.

```sql
SELECT * FROM rally.schedule_events 
WHERE STARTS_WITH(path_to_root, "<value>") 
ORDER BY rally_id, timestamp, event_type_id, schedule_state_id;
```

## Data for Building Cycle Time Scatter-Plot or Histogram

Add ```STARTS_WITH(path_to_root, "<value>")``` to ```WHERE``` clause to filter.

```sql
CREATE VIEW rally.schedule_cycle_times AS
SELECT 
  arrivals.rally_id as rally_id, 
  TIMESTAMP_DIFF(departures.departure, arrivals.arrival, DAY) + 1 as cycle_time_in_days, 
  EXTRACT(DATE FROM departures.departure AT TIME ZONE "America/Chicago") as completion_date,
  arrivals.path
FROM 
  (
    SELECT rally_id, path_to_root as path, MIN(timestamp) as arrival 
    FROM rally.schedule_events 
    WHERE schedule_state_name = 'IN-PROGRESS' AND event_type_name = 'ARRIVAL' 
    GROUP BY rally_id, path_to_root
  ) as arrivals,
  (
    SELECT rally_id, MAX(timestamp) as departure 
    FROM rally.schedule_events 
    WHERE schedule_state_name = 'ACCEPTED' AND event_type_name = 'ARRIVAL' 
    GROUP BY rally_id
  ) as departures
WHERE 
  arrivals.rally_id = departures.rally_id
```

```sql
CREATE VIEW rally.schedule_cycle_time_frequencies AS 
SELECT cycle_time_in_days, path, count(*) as frequency FROM 
(
SELECT 
  arrivals.rally_id as rally_id,
  TIMESTAMP_DIFF(departures.departure, arrivals.arrival, DAY) + 1 as cycle_time_in_days, 
  path
FROM 
  (
    SELECT rally_id, path_to_root as path, MIN(timestamp) as arrival 
    FROM rally.schedule_events 
    WHERE schedule_state_name = 'IN-PROGRESS' AND event_type_name = 'ARRIVAL' 
    GROUP BY rally_id, path_to_root
  ) as arrivals,
  (
    SELECT rally_id, MAX(timestamp) as departure 
    FROM rally.schedule_events 
    WHERE schedule_state_name = 'ACCEPTED' AND event_type_name = 'ARRIVAL' 
    GROUP BY rally_id
  ) as departures
WHERE 
  arrivals.rally_id = departures.rally_id and path != ''
) 
WHERE 
  cycle_time_in_days > 0 
GROUP BY
  cycle_time_in_days, path
```

## Throughput Distribution by Date (for Monte-Carlo Simulations)

Note that it just a sample and requires future work. For example, we need to exclude items that did not
flow through the system (i.e., did not enter ```IN-PROGRESS``` and ```COMPLETED``` states)

Add ```STARTS_WITH(path_to_root, "<value>")``` to ```WHERE``` clause to filter.

```sql
SELECT 
  departure as completion_date,
  count(*) as throughput 
FROM 
  (
    SELECT rally_id, EXTRACT(DATE from MAX(timestamp) AT TIME ZONE "America/Chicago") as departure 
    FROM rally.schedule_events 
    WHERE schedule_state_name = 'ACCEPTED' AND event_type_name = 'ARRIVAL' 
    GROUP BY rally_id
  ) as departures
GROUP BY
  departure
ORDER BY 
  departure
```

## Report Deviations from the Recommended Flow Patterns

```sql
SELECT 
  rally_id, ARRAY_TO_STRING(state_sequence, '->') as flow, path_to_root 
FROM 
  (
    SELECT 
      rally_id, path_to_root, ARRAY_AGG(SUBSTR(schedule_state_name, 0, 2) ORDER BY(timestamp)) as state_sequence 
    FROM 
      rally.schedule_events 
    WHERE 
      event_type_name = 'ARRIVAL' and path_to_root NOT IN ( '', 'Customer Data Hub', 'Customer Experience Manager' )
    GROUP BY 
      rally_id, path_to_root 
  )
WHERE 
  ARRAY_TO_STRING(state_sequence, '->') NOT IN ( 'DE->IN', 'DE->IN->CO', 'DE->IN->CO->AC', 'DE->IN->CO->AC->RE' )
ORDER BY 
  path_to_root
```

## Cycle Time vs. Estimate

```sql
SELECT 
    cycle_times.rally_id AS rally_id, 
    CAST(cycle_time_in_days AS float64) AS cycle_time_in_days, 
    CAST(plan_estimate AS float64) AS estimate_in_story_points, 
    cycle_times.path AS path 
FROM 
    rally.schedule_cycle_times AS cycle_times, 
    rally.items AS items 
WHERE 
    cycle_times.rally_id = items.rally_id AND plan_estimate IS NOT NULL AND plan_estimate != 0
```

## Cycle Time Frequencies (To Check the Histogram)

```sql
SELECT 
    COUNT(*) AS frequency, cycle_time_in_days 
FROM 
    rally.schedule_cycle_times 
WHERE 
    path = 'your path' 
GROUP BY 
    cycle_time_in_days 
ORDER BY 
    cycle_time_in_days
```