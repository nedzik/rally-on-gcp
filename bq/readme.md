# Sample Queries

Please, feel free to share your queries. 

## General Flow of Rally Events

Replace ```<value>``` with the path to your subproject.

```sql
SELECT rally_id, schedule_state_name, event_type_name, timestamp, author, path_to_root FROM rally.events 
WHERE STARTS_WITH(path_to_root, "<value>") 
ORDER By rally_id, timestamp, schedule_state_id;
```

## Data for Building Cycle Time Scatter-Plot or Histogram

Add ```STARTS_WITH(path_to_root, "<value>")``` to ```WHERE``` clause to filter.

```sql
SELECT 
  arrivals.rally_id as rally_id, 
  TIMESTAMP_DIFF(departures.departure, arrivals.arrival, DAY) + 1 as cycle_time_in_days, 
  EXTRACT(DATE FROM departures.departure AT TIME ZONE "America/Chicago") as completion_date 
FROM 
  (
    SELECT rally_id, MIN(timestamp) as arrival 
    FROM rally.events 
    WHERE schedule_state_name = 'IN-PROGRESS' AND event_type_name = 'ARRIVAL' 
    GROUP BY rally_id
  ) as arrivals,
  (
    SELECT rally_id, MAX(timestamp) as departure 
    FROM rally.events 
    WHERE schedule_state_name = 'ACCEPTED' AND event_type_name = 'ARRIVAL' 
    GROUP BY rally_id
  ) as departures
WHERE 
  arrivals.rally_id = departures.rally_id
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
    FROM rally.events 
    WHERE schedule_state_name = 'ACCEPTED' AND event_type_name = 'ARRIVAL' 
    GROUP BY rally_id
  ) as departures
GROUP BY
  departure
ORDER BY 
  departure
```