#!/usr/bin/env python

import datetime
import functools
import operator
import os
import re

import click
import pytz
from google.cloud import bigquery
from pyral import Rally, rallyWorkset

from forecast import prepare_throughput_data, get_throughput_data_from_bq, run_simulation
from forecast import print_information_header, print_simulation_results

UTC = pytz.UTC
SCHEDULE_EVENTS_TABLE = 'rally.schedule_events'
SCHEDULE_STATE_CHANGE_EXPR = r'SCHEDULE STATE changed from \[(.+?)\] to \[(.+?)\]'
READY_CHANGE_EXPR = r'READY changed from \[(.+?)\] to \[(.+?)\]'
BLOCKED_STATE_CHANGE_EXPR = r'BLOCKED changed from \[(.+?)\] to \[(.+?)\]'
TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%S.%fZ'
UNKNOWN = 'UNKNOWN'
PATHS_TO_ROOT = {}
SCHEDULE_STATE_ID_MAP = {
    'IDEA': 1,
    'DEFINED': 2,
    'IN-PROGRESS': 3,
    'COMPLETED': 4,
    'ACCEPTED': 5,
    'RELEASED-TO-PRODUCTION': 6
}
EVENT_TYPE_ID_MAP = {
    'DEPARTURE': 1,
    'OTHER': 2,
    'ARRIVAL': 3
}
STATE_ID_MAP = {
    'true': 'ON',
    'false': 'OFF'
}


# Helpers - Rally
def initialize_rally():
    print(f' - initializing Rally API ...')
    server, user, password, apikey, workspace, project = rallyWorkset([])
    rally = Rally(server=server, apikey=apikey, workspace=workspace, project=project)
    return rally, workspace, project


def get_items_from_rally(rally, workspace, project, item_type, from_date, fields):
    query = f'''((LastUpdateDate >= "{from_date}") AND (FlowState.ScheduleStateMapping != "Idea"))'''
    print(f' - retrieving {item_type} that match query: "{query}" ...')
    return rally.get(item_type, fetch=fields, workspace=workspace, project=project, projectScopeDown=True, query=query)


def item(rally_item):
    return rally_item.FormattedID, rally_item.LastUpdateDate, rally_item


def get_stories_and_defects_from_rally(rally, workspace, project, from_date):
    fields = "FormattedID,LastUpdateDate,RevisionHistory,Owner,Project"
    stories = [item(i) for i in get_items_from_rally(rally, workspace, project, 'UserStory', from_date, fields)]
    defects = [item(i) for i in get_items_from_rally(rally, workspace, project, 'Defect', from_date, fields)]
    return stories + defects


# Helpers - Rally to BQ conversion
def to_bq_row(rally_id, event_type, schedule_state, timestamp, path, blocked_state, ready_state):
    return {
        u'rally_id': rally_id,
        u'schedule_state_id': SCHEDULE_STATE_ID_MAP.get(schedule_state, 99),
        u'schedule_state_name': schedule_state,
        u'event_type_id': EVENT_TYPE_ID_MAP.get(event_type, 99),
        u'event_type_name': event_type,
        u'timestamp': timestamp,
        u'path_to_root': path,
        u'blocked_state': blocked_state,
        u'ready_state': ready_state
    }


def get_path_to_root_project(rally_project, root_project_name, path=''):
    project_name = rally_project.Name
    if project_name:
        if project_name == root_project_name:
            PATHS_TO_ROOT[project_name] = path[:-1]
            return path[:-1]
        else:
            if project_name in PATHS_TO_ROOT: return PATHS_TO_ROOT[project_name]
            return get_path_to_root_project(rally_project.Parent, root_project_name, f'{project_name}/{path}')
    else:
        return path


def extract_blocked_state(revision):
    return extract_state(revision, BLOCKED_STATE_CHANGE_EXPR)


def extract_ready_state(revision):
    return extract_state(revision, READY_CHANGE_EXPR)


def extract_state(revision, expr):
    state = next((re.finditer(expr, revision.Description)), None)
    return STATE_ID_MAP.get(state[2], UNKNOWN) if state else None


def extract_bq_rows_from_revision(rally_item_id, revision, path_to_root):
    schedule_state_change = next((re.finditer(SCHEDULE_STATE_CHANGE_EXPR, revision.Description)), None)
    blocked_state_to = extract_blocked_state(revision)
    ready_state_to = extract_ready_state(revision)
    if schedule_state_change:
        return [
            to_bq_row(
                rally_item_id, 'DEPARTURE', schedule_state_change[1].upper(), revision.CreationDate,
                path_to_root, None, None
            ),
            to_bq_row(
                rally_item_id, 'ARRIVAL', schedule_state_change[2].upper(), revision.CreationDate,
                path_to_root, blocked_state_to, ready_state_to
            )
        ]
    elif blocked_state_to or ready_state_to:
        return [
            to_bq_row(
                rally_item_id, 'OTHER', UNKNOWN, revision.CreationDate, path_to_root,
                blocked_state_to, ready_state_to
            )
        ]
    return []


def propagate_schedule_states(rows):
    for index in range(1, len(rows)):
        current, previous = rows[index], rows[index - 1]
        if current[u'schedule_state_name'] == UNKNOWN and previous[u'schedule_state_name'] != UNKNOWN:
            current[u'schedule_state_id'] = previous[u'schedule_state_id']
            current[u'schedule_state_name'] = previous[u'schedule_state_name']
    return rows


def extract_bq_rows_from_item(item_to_process, root_project_name):
    item_id, last_updated, rally_item = item_to_process
    path_to_root = get_path_to_root_project(rally_item.Project, root_project_name)
    revisions = rally_item.RevisionHistory.Revisions
    revisions.reverse()
    return propagate_schedule_states(functools.reduce(operator.iconcat, [
        extract_bq_rows_from_revision(item_id, r, path_to_root) for r in revisions
    ], []))


def extract_bq_rows_from_items(items, root_project_name):
    bq_rows = []
    print(f' - converting {len(items)} rally items into BQ row dictionaries ...')
    for index in range(0, len(items)):
        if index and index % 10 == 0: print(f' --- processed {index} of {len(items)} items ...')
        bq_rows += extract_bq_rows_from_item(items[index], root_project_name)
    return bq_rows


# Helpers - BQ operations
def events_table_is_empty(client):
    print(f' - checking there is no data in {SCHEDULE_EVENTS_TABLE} ...')
    query = f'''SELECT count(*) as row_count from {SCHEDULE_EVENTS_TABLE}'''
    return next((x.row_count for x in client.query(query)), -1) == 0


def get_latest_timestamps_from_bq(bq_client, rally_items):
    query = f'''
            SELECT rally_id, max(timestamp) AS timestamp FROM {SCHEDULE_EVENTS_TABLE}
            WHERE rally_id IN UNNEST(@CANDIDATES)
            GROUP BY rally_id
        '''
    job_config = bigquery.QueryJobConfig()
    job_config.query_parameters = [bigquery.ArrayQueryParameter('CANDIDATES', 'STRING', [x[0] for x in rally_items])]
    return dict([(x.rally_id, x.timestamp) for x in bq_client.query(query, job_config=job_config)])


def insert_rows_into_bq(bq_client, bq_rows):
    batch_size = 10000
    print(f' - inserting {len(bq_rows)} row(s) into {SCHEDULE_EVENTS_TABLE} ...')
    for index in range(0, len(bq_rows), batch_size):
        batch_rows = bq_rows[index:index + batch_size]
        print(f' --- inserting next {len(batch_rows)} rows starting from offset {index} ...')
        errors = bq_client.insert_rows_json(SCHEDULE_EVENTS_TABLE, batch_rows, row_ids=[None] * len(batch_rows))
        if errors:
            print(f' --- aborting due to the errors encountered while inserting rows:')
            for x in errors: print(f' ----- {x}')
            return
        print(f' --- inserted {len(batch_rows)} row(s) into {SCHEDULE_EVENTS_TABLE}.')
    print(f' - done inserting {len(bq_rows)} row(s) into {SCHEDULE_EVENTS_TABLE}.')


# Helpers - Scheduler Logic
def extract_new_bq_rows_from_candidates(candidate_rally_items, timestamps_by_id, root_project_name):
    bq_rows = []
    for candidate_item in candidate_rally_items:
        rally_id, rally_last_updated, rally_item = candidate_item
        rally_last_updated = to_datetime_utc(rally_last_updated)
        print(f' - considering Rally item {rally_id}, last updated in Rally on {rally_last_updated} ...')
        bq_last_updated = timestamps_by_id.get(rally_id, None)
        if not bq_last_updated or bq_last_updated < rally_last_updated:
            message = 'a brand new item' if not bq_last_updated else f'the item has new events after {bq_last_updated}'
            print(f''' --- {message}. Processing ...''')
            bq_rows += extract_new_bq_rows_from_candidate(
                candidate_item, bq_last_updated, rally_last_updated, root_project_name)
        else:
            print(f' --- up-to-date in {SCHEDULE_EVENTS_TABLE} (last time updated on {bq_last_updated}. Skipping ...')
    return bq_rows


def extract_new_bq_rows_from_candidate(candidate_rally_item, bq_last_updated, rally_last_updated, root_project_name):
    bq_rows_from_item = extract_bq_rows_from_item(candidate_rally_item, root_project_name)
    print(f' --- all items ({len(bq_rows_from_item)}) ...')
    for x in bq_rows_from_item: print(x)
    selected_bq_rows_from_item = [x for x in bq_rows_from_item if to_datetime_utc(x[u'timestamp']) > bq_last_updated] \
        if bq_last_updated and bq_last_updated < rally_last_updated else bq_rows_from_item
    print(f' --- selected items ({len(selected_bq_rows_from_item)})...')
    for x in selected_bq_rows_from_item: print(x)
    return selected_bq_rows_from_item


def to_datetime_utc(timestamp):
    return datetime.datetime.strptime(timestamp, TIMESTAMP_FORMAT).replace(tzinfo=UTC)


# Cloud Function handler for scanning for recently modified stories/defects
# Takes the scan offset from RALLY_SCAN_OFFSET environment variable
# For each found story/defect, issues a PubSub message that updater Cloud Function will process
# noinspection PyUnusedLocal
def scheduler(event, context):
    print(' - starting the scheduler ...')
    bq_client = bigquery.Client()
    if events_table_is_empty(bq_client):
        print(f' --- {SCHEDULE_EVENTS_TABLE} is still empty. Please perform the initial data load. Exiting ...')
        return
    rally, workspace, project = initialize_rally()
    rally_scan_offset = int(os.getenv('RALLY_SCAN_OFFSET', '1'))
    print(' - scanning for candidates with new events ...')
    from_date = (datetime.datetime.now() - datetime.timedelta(days=rally_scan_offset)).strftime('%Y-%m-%d')
    candidate_rally_items = get_stories_and_defects_from_rally(rally, workspace, project, from_date)
    if candidate_rally_items:
        print(f' - found {len(candidate_rally_items)} candidates. Retrieving their info from BQ ...')
        timestamps_by_id = get_latest_timestamps_from_bq(bq_client, candidate_rally_items)
        bq_rows = extract_new_bq_rows_from_candidates(candidate_rally_items, timestamps_by_id, project)
        insert_rows_into_bq(bq_client, bq_rows)
    print(f'Done.')


# Bulk loader of Rally events into BQ. Scans for all stories/defects that have been updates since from_date
# noinspection PyUnresolvedReferences
@click.command()
@click.option('-f', '--from-date', type=click.DateTime(formats=['%Y-%m-%d']), default='2020-07-01')
def load_schedule_events(from_date):
    print(f' - starting the loader ...')
    print(f' --- will attempt to load schedule events starting from {from_date:%Y-%m-%d}')
    bq_client = bigquery.Client()
    if not events_table_is_empty(bq_client):
        print(f' --- {SCHEDULE_EVENTS_TABLE} is not empty or its status is unknown. Exiting ...')
        return
    rally, workspace, project = initialize_rally()
    items = get_stories_and_defects_from_rally(rally, workspace, project, f'{from_date:%Y-%m-%d}')
    bq_rows = extract_bq_rows_from_items(items, root_project_name=project)
    insert_rows_into_bq(bq_client, bq_rows)
    print('Done.')


@click.group()
def cli():
    pass


@click.command()
def sync():
    scheduler({}, {})


@click.command(help='lists available paths available in BQ dataset')
def list_paths():
    bq_client = bigquery.Client()
    query = f'''SELECT DISTINCT path_to_root as row_count from {SCHEDULE_EVENTS_TABLE} ORDER BY path_to_root'''
    for x in bq_client.query(query): print(x[0])


DATE_RANGE_HELP = 'use throughput data from within the date range'


@click.command(help='runs a Monte-Carlo simulation using throughput data from BQ dataset')
@click.argument('backlog-size', type=int)
@click.argument('path-to-root')
@click.option('-r', '--sample-date-range', nargs=2, type=click.DateTime(formats=['%Y-%m-%d']), help=DATE_RANGE_HELP)
@click.option('-c', '--experiment-count', 'count', default=1000, type=int, show_default=True)
# TODO: add support for how-much-we-can-do-by-date mode
# TODO: add support for options: a) weekday-to-weekday simulation, b) include weekends
def forecast(backlog_size, path_to_root, sample_date_range, count):
    print_information_header(backlog_size, count, path_to_root, sample_date_range)
    bq_throughput_data = get_throughput_data_from_bq(bigquery.Client(), path_to_root, sample_date_range)
    data = prepare_throughput_data(bq_throughput_data, sample_date_range)
    results = [run_simulation(data, backlog_size) for _ in range(count)]
    print_simulation_results(results)


if __name__ == '__main__':
    cli.add_command(load_schedule_events)
    cli.add_command(sync)
    cli.add_command(forecast)
    cli.add_command(list_paths)
    cli()
