import json

from util import find_if, nop
from joiner import Joiner

class Sorter:

    def __init__(
            self,
            sort=True,
            max_requests=1000,
            corresponding=nop,
            error_reporter=nop,
            # for joiner
            join_pairs=None,
            cook_successive_pairs=None
    ):
        self._sort = sort
        self._max_requests = max_requests
        self._corresponding = corresponding
        self._error_reporter = error_reporter
        self._req_pool = []
        self._res_pool = []
        self._joiner = Joiner(
            join_pairs=join_pairs,
            cook_successive_pairs=cook_successive_pairs
        )

    def has_requests(self):
        return bool(self._req_pool)

    def has_room(self):
        return len(self._req_pool) < self._max_requests

    def count(self):
        requests = len(self._req_pool)
        pooled = len(self._res_pool)
        waiting = requests - pooled
        to_join, popped = self._joiner.count()
        counts = [waiting, pooled, to_join, popped]
        pushed = sum(counts)
        return (waiting, pooled, to_join, popped, pushed)

    def push_requests(self, requests):
        self._req_pool += requests

    def push_response(self, response):
        self._res_pool.append(response)
        return self._pop_req_res_pairs()

    def push_pairs_to_joiner(self, pairs):
        return self._joiner.push_pairs(pairs)

    def get_request_for(self, res):
        return self._get_request_for(res)

    def pop_requests_by_id(self, i):
        requests = [req for req in self._req_pool if req['id'] == i]
        for req in requests:
            self._req_pool.remove(req)
        return requests

    def dump_requests(self):
        return ''.join([json.dumps(h) + '\n' for h in self._req_pool])

    def undump_requests(self, dumped):
        self._req_pool = [json.loads(s) for s in dumped.strip().split('\n')]

    # available request-response pairs

    def _pop_req_res_pairs(self):
        if self._sort:
            pairs = self._get_available_sorted_pairs()
        else:
            pairs = self._get_pairs_in_arrival_order()
        for req, res in pairs:
            if req:
                self._req_pool.remove(req)
            if res:
                self._res_pool.remove(res)
        invalid_pairs = [p for p in pairs if not all(p)]
        for p in invalid_pairs:
            req, res = p
            self._error_reporter(f"Unmatched: request={req} response={res}")
            pairs.remove(p)
        return pairs

    def _get_pairs_in_arrival_order(self):
        return [(self._get_request_for(res), res) for res in self._res_pool]

    def _get_available_sorted_pairs(self):
        ret = []
        for req in self._req_pool:
            res = self._get_response_for(req)
            if res:
                ret.append((req, res))
            else:
                # corresponding response is not received yet.
                break
        return ret

    # correspondence

    def _get_request_for(self, res):
        return self._find_correspondence(self._req_pool, res)

    def _get_response_for(self, req):
        return self._find_correspondence(self._res_pool, req)

    def _find_correspondence(self, lis, elt):
        return find_if(lis, lambda z: self._corresponding(z, elt))
