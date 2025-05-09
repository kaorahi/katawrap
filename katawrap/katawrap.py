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
import math
import subprocess
import sys
import threading
import time
import uuid

from sorter import Sorter
from board import board_from_moves, board_after_move
from util import find_if, flatten, warn, parse_json, merge_dict, is_executable

from katrain.sgf_parser import SGF, Move

##############################################
# parse args

if __name__ == "__main__":

    description = """
    Add conveneint features to KataGo parallel analysis engine.
    """

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('-default', metavar='JSON', help='default for missing fields in queries', required=False)
    parser.add_argument('-override', metavar='JSON', help='override queries', required=False)
    parser.add_argument('-override-list', metavar='JSON', help='override queries for each setting', required=False)
    parser.add_argument('-default-komi', metavar='KOMI', type=float, help='equivalent to specification in -default', required=False)
    parser.add_argument('-default-rules', metavar='RULES', help='equivalent to specification in -default', required=False)
    parser.add_argument('-komi', type=float, help='equivalent to specification in -override', required=False)
    parser.add_argument('-rules', help='equivalent to specification in -override', required=False)
    parser.add_argument('-visits', metavar='MAX_VISITS', type=int, help='equivalent to specification in -override', required=False)
    parser.add_argument('-from', metavar='ANALYZE_TURNS_FROM', type=int, help='equivalent to specification in -override', required=False)
    parser.add_argument('-to', metavar='ANALYZE_TURNS_TO', type=int, help='equivalent to specification in -override', required=False)
    parser.add_argument('-every', metavar='ANALYZE_TURNS_EVERY', type=int, help='equivalent to specification in -override', required=False)
    parser.add_argument('-last', action='store_true', help='equivalent to specification in -override')
    parser.add_argument('-include-policy', action='store_true', help='equivalent to specification in -override')
    parser.add_argument('-scan-humansl-ranks', action='store_true', help='scan humanSLProfile rank_*')
    parser.add_argument('-order', help='"arrival", "sort" (default), or "join"', default='sort', required=False)
    parser.add_argument('-extra', help='"normal", "rich", or "excess" (default)', default='excess', required=False)
    parser.add_argument('-max-requests', type=int, help='suspend sending queries when pending requests exceeds this number (0 = unlimited)', default=1000, required=False)
    parser.add_argument('-sequentially', action='store_true', help='do not read all input lines at once')
    parser.add_argument('-only-last', action='store_true', help='analyze only the last turn when analyzeTurns is missing')
    parser.add_argument('-sgf-encoding', metavar='ENCODINGS', help='use ENCODINGS (e.g. "utf-8,latin-1") to read SGF file', default='utf-8,latin-1,cp932,euc_jp,iso2022_jp', required=False)
    parser.add_argument('-disable-sgf-file', action='store_true', help='do not support sgfFile in query')
    parser.add_argument('-suspend-to', metavar='PATH', help='use pre-post wrapping like "katawrap.py -suspend-to PATH | katago | katawrap.py -resume-from PATH"', default=None, required=False)
    parser.add_argument('-resume-from', metavar='PATH', help='use pre-post wrapping like "katawrap.py -suspend-to PATH | katago | katawrap.py -resume-from PATH"', default=None, required=False)
    parser.add_argument('-netcat', action='store_true', help='use this option when netcat (nc) is used as katago command')
    parser.add_argument('-silent', action='store_true', help='do not print progress info to stderr')
    parser.add_argument('-debug', action='store_true', help='print debug info to stderr')
    parser.add_argument('-unsettledness-by-entropy', action='store_true', help='experimental (undocumented)')
    parser.add_argument('-soft-moyo', action='store_true', help='experimental (undocumented)')
    parser.add_argument('katago-command', metavar='KATAGO_COMMAND', help='(ex.) ./katago analysis -config analysis.cfg -model model.bin.gz', nargs=argparse.REMAINDER)

    args = vars(parser.parse_args())
    default_default = {} if args['extra'] == 'normal' else {'includeUnsettledness': True}
    default = merge_dict(default_default, parse_json(args['default'] or '{}'))
    override = parse_json(args['override'] or '{}')
    for key in ['komi', 'rules', 'visits', 'from', 'to', 'every', 'last']:
        val = args[key]
        if val is not None:
            override[key] = val
    if args['include_policy'] :
        override['includePolicy'] = True
    override_orig = override
    override_list = parse_json(args['override_list'] or '[]')
    if args['scan_humansl_ranks']:
        override_list += [
            {
                'maxVisits': 1,
                'includePolicy': True,
                'overrideSettings': {'humanSLProfile': f'rank_{r}'},
            }
            for r in
            [f'{i}d' for i in reversed(range(1, 10))] +
            [f'{i}k' for i in range(1, 21)]
        ]
    if not override_list:
        override_list = [{}]
    for key in ['komi', 'rules']:
        val = args['default_' + key]
        if val is not None:
            default[key] = val
    katago_command = args['katago-command']

    if not (katago_command or args['suspend_to'] or args['resume_from']):
        parser.print_help(sys.stderr)
        exit(1)

##############################################
# cook

def cook_json_to_jsonlist(func, line, sorter):
    return [json.dumps(z) for z in func(parse_json(line), sorter)]

def cook_query_json(line, sorter):
    return cook_json_to_jsonlist(cook_query, fill_placeholder(line), sorter)

def cook_response_json(line, sorter):
    return cook_json_to_jsonlist(cook_response, line, sorter)

def cook_query(query, sorter):
    needs_extra = (args['extra'] != 'normal')
    katago_queries, requests = cooked_queries_and_requests(query, needs_extra, warn)
    sorter.push_requests(requests)
    return katago_queries

def cook_response(response, sorter):
    if handle_invalid_response(response, sorter, warn):
        return []
    pairs = sorter.push_response(response)
    for req, res in pairs:
        cook_pair(req, res)
    return sorter.push_pairs_to_joiner(pairs)

##############################################
# cook query

def cooked_queries_and_requests(orig_query, needs_extra, error_reporter):
    query = merge_dict(default, orig_query, override)
    override_sgf = ['rules', 'komi']
    override_after_sgf = {k: override[k] for k in override_sgf if k in override.keys()}
    katago_query, extra = cooked_query_for_katago(query, override_after_sgf)
    err = check_error_in_query(katago_query)
    if err:
        error_reporter(f"{err} in {katago_query} (from {query})")
        return ([], [])
    additional = extra if needs_extra else {}
    requests = expand_query_turns(merge_dict(query, katago_query, additional))
    return ([katago_query], requests)

def cooked_query_for_katago(given_query, override_after_sgf):
    query = given_query.copy()
    add_id(query)
    cook_sgf_file(query)
    extra = cook_sgf(query)
    query.update(override_after_sgf)
    if not(has_valid_moves_field(query)):
        return (query, extra)
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
    'last': 'analyzeLastTurn',
    'visits': 'maxVisits',
}

def cook_alias(query):
    for field, value in query.copy().items():
        original = field_alias.get(field)
        if original:
        # if original is not None:
            del query[field]
            query[original] = value

def cook_sgf_file(query):
    sgf_file = query.pop('sgfFile', None)
    if sgf_file is None:
        return
    if (args['disable_sgf_file']):
        warn(f"sgfFile is disabled by the option -disable-sgf-file: {sgf_file}")
        return
    opener = gzip.open if sgf_file.endswith('gz') else open
    try:
        with opener(sgf_file, mode='rb') as f:
            raw = f.read()
            for encoding in args['sgf_encoding'].split(','):
                try:
                    query['sgf'] = raw.decode(encoding)
                    return
                except:
                    pass
            query['skipMe'] = f"Failed to read SGF file: {sgf_file}\n"
    except:
        query['skipMe'] = f"Failed to open SGF file: {sgf_file}\n"

def cook_sgf(query):
    sgf = query.pop('sgf', None)
    if sgf is None:
        return {}
    try:
        parsed, extra = parse_sgf(sgf)
    except:
        query['skipMe'] = f"Failed to parse SGF text: {sgf}\n"
        return {}
    query.update(parsed)
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
    query['analyzeTurns'] = turns

def fix_analyze_turns(query):
    orig = query.get('analyzeTurns') or []
    n = len(query['moves'])
    if query.pop('analyzeLastTurn', False):
        turns = append_if_missing(orig, n)
    elif orig:
        turns = orig
    else:
        turns = [n] if args['only_last'] else list(range(0, n + 1))
    query['analyzeTurns'] = [t for t in turns if 0 <= t and t <= n]

def append_if_missing(lis, elt):
    warn(lis, elt)
    return lis if elt in lis else lis + [elt]

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
    rules = query.get('rules')
    if rules is None:
        return
    a = find_if(rules_table, lambda z: rules.lower() in z)
    if a:
        query['rules'] = a[0]
    else:
        del query['rules']  # guessed later

# misc.

def has_valid_moves_field(query):
    moves = query.get('moves')
    return isinstance(moves, list) and moves

def check_error_in_query(query):
    skip_me = query.get('skipMe')
    if skip_me:
        del query['skipMe']
        return skip_me
    required = ['id', 'moves', 'rules', 'boardXSize', 'boardYSize']
    missing = [key for key in required if query.get(key) is None]
    if missing:
        return f"Missing keys {missing}"
    err_maybe = [
        not has_valid_moves_field(query) and "Invalid moves field",
    ]
    err = [e for e in err_maybe if e]
    return err or None

def fill_placeholder(line):
    if line.startswith('{'):
        return line
    key = 'sgf' if line.startswith('(;') else 'sgfFile'
    return json.dumps({key: line})

def expand_query_turns(query):
    return [merge_dict(query, {'turnNumber': t}) for t in query['analyzeTurns']]

##############################################
# cook response

def cook_pair(req, res):
    sort_move_infos(req, res)
    cook_board_in_info(req, res)
    cook_unsettledness(req, res)
    add_extra_response(req, res)

def sort_move_infos(req, res):
    res['moveInfos'].sort(key=lambda z: z['order'])

def add_extra_response(req, res):
    extra = args['extra']
    if extra == 'normal':
        return
    rich = rich_response(req, res)
    excess = excessive_response(req, res) if extra == 'excess' else {}
    res.update(merge_dict(excess, rich, res))

def rich_response(req, res):
    rich = merge_dict(next_move_etc(req, res), {
        'query': req,
        'board': board_from_query(req),
    })
    return rich

def excessive_response(req, res):
    root_info = res['rootInfo']
    res['rootInfo'] = extended_root_info(res)
    override = req.get('overrideSettings', {})
    return merge_dict(req, cooked_sgf_prop(req), root_info, override)

def extended_root_info(res):
    keys = [
        'blackUnsettledness',
        'whiteUnsettledness',
        'territoryUnsettledness',
        'unsettledness',
        'blackMoyo',
        'whiteMoyo',
        'moyoLead',
    ]
    root_info = res['rootInfo']
    additional = {k: res[k] for k in keys if k in res}
    return merge_dict(root_info, additional)

def cooked_sgf_prop(req):
    sgf_prop = req.get('sgfProp')
    if not sgf_prop:
        return {}
    return {k: ','.join(v) for k, v in sgf_prop.items()}

def next_move_etc(req, res):
    moves = req['moves']
    turn_number = res['turnNumber']
    n = len(moves)
    if n <= turn_number:
        return {}
    next_move_color, next_move = moves[turn_number]
    next_sign_for = {'B': +1, 'W': -1}
    next_move_sign = next_sign_for.get(next_move_color.upper()) or 0
    ret = {
        'nextMove': next_move,
        'nextMoveColor': next_move_color,
        'nextMoveSign': next_move_sign,
    }
    # policy
    policy_table = {
        'nextMovePrior': 'policy',
        'nextMoveHumanPrior': 'humanPolicy',
    }
    idx = policy_index(next_move, req['boardXSize'], req['boardYSize'])
    for k, v in policy_table.items():
        p = res.get(v)
        if p is not None:
            ret[k] = p[idx]
    # moveInfos
    hit = find_if(res['moveInfos'], lambda z: z['move'] == next_move)
    if hit:
        keys = {
            'nextMoveRank': 'order',
            'nextMovePrior': 'prior',
            'nextMoveHumanPrior': 'humanPrior',
        }
        for k, v in keys.items():
            if v in hit:
                ret[k] = hit[v]
    return ret

def policy_index(move, xsize, ysize):
    coords = Move.from_gtp(move).coords
    if coords is None:
        return -1
    else:
        # >>> from sgf_parser import Move
        # >>> Move.from_gtp('A19').coords
        # (0, 18)
        # >>> Move.from_gtp('T1').coords
        # (18, 0)
        x, y = coords
        # top-left (A19) = 0, bottom-right (T1) = 360
        return x + (ysize - y - 1) * xsize

def board_from_query(req):
    moves = req['moves'][0:req['turnNumber']]
    return board_from_moves(moves, req['boardXSize'], req['boardYSize'])

def board_for_info(req, res, info, base_board=None):
    board = base_board or res.get('board') or board_from_query(req)
    player = res['rootInfo']['currentPlayer']
    move = [player, info['move']]
    return board_after_move(move, board)

def cook_board_in_info(req, res):
    # add "boad" into each element of "moveInfos" only when includeOwnership
    # is true because of too large overhead in the output size
    if req['includeOwnership'] and res.get('board'):
        for info in res['moveInfos']:
            info['board'] = board_for_info(req, res, info)

def cook_unsettledness(req, res):
    # This is separated from add_extra_response so that one can disable
    # it individually. Note that unsettledness needs ownership,
    # that incurs some performance overhead.
    if not req.get('includeUnsettledness'):
        return
    board = res.get('board') or board_from_query(req)
    cook_unsettledness_sub(res, board)
    for info in res['moveInfos']:
        board1 = info.get('board') or board_for_info(req, res, info, base_board=board)
        cook_unsettledness_sub(info, board1)

def cook_unsettledness_sub(res, board):
    ownership = res.get('ownership')
    if ownership is None:
        return
    calculators = (
        calculate_unsettledness,
        calculate_moyo,
        calculate_settled_territory,
        calculate_ownership_distribution,
    )
    for calc in calculators:
        res.update(calc(ownership, board))

def calculate_unsettledness(ownership, board):
    board_marks = ('X', 'O', '.')
    f = unsettledness_by_entropy if args['unsettledness_by_entropy'] else unsettledness_by_abs
    b, w, t = (ownership_based_feature(f, c, ownership, board) for c in board_marks)
    return {
        'blackUnsettledness': b,
        'whiteUnsettledness': w,
        'territoryUnsettledness': t,
        'unsettledness': b + w,
    }

def ownership_based_feature(f, stone_mark, ownership, board):
    o_b_pairs = zip(ownership, flatten(board))
    return sum(f(o) for o, b in o_b_pairs if b == stone_mark)

def unsettledness_by_abs(o):
    return 1 - abs(o)

def unsettledness_by_entropy(o):
    q = (o + 1) / 2
    return entropy_sub(q) + entropy_sub(1 - q)

def entropy_sub(p):
    return - p * math.log(p) if p > 0 else 0

def calculate_moyo(ownership, board):
    fs = (black_moyo_func, white_moyo_func)
    b, w = (ownership_based_feature(f, '.', ownership, board) for f in fs)
    return {
        'blackMoyo': b,
        'whiteMoyo': w,
        'moyoLead': b - w,
    }

def black_moyo_func(o):
    f = black_soft_moyo_func if args['soft_moyo'] else black_hard_moyo_func
    return f(o)

def black_hard_moyo_func(o):
    threshold = 1/3
    return o if 0 <= o <= threshold else 0

def black_soft_moyo_func(o):
    power = 2
    # compatible with lizgoban v0.8.0-pre3
    # (23-07-14, draw_endstate_dist.js)
    return o * (1 - o**power) if o > 0 else 0

def white_moyo_func(o):
    return black_moyo_func(- o)

def calculate_settled_territory(ownership, board):
    fs = (black_settled_territory_func, white_settled_territory_func)
    b, w = (ownership_based_feature(f, '.', ownership, board) for f in fs)
    return {
        'blackSettledTerritory': b,
        'whiteSettledTerritory': w,
    }

def black_settled_territory_func(o):
    exponent = 3.0
    return o ** exponent if o >= 0 else 0

def white_settled_territory_func(o):
    return black_settled_territory_func(- o)

def calculate_ownership_distribution(ownership, board):
    divide = ownership_distribution_idx(1.0) + 1
    z = lambda: [0] * divide
    counts = {'X': z(), 'O': z(), '.': z()}
    for o, b in zip(ownership, flatten(board)):
        counts[b][ownership_distribution_idx(o)] += 1
    a = flatten([counts[c] for c in ('X', 'O', '.')])
    return {
        'ownershipDistribution': a
    }

def ownership_distribution_idx(o):
    divide = 10
    exponent = 1  # be careful for the sign of o!
    o = o ** exponent
    return min(int((o + 1) * divide / 2), divide - 1)

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
    # rootInfo
    req0, res0 = former_pair
    req1, res1 = latter_pair
    res0['nextRootInfo'] = res1['rootInfo']
    # gain
    sign = res0['nextMoveSign']
    setter = lambda gain_key, key, sign=sign: gain_setter(gain_key, key, res0, res1, sign)
    setter('nextWinrateGain', 'winrate')
    setter('nextScoreGain', 'scoreLead')
    setter('nextMoyoGain', 'moyoLead')
    setter('nextUnsettlednessGain', 'unsettledness', +1)

def gain_setter(gain_key, key, res0, res1, sign):
    if key in res0 and key in res1:
        res0[gain_key] = (res1[key] - res0[key]) * sign

# errors

def handle_invalid_response(response, sorter, error_reporter):
    if is_error_response(response):
        give_up_queries_for_error_response(response, sorter, error_reporter)
        return True
    if is_ignorable_response(response, sorter):
        return True  # drop silently
    if is_warning_response(response):
        error_reporter(f"Got warning: {response} for {req}")
        return False
    return False

def give_up_queries_for_error_response(response, sorter, error_reporter):
    i = response.get('id')
    if i is None:
        error_reporter(f"Error (no 'id'): {response}")
        return
    requests = sorter.pop_requests_by_id(i)
    first_req = requests[0] if requests else '(No corresponding request)'
    error_reporter(f"Got error: {response} for {first_req}")

def is_error_response(response):
    return 'error' in response

def is_warning_response(response):
    return 'warning' in response

def is_ignorable_response(response, sorter):
    keys = ['action', 'noResults', 'isDuringSearch']
    ignored_type = any(response.get(k) for k in keys)
    no_corresponding_request = sorter.get_request_for(response) is None
    return ignored_type or no_corresponding_request

##############################################
# progress message

total_queries = None
processed_queries = 0
progress_start_time = None

def print_progress(sorter):
    if args['silent']:
        return
    ti = elapsed_time_string()
    q = progress_of_queries()
    w, p, j, d, requests = sorter.count()
    # message = f"[q] {q} [res] wait={w} pool={p} join={j} done={d} ... "
    r = progress_of_responses(w, requests)
    message = f"[in {q}] [out{r} {w}>{p}>{j}>{d}] {ti} ... "
    warn(message, overwrite=True)

def progress_of_queries():
    total = '' if total_queries is None else f"/{total_queries}"
    return f"{processed_queries}{total}"

def progress_of_responses(waiting, requests):
    if total_queries is None:
        return ''
    if requests == 0 or processed_queries == 0:
        return ' 0%'
    responses = requests - waiting
    p = processed_queries / total_queries
    is_guess = p < 1
    s = math.floor(responses / requests * p * 100)
    return f" {s}%{'?' if is_guess else ''}"

def finish_print_progress(interrupted):
    if not args['silent']:
        warn('\nInterrupted.' if interrupted else 'All done.')

def elapsed_time_string():
    global progress_start_time
    if progress_start_time is None:
        progress_start_time = time.time()
    seconds = int(time.time() - progress_start_time)
    minutes, s = quotient_and_remainder(seconds, 60)
    h, m = quotient_and_remainder(minutes, 60)
    h_str = '' if h < 1 else f"{h}:"
    return f"{h_str}{m:02}:{s:02}"

def quotient_and_remainder(a, b):
    return int(a / b), a % b

##############################################
# SGF

def parse_sgf(sgf):
    root = SGF.parse_sgf(sgf)
    x, y = root.board_size
    ret = {
        'moves': gtp_moves_in_main_branch(root),
        'boardXSize': x,
        'boardYSize': y,
        'initialPlayer': root.initial_player,
    }
    extra = {
        'sgfProp': root.sgf_properties(),
        'sgf': sgf,
    }
    if root.placements:
        ret['initialStones'] = gtp_moves_for(root.placements)
    if root.komi is not None:
        ret['komi'] = root.komi
    if root.ruleset:
        ret['rules'] = root.ruleset
    return (ret, extra)

def gtp_moves_in_main_branch(root):
    nodes = main_branch_after(root)
    katrain_moves = sum([n.move_with_placements for n in nodes], root.moves)
    return gtp_moves_for(katrain_moves)

def gtp_moves_for(katrain_moves):
    return [[m.player, m.gtp()] for m in katrain_moves]

def main_branch_after(root):
    nodes = []
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

def make_sorter():
    order = args['order']
    dumped = args['resume_from']
    sorter = Sorter(
        sort=(order != 'arrival'),
        max_requests=max_requests(),
        corresponding=same_by(['id', 'turnNumber']),
        error_reporter=warn,
        join_pairs=join_pairs if (order == 'join') else None,
        cook_successive_pairs=cook_successive_pairs if (order != 'arrival') else None,
    )
    if dumped:
        with open(dumped, 'r') as f:
            sorter.undump_requests(f.read())
    return sorter

def max_requests():
    m = args['max_requests']
    return m if m > 0 else math.inf

def has_requests_limit():
    return max_requests() < math.inf

##############################################
# katago process

def start_katago():
    return subprocess.Popen(
        katago_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
    )

def send_to_katago(line, process):
    if process is None:
        print(line)
        return
    debug_print(f"(to KATAGO): {line}")
    process.stdin.write((line + '\n').encode())
    process.stdin.flush()

def terminate_all_queries(process):
    terminate_all = json.dumps({'id': new_id(), 'action': 'terminate_all'})
    send_to_katago(terminate_all, process)

##############################################
# main loop

# query: STDIN ==> [main thread] ==> KataGo

is_input_finished = False

def read_queries(katago_process, sorter, thread_condition):
    global is_input_finished, total_queries, processed_queries, override
    if args['sequentially']:
        input_lines = sys.stdin
    else:
        input_lines = sys.stdin.readlines()
        total_queries = len(input_lines)
    for k, line in enumerate(input_lines):
        for o in override_list:
            override = override_orig | o
            cook_input_line(line, katago_process, sorter, thread_condition)
        processed_queries = k + 1
    total_queries = processed_queries  # for -sequentially
    is_input_finished = True

def cook_input_line(raw_line, katago_process, sorter, thread_condition):
    line = raw_line.strip()
    debug_print(f"(from STDIN): {line}")
    push_to_sorter = lambda: cook_query_json(line, sorter)
    wait_for_room = lambda tc: tc.wait_for(sorter.has_room)
    js = with_thread_condition(push_to_sorter, wait_for_room, thread_condition)
    for j in js:
        send_to_katago(j, katago_process)

# response: KataGo ==> [response thread] ==> STDOUT

def read_responses(katago_process, sorter, thread_condition):
    try:
        do_read_responses(katago_process, sorter, thread_condition)
    except BrokenPipeError:
        warn('BrokenPipe in response thread')

def do_read_responses(katago_process, sorter, thread_condition):
    read_line = lambda: katago_process.stdout.readline().decode().strip() if katago_process else sys.stdin.readline().strip()
    source = katago_process.stdout if katago_process else sys.stdin
    while in_progress(katago_process, sorter):
        line = read_line()
        if not line:
            continue
        debug_print(f"(from KATAGO): {line}")
        pop_from_sorter = lambda: cook_response_json(line, sorter)
        notify = lambda tc: tc.notify()
        js = with_thread_condition(pop_from_sorter, notify, thread_condition)
        for j in js:
            print(j)
        sys.stdout.flush()

def with_thread_condition(cooker, checker, thread_condition):
    if not (has_requests_limit() and thread_condition):
        return cooker()
    with thread_condition:
        checker(thread_condition)
        return cooker()

# progress: [progress thread] ==> STDERR

def show_progress_periodically(sec, katago_process, sorter):
    while in_progress(katago_process, sorter):
       print_progress(sorter)
       time.sleep(sec)

def in_progress(katago_process, sorter):
    alive = katago_process.poll() is None if katago_process else True
    done = is_input_finished and not sorter.has_requests()
    return alive and not done

##############################################
# run

def main():
    global is_input_finished
    exit_if_dangerous()
    interrupted = False
    katago_process, response_thread, sorter, thread_condition = initialize()
    try:
        if args['resume_from'] is not None:
            is_input_finished = True
            read_responses(katago_process, sorter, thread_condition)
            return
        read_queries(katago_process, sorter, thread_condition)
        if response_thread:
            response_thread.join()
        else:
            dump_sorter(sorter, args['suspend_to'])
    except KeyboardInterrupt:
        interrupted = True
    finally:
        print_progress(sorter)
        finalize(katago_process, interrupted)

def exit_if_dangerous():
    path = args['suspend_to']
    overwriting_exe = path is not None and is_executable(path)
    if overwriting_exe:
        print(f"You are trying to overwrite an executable file! ({path})\nAbort.", file=sys.stderr)
        exit(1)

def dump_sorter(sorter, path):
    if path is None:
        return
    with open(path, 'w') as f:
        f.write(sorter.dump_requests())

def initialize():
    needs_katago = args['suspend_to'] is None and args['resume_from'] is None
    needs_thread_condition = needs_katago and has_requests_limit()
    katago_process = None
    response_thread = None
    sorter = make_sorter()
    thread_condition = threading.Condition() if needs_thread_condition else None
    if needs_katago:
        katago_process = start_katago()
        response_thread = threading.Thread(
            target=read_responses,
            args=(katago_process, sorter, thread_condition),
            daemon=True,
        )
        response_thread.start()
    if not args['silent']:
        progress_sec = 1
        start_progress_thread(progress_sec, katago_process, sorter)
    if args['netcat'] and needs_katago:
        # cancel requests by previous client for safety
        terminate_all_queries(katago_process)
    return (katago_process, response_thread, sorter, thread_condition)

def start_progress_thread(sec, katago_process, sorter):
    progress_thread = threading.Thread(
        target=show_progress_periodically,
        args=(sec, katago_process, sorter),
        daemon=True,
    )
    progress_thread.start()

def finalize(katago_process, interrupted):
    if katago_process is None:
        finish_print_progress(interrupted)
        return
    try:
        katago_process.stdin.close()
        katago_process.kill()
        finish_print_progress(interrupted)
    except BrokenPipeError:
        warn('BrokenPipe in main thread')
    finally:
        if interrupted:
            finalize_interruption()

def finalize_interruption():
    if not args['netcat']:
        return
    warn('Sending terminate_all...')
    another_netcat = start_katago()
    terminate_all_queries(another_netcat)
    another_netcat.stdin.close()
    warn('...Sent')

if __name__ == "__main__":
    main()
