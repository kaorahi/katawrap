#!/usr/bin/python3

# Implementation note:
# 
# Single query {..., 'analyzeTurns': [0, 10, 20, ...]} is expended to
# multiple "requests" {..., 'turnNumber': n} for n = 0, 10, 20, ....
# Requests and responses must correspond one-to-one
# by their "id" and "turnNumber".
# (reportDuringSearchEvery is not supported.)
# 
# All requests and responses are poured into "sorter" to make
# sorted request-response pairs.

import argparse
import gzip
import json
import subprocess
import sys
import threading
import uuid

from sorter import Sorter
from joiner import Joiner
from board import board_from_moves
from util import find_if, warn, parse_json

from katrain.sgf_parser import SGF

##############################################
# parse args

if __name__ == "__main__":

    description = """
    Add conveneint features to KataGo parallel analysis engine.
    """

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('-default', metavar='JSON', help='default for missing fields in queries', required=False)
    parser.add_argument('-override', metavar='JSON', help='override queries', required=False)
    parser.add_argument('-komi', type=float, help='equivalent to specification in -override', required=False)
    parser.add_argument('-rules', help='equivalent to specification in -override', required=False)
    parser.add_argument('-visits', type=int, help='equivalent to specification in -override', required=False)
    parser.add_argument('-from', type=int, help='equivalent to specification in -override', required=False)
    parser.add_argument('-to', type=int, help='equivalent to specification in -override', required=False)
    parser.add_argument('-every', type=int, help='equivalent to specification in -override', required=False)
    parser.add_argument('-order', help='"arrival", "sort" (default), or "join"', default='sort', required=False)
    parser.add_argument('-extra', help='"normal", "rich", or "excess" (default)', default='excess', required=False)
    parser.add_argument('-only-last', action='store_true', help='analyze only the last turn when analyzeTurns is missing')
    parser.add_argument('-silent', action='store_true', help='do not print progress info to stderr')
    parser.add_argument('-debug', action='store_true', help='print debug info to stderr')
    parser.add_argument('katago-command', metavar='KATAGO_COMMAND', help='(ex.) ./katago analysis -config analysis.cfg -model model.bin.gz', nargs=argparse.REMAINDER)

    args = vars(parser.parse_args())
    default_default = {} if args['extra'] == 'normal' else {'includeUnsettledness': True}
    default = default_default | parse_json(args['default'] or '{}')
    override = parse_json(args['override'] or '{}')
    for key in ['komi', 'rules', 'visits', 'from', 'to', 'every']:
        val = args[key]
        if val is not None:
            override[key] = val
    katago_command = args['katago-command']

    if not katago_command:
        parser.print_help(sys.stderr)
        exit(1)

##############################################
# cook

# set later
sorter = None
joiner = None

def cook_json_to_jsonlist(func, line):
    ret = [json.dumps(z) for z in func(parse_json(line))]
    print_progress()
    return ret

def cook_query_json(line):
    return cook_json_to_jsonlist(cook_query, fill_placeholder(line))

def cook_response_json(line):
    return cook_json_to_jsonlist(cook_response, line)

def cook_query(query):
    needs_extra = (args['extra'] != 'normal')
    katago_queries, requests = cooked_queries_and_requests(query, needs_extra, warn)
    sorter.push_requests(requests)
    return katago_queries

def cook_response(response):
    if handle_invalid_response(response, warn):
        return []
    pairs = sorter.push_response(response)
    for req, res in pairs:
        cook_pair(req, res)
    return joiner.push_pairs(pairs)

def print_progress():
    if args['silent']:
        return
    rq, rs = sorter.count()
    j = joiner.count()
    warn(f"{rq} requests ({rs} pooled) / {j} to join ... ", overwrite=True)

def finish_print_progress():
    if not args['silent']:
        warn('Done.')

##############################################
# cook query

def cooked_queries_and_requests(orig_query, needs_extra, when_error):
    query = default | orig_query | override
    override_sgf = ['rules', 'komi']
    override_after_sgf = {k: override[k] for k in override_sgf if k in override.keys()}
    katago_query, extra = cooked_query_for_katago(query, override_after_sgf)
    err = check_error_in_query(katago_query)
    if err:
        when_error(err)
        return ([], [])
    additional = extra if needs_extra else {}
    requests = expand_query_turns(query | katago_query | additional)
    return ([katago_query], requests)

def cooked_query_for_katago(given_query, override_after_sgf):
    query = given_query.copy()
    add_id(query)
    cook_sgf_file(query)
    extra = cook_sgf(query)
    query |= override_after_sgf
    cook_alias(query)
    cook_analyze_turns_every(query)
    fix_analyze_turns(query)  # Joiner needs analyzeTurns.
    upcase_moves_and_players(query)  # for safety
    disable_report_during_search_every(query)
    cook_include_unsettledness(query)
    fix_rules(query)
    guess_rules_etc(query)
    return (query, extra)

# each cook

def add_id(query):
    i = new_id()
    if not 'id' in query:
        query['id'] = i

field_alias = {
    'from': 'analyzeTurnsFrom',
    'to': 'analyzeTurnsTo',
    'every': 'analyzeTurnsEvery',
    'visits': 'maxVisits',
}

def cook_alias(query):
    for field, value in query.copy().items():
        original = field_alias.get(field)
        if original:
            del query[field]
            query[original] = value

def cook_sgf_file(query):
    sgf_file = query.pop('sgfFile', None)
    if sgf_file is None:
        return
    opener = gzip.open if sgf_file.endswith('gz') else open
    with opener(sgf_file, mode='rt', encoding='utf-8') as f:
        sgf = f.read()
    query['sgf'] = sgf

def cook_sgf(query):
    sgf = query.pop('sgf', None)
    if sgf is None:
        return {}
    parsed, extra = parse_sgf(sgf)
    query |= parsed
    return extra

def cook_analyze_turns_every(query):
    every = query.pop('analyzeTurnsEvery', None)
    fr = query.pop('analyzeTurnsFrom', None)
    to = query.pop('analyzeTurnsTo', None)
    if not any((every, fr, to)):
        return
    n = len(query['moves'])
    _or = lambda z, default: default if z is None else z
    turns = list(range(_or(fr, 0), _or(to, n) + 1, _or(every, 1)))
    valid_last = (n in turns) or (to is not None)
    query['analyzeTurns'] = turns if valid_last else turns + [n]

def fix_analyze_turns(query):
    key = 'analyzeTurns'
    n = len(query['moves'])
    if not key in query:
        query[key] = [n] if args['only_last'] else list(range(0, n + 1))
    query[key] = [t for t in query[key] if 0 <= t and t <= n]

def upcase_moves_and_players(query):
    query['moves'] = [[player.upper(), move.upper()] for player, move in query['moves']]

def disable_report_during_search_every(query):
    if 'reportDuringSearchEvery' in query:
        del query['reportDuringSearchEvery']
        warn('"reportDuringSearchEvery" is unsupported.')

def cook_include_unsettledness(query):
    unsettledness = query.pop('includeUnsettledness', None)
    if unsettledness:
        query['includeOwnership'] = True

def guess_rules_etc(query):
    keys = ['rules', 'komi', 'boardXSize', 'boardYSize']
    rules, komi, boardXSize, boardYSize = (query.get(k) for k in keys)
    if rules is None:
        query['rules'] = 'chinese' if komi is None or komi == 7.5 else 'japanese'
    if boardXSize is None:
        query['boardXSize'] = boardYSize or 19
    if boardYSize is None:
        query['boardYSize'] = boardXSize or 19

rules_table = [
    # [katago_name, other_names...]
    ['tromp-taylor'],
    ['chinese', 'cn'],
    ['chinese-ogs'],
    ['chinese-kgs'],
    ['japanese', 'jp'],
    ['korean', 'kr'],
    ['stone-scoring'],
    ['aga'],
    ['bga'],
    ['new-zealand', 'nz'],
    ['aga-button'],
]

def fix_rules(query):
    rules = query['rules'].lower()
    a = find_if(rules_table, lambda z: rules in z)
    if a:
        query['rules'] = a[0]
    else:
        del query['rules']  # guessed later

# misc.

def check_error_in_query(query):
    required = ['id', 'moves', 'rules', 'boardXSize', 'boardYSize']
    missing = [key for key in required if query.get(key) is None]
    if missing:
        return f"Missing keys {missing}"
    moves = query['moves']
    err_maybe = [
        not (isinstance(moves, list) and moves) and "invalid moves",
    ]
    err = [e for e in err_maybe if e]
    return err or None

def fill_placeholder(line):
    if line.startswith('{'):
        return line
    key = 'sgf' if line.startswith('(;') else 'sgfFile'
    return json.dumps({key: line})

def expand_query_turns(query):
    return [query | {'turnNumber': t} for t in query['analyzeTurns']]

##############################################
# cook response

def cook_pair(req, res):
    sort_move_infos(req, res)
    add_extra_response(req, res)
    cook_unsettledness(req, res)

def sort_move_infos(req, res):
    res['moveInfos'].sort(key=lambda z: z['order'])

def add_extra_response(req, res):
    extra = args['extra']
    if extra == 'normal':
        return
    rich = played_move_etc(req, res) | {
        'query': req,
        'board': board_from_query(req),
    }
    excess = (req | res['rootInfo']) if extra == 'excess' else {}
    res |= excess | rich | res

def played_move_etc(req, res):
    moves = req['moves']
    turn_number = res['turnNumber']
    n = len(moves)
    if n <= turn_number:
        return {}
    played_color, played_move = moves[turn_number]
    ret = {'playedColor': played_color, 'playedMove': played_move}
    hit = find_if(res['moveInfos'], lambda z: z['move'] == played_move)
    if hit:
        ret['playedOrder'] = hit['order']
    return ret

def board_from_query(req):
    moves = req['moves'][0:req['turnNumber']]
    return board_from_moves(moves, req['boardXSize'], req['boardYSize'])

def cook_unsettledness(req, res):
    # This is separated from add_extra_response so that one can disable
    # it individually. Note that unsettledness needs ownership,
    # that incurs some performance overhead.
    if req.get('includeUnsettledness'):
        board = res.get('board') or board_from_query(req)
        res['unsettledness'] = calculate_unsettledness(res['ownership'], board)

def calculate_unsettledness(ownership, board):
    flattened_board = sum(board, [])
    unsettledness = lambda o, b: 0 if b == '.' else 1 - abs(o)
    return sum(unsettledness(o, b) for o, b in zip(ownership, flattened_board))

# for joiner

def join_pairs(pairs):
    req0, res0 = pairs[0]
    responses = [res for _, res in pairs]
    query = req0.copy()
    del query['turnNumber']
    return {'id': req0['id'], 'query': query, 'responses': responses}

def cook_successive_pairs(former_pair, latter_pair):
    if args['extra'] == 'normal':
        return
    req0, res0 = former_pair
    req1, res1 = latter_pair
    res0['nextRootInfo'] = res1['rootInfo']

# errors

def handle_invalid_response(response, when_error):
    if is_error_response(response):
        give_up_queries_for_error_response(response, when_error)
        return True
    if is_warning_response(response):
        req = get_request_for(response)
        when_error(f"Got warning (or unsupported): {response} for {req}")
    return False

def give_up_queries_for_error_response(response, when_error):
    i = response.get('id')
    if i is None:
        when_error(f"Error (no 'id'): {response}")
        return
    requests = sorter.pop_requests_by_id(i)
    first_req = requests[0] if requests else '(No corresponding request)'
    when_error(f"Got error (or unsupported): {response} for {first_req}")

def is_error_response(response):
    # 'action' is not supported
    return 'error' in response or 'action' in response

def is_warning_response(response):
    # 'isDuringSearch' is not supported
    return 'warning' in response or response.get('isDuringSearch')

##############################################
# SGF

def parse_sgf(sgf):
    root = SGF.parse_sgf(sgf)
    x, y = root.board_size
    ret = {
        'moves': gtp_moves_in_main_branch(root),
        'boardXSize': x,
        'boardYSize': y,
    }
    extra = {
        'sgfProp': root.sgf_properties(),
        'sgf': sgf,
    }
    if root.komi is not None:
        ret['komi'] = root.komi
    if root.ruleset:
        ret['rules'] = root.ruleset
    return (ret, extra)

def gtp_moves_in_main_branch(root):
    nodes = main_branch(root)
    katrain_moves = sum([n.move_with_placements for n in nodes], [])
    return [[m.player, m.gtp()] for m in katrain_moves]

def main_branch(root):
    nodes = [root]
    cur = root
    while cur.children:
        cur = cur.children[0]
        nodes.append(cur)
    return nodes

##############################################
# util

query_id_base = uuid.uuid4()
query_id = -1

def new_id():
    global query_id
    query_id += 1
    return f"{query_id_base}_{query_id}"

def same_by(keys):
    return lambda a, b: all(a.get(k) == b.get(k) for k in keys)

def debug_print(message):
    if args['debug']:
        warn(f"DEBUG {message}")

##############################################
# sorter & joiner

order = args['order']

sorter = Sorter(
    sort=(order != 'arrival'),
    corresponding=same_by(['id', 'turnNumber']),
    when_error=warn,
)

joiner = Joiner(
    join_pairs=join_pairs if (order == 'join') else None,
    cook_successive_pairs=cook_successive_pairs if (order != 'arrival') else None,
)

##############################################
# main loop

katago_process = subprocess.Popen(
    katago_command,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=sys.stderr,
)

thread_lock = threading.Lock()

is_input_finished = False

def read_queries():
    global is_input_finished
    for raw_line in sys.stdin:
        line = raw_line.strip()
        debug_print(f"(from STDIN): {line}")
        with thread_lock:
            js = cook_query_json(line)
        for j in js:
            debug_print(f"(to KATAGO): {j}")
            katago_process.stdin.write((j + '\n').encode())
        katago_process.stdin.flush()
    with thread_lock:
        is_input_finished = True

def read_responses():
    while in_progress():
        line = katago_process.stdout.readline().decode().strip()
        if not line:
            continue
        debug_print(f"(from KATAGO): {line}")
        with thread_lock:
            js = cook_response_json(line)
        for j in js:
            print(j)
        sys.stdout.flush()

def in_progress():
    with thread_lock:
        alive =  katago_process.poll() is None
        done = is_input_finished and not sorter.has_requests()
        return alive and not done

##############################################
# run

# initialize
response_thread = threading.Thread(target=read_responses, daemon=True)
response_thread.start()

# run
read_queries()

# finalize
if in_progress():
    response_thread.join()
katago_process.stdin.close()
finish_print_progress()