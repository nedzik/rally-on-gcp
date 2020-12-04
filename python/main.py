import base64
import os
import re
import sys
import functools
import operator
import datetime

from google.cloud import bigquery
from pyral import Rally, rallyWorkset

SCHEDULE_EVENTS_TABLE='rally.schedule_events'
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


def get_stories_and_defects_from_rally(rally, workspace, project, fields, from_date):
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
    print(' - checking there is no data in BQ ...')
    query = f'''SELECT count(*) as row_count from {SCHEDULE_EVENTS_TABLE}'''
    return next((x.row_count for x in client.query(query)), -1) == 0


def insert_rows_into_bq(bq_client, bq_rows):
    batch_size = 10000
    print(f' - inserting {len(bq_rows)} into BQ ...')
    for index in range(0, len(bq_rows), batch_size):
        batch_rows = bq_rows[index:index+batch_size]
        print(f' --- inserting next {len(batch_rows)} rows starting from offset {index} ...')
        errors = bq_client.insert_rows_json(SCHEDULE_EVENTS_TABLE, batch_rows, row_ids=[None] * len(batch_rows))
        if errors:
            print(f' --- aborting due to the errors encountered while inserting rows:')
            for x in errors: print(f' ----- {x}')
            return
        print(f' --- inserted {len(batch_rows)} rows into BQ.')
    print(f' - done inserting {len(bq_rows)} into BQ.')


def get_rally_item(rally, rally_id):
    query = f'''FormattedID = "{rally_id}"'''
    print(f''' - fetching rally object {rally_id} ...''')
    entity_type = 'Defect' if rally_id[:2] == b'DE' else 'HierarchicalRequirement'
    return next((x for x in rally.get(entity_type, query=query, projectScopeDown=True, fetch=True)), None)


# Work In Progress
# Cloud Function handler for scanning for recently modified stories/defects
# Takes the scan offset from RALLY_SCAN_OFFSET environment variable
# For each found story/defect, issues a PubSub message that updater Cloud Function will process
# noinspection PyUnusedLocal
def scheduler(event, context):
    rally, workspace, project = initialize_rally()
    rally_scan_offset = int(os.getenv('RALLY_SCAN_OFFSET', '1'))
    from_date = (datetime.datetime.now() - datetime.timedelta(days=rally_scan_offset)).strftime('%Y-%m-%d')
    rally_items = get_stories_and_defects_from_rally(rally, workspace, project, "FormattedID,LastUpdateDate", from_date)
    for i in rally_items: print(i[:-1])
    print(f'Done.')


# Work In Progress
# Cloud Function to insert new events in BQ for the story/defect provider as data
# noinspection PyUnusedLocal
def updater(event, context):
    rally, workspace, project = initialize_rally()
    rally_id = base64.b64decode(event['data'])
    rally_item = get_rally_item(rally, rally_id)
    if rally_item:
        bq_rows = extract_bq_rows_from_item(item(rally_item), root_project_name=project)
        for x in bq_rows: print(x)
        print(len(bq_rows))
    print(f'Done.')


# Bulk loader of Rally events into BQ. Scans for all stories/defects that have been updates since from_date
# noinspection PyUnresolvedReferences
def loader(from_date):
    print(' - starting the loader ...')
    bq_client = bigquery.Client()
    if not events_table_is_empty(bq_client):
        print(' --- BQ table rally_statistics.events is not empty or its status is unknown. Exiting ...')
        return
    rally, workspace, project = initialize_rally()
    fields = "FormattedID,LastUpdateDate,RevisionHistory,Owner,Project"
    items = get_stories_and_defects_from_rally(rally, workspace, project, fields, from_date)
    bq_rows = extract_bq_rows_from_items(items, root_project_name=project)
    insert_rows_into_bq(bq_client, bq_rows)
    print('Done.')


# Main Entry to run the loader and to test Cloud Function handlers
if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else 'load'
    if action == 'scheduler':
        scheduler({}, {})
    elif action == 'updater':
        id_to_find = sys.argv[2] if len(sys.argv) > 2 else 'US1036860'
        updater({'data': base64.b64encode(id_to_find.encode())}, {})
    elif action == 'loader':
        loader(sys.argv[2] if len(sys.argv) > 2 else '2020-07-01')
    else:
        print(f'Unknown action: {action}')
        sys.exit(1)
