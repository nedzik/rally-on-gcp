import datetime
from random import choice

import pandas as pd
from google.cloud import bigquery


def is_within_date_range(date_range, date):
    if len(date_range) == 2:
        return date_range[0].date() <= date <= date_range[1].date()
    return True


def prepare_throughput_data(bq_data, date_range):
    start_date = min(bq_data.keys())
    start_date = min(start_date, date_range[0].date()) if len(date_range) == 2 else start_date
    end_date = max(bq_data.keys())
    end_date = max(end_date, date_range[1].date()) if len(date_range) == 2 else end_date
    dates = [start_date + datetime.timedelta(days=x) for x in range((end_date - start_date).days + 1)]
    dates = [x for x in dates if x.isoweekday() < 6]
    return [bq_data.get(x, 0) for x in dates]


def get_throughput_data_from_bq(bq_client, path_to_root, sample_date_range):
    query = f'''
        SELECT departure as completion_date, count(*) as throughput 
        FROM 
          (
            SELECT rally_id, EXTRACT(DATE from MAX(timestamp) AT TIME ZONE "America/Chicago") as departure 
            FROM rally.schedule_events 
            WHERE schedule_state_name = 'ACCEPTED' AND event_type_name = 'ARRIVAL' AND 
                STARTS_WITH(path_to_root, @PATH_TO_ROOT)
            GROUP BY rally_id
          ) as departures
        GROUP BY
          departure
        ORDER BY 
          departure
    '''
    job_config = bigquery.QueryJobConfig()
    job_config.query_parameters = [bigquery.ScalarQueryParameter('PATH_TO_ROOT', 'STRING', path_to_root)]
    return dict([
        (x.completion_date, x.throughput) for x in bq_client.query(query, job_config=job_config) if
        is_within_date_range(sample_date_range, x.completion_date)
    ])


def run_simulation(throughput_data, backlog_size):
    remaining_backlog = backlog_size
    days = 0
    current_date = datetime.date.today()
    # TODO: limit the number of cycles to avoid infinite loops
    while remaining_backlog > 0:
        remaining_backlog -= choice(throughput_data) if current_date.isoweekday() < 6 else 0
        current_date += datetime.timedelta(days=1)
        days += 1
    return days


def format_date_range(date_range):
    return 'all available' if len(date_range) != 2 else \
        f'''within [{date_range[0]:%Y-%m-%d}, {date_range[1]:%Y-%m-%d}]'''


def get_date(ci_95_lower):
    return datetime.date.today() + datetime.timedelta(days=ci_95_lower)


def print_information_header(backlog_size, count, path_to_root, sample_date_range):
    print(f' - starting the forecaster ...')
    print(f' --- backlog size: {backlog_size} items')
    print(f''' --- path to root starting with: '{path_to_root}' ''')
    print(f''' --- throughput data: {format_date_range(sample_date_range)}''')
    print(f' --- experiment count: {count}')


def print_simulation_results(results):
    summary = pd.DataFrame({'effort': results}).describe(percentiles=[.025, 0.05, 0.075, 0.925, 0.95, .975])
    ci_95_lower = next(summary.filter(regex=r'^2\.5%$', axis=0).itertuples()).effort
    ci_95_upper = next(summary.filter(regex=r'^97\.5%$', axis=0).itertuples()).effort
    print(f' - results:')
    print(f'''95% CI (days): [{ci_95_lower:.0f}, {ci_95_upper:.0f}]''')
    print(f'''95% CI (dates from today): [{get_date(ci_95_lower)}, {get_date(ci_95_upper)}]''')
