#!/usr/bin/env python3

# Avoid using pandas to prevent running out of memory with large inputs.

import sys
import json
import math
import argparse
import csv
import re
from collections import defaultdict
from datetime import datetime

##############################################
# parse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="""
Estimate player ranks using the HumanSL model.

example:
Make sure to use the HumanSL model.
  ls /FOO/*.sgf \\
    | /BAR/katawrap.py -scan-humansl-ranks \\
        /BAZ/katago analysis -config analysis.cfg \\
          -model b18c384nbt-humanv0.bin.gz \\
    | ./estimate_rank.py

If you have sufficient computational power, you might prefer setting
rootNumSymmetriesToSample=8 for slightly better accuracy.
  ls /FOO/*.sgf \\
    | /BAR/katawrap.py -scan-humansl-ranks \\
        /BAZ/katago analysis -config analysis.cfg \\
          -model b18c384nbt-humanv0.bin.gz \\
          -override-config rootNumSymmetriesToSample=8 \\
    | ./estimate_rank.py

note:
The output of katawrap can be very large. If you want to save
intermediate outputs, selecting only the necessary items and
compressing them is recommended.
  ls /FOO/*.sgf | /BAR/katawrap.py ... \\
    | jq -c '{sgfFile, nextMoveColor, turnNumber, humanSLProfile, nextMovePrior, PB, BR, PW, WR, RE, HA, KM, DT, SZ, TM}' \\
    | gzip > analysis.jsonl.gz
  zcat analysis.jsonl.gz | ./estimate_rank.py""",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument('-by', metavar='AGG', help='aggregate results by: "file" (default), "player", or "player+rank"', required=False)
    parser.add_argument('-json', action='store_true', help='output JSONL with additional information.')
    args = vars(parser.parse_args())

################################################
# constants

fields_spec = {
    'file': {
        'agg': ['sgfFile', 'nextMoveColor'],
        'out': [
            'sgfFile', 'nextMoveColor',
            'PB', 'BR', 'PW', 'WR', 'RE', 'HA', 'KM', 'DT', 'SZ', 'TM',
            'player', 'playerRank',
        ],
    },
    'player': {
        'agg': ['player'],
        'out': ['player'],
    },
    'player+rank': {
        'agg': ['player', 'playerRank'],
        'out': ['player', 'playerRank'],
    },
}

csv_output_fields = ['sgfFile', 'nextMoveColor', 'player', 'playerRank']

################################################
# variables

by = 'file'
output_format = 'csv'

################################################
# main

def main():
    result = {}
    for k, line in enumerate(sys.stdin):
        analysis = json.loads(line)
        add_player_info(analysis)
        update_result(result, analysis)
        print_message(k, result, analysis)
    print_result(result)

def add_player_info(d):
    c = d.get('nextMoveColor')
    if c == 'B':
        d.update({'player': d.get('PB'), 'playerRank': d.get('BR')})
    elif c == 'W':
        d.update({'player': d.get('PW'), 'playerRank': d.get('WR')})

def update_result(result, analysis):
    # ignore analysis after the last move
    if analysis.get('nextMovePrior') is None and analysis.get('nextMoveHumanPrior') is None:
        return
    key = key_of(analysis)
    record = result.get(key)
    if record is None:
        record = new_record(analysis)
        result[key] = record
    update_record(record, analysis)

def key_of(analysis):
    prop = tuple(analysis.get(k) for k in fields_spec[by]['agg'])
    key = json.dumps(prop)
    return key

def new_record(analysis):
    return {
        **{k: analysis.get(k) for k in fields_spec[by]['out']},
        'log_likelihood': defaultdict(float),
        'moves': defaultdict(int),
    }

def update_record(record, analysis):
    profile = analysis['humanSLProfile']
    prior = analysis.get('nextMoveHumanPrior')
    if prior is None:
        prior = analysis['nextMovePrior']
    log_policy = math.log(prior)
    record['log_likelihood'][profile] += log_policy
    record['moves'][profile] += 1

def print_result(result):
    for record in result.values():
        print_record(record)

def print_record(record):
    log_likelihood = record['log_likelihood']
    posterior = get_posterior(log_likelihood)
    estimated_rank = dict_argmax(log_likelihood)
    output_fields = fields_spec[by]['out']
    player_dan = dan_for(record.get('playerRank'))
    estimated_dan = dan_for(estimated_rank)
    if output_format == 'json':
        print(json.dumps({
            **{k: record.get(k) for k in output_fields},
            'estimatedRank': estimated_rank,
            'posteriorOfEstimatedRank': posterior[estimated_rank],
            'movesForEstimatedRank': record['moves'][estimated_rank],
            'playerDan': player_dan,
            'estimatedDan': estimated_dan,
            'errorOfestimatedDan': estimated_dan - player_dan,
            'posterior': posterior,
        }))
    else:
        a = [record.get(k) for k in intersection(output_fields, csv_output_fields)]
        r = [estimated_rank]
        csv.writer(sys.stdout, delimiter=',').writerow(a + r)

def get_posterior(log_likelihood):
    # Uniform prior is assumed.
    m = max(log_likelihood.values())
    unnormalized_posterior = {k: math.exp(v - m) for k, v in log_likelihood.items()}
    s = sum(unnormalized_posterior.values())
    return {k: v / s for k, v in unnormalized_posterior.items()}

last_message_count = 0
def print_message(k, result, analysis):
    global last_message_count
    count = k + 1
    mega = 1000**2
    if count < mega or str(count)[0] == str(last_message_count)[0]:
        return
    else:
        last_message_count = count
    ti = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    f = analysis.get('sgfFile', '?')
    pb = analysis.get('PB', '?')
    pw = analysis.get('PW', '?')
    print(f'...[{ti}] in={count // mega}M, out={len(result)}, PB={pb}, PW={pw}, file={f}', file=sys.stderr)

################################################
# util

def find_first(ary, pred, not_found=None):
    return next((x for x in ary if pred(x)), not_found)

def intersection(a, b):
    # keep order
    return [x for x in a if x in b]

def dict_argmax(d):
    return max(d, key=d.get)

def dan_for(rank):
    nan = float('nan')
    if rank is None:
        return nan
    match = re.search(r'(\d+)([dkp])', rank)
    if match:
        n = int(match.group(1))
        u = match.group(2)
        return n if u == 'd' else 1 - n if u == 'k' else 9
    else:
        return nan

##############################################
# run

if __name__ == "__main__":
    if args['by']:
        by = args['by']
        allowed = fields_spec.keys()
        if not by in allowed:
            raise ValueError(f'Invalid -by option "{by}". Allowed options are: {", ".join(allowed)}')
    if args['json']:
        output_format = 'json'
    main()
