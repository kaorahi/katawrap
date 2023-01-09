import json
import sys

def find_if(lis, pred):
    hit = [z for z in lis if pred(z)]
    return hit[0] if hit else None

def nop(*args):
    return None

def warn(message, overwrite=False):
    fmt = '\r{}' if overwrite else '{}\n'
    print(fmt.format(message), end='', file=sys.stderr)
    sys.stderr.flush()

def parse_json(s):
    try:
        return json.loads(s)
    except:
        warn(f"Invalid JSON '{s}' is replaced with '{{}}')")
        return {}

# for python < 3.9
def merge_dict(*args):
    ret = {}
    for d in args:
        ret.update(d)
    return ret
