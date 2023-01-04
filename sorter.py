from util import find_if, nop

class Sorter:

    def __init__(self, sort=True, corresponding=nop, when_error=nop):
        self._sort = sort
        self._corresponding = corresponding
        self._when_error = when_error
        self._req_pool = []
        self._res_pool = []

    def has_requests(self):
        return bool(self._req_pool)

    def count(self):
        return (len(self._req_pool), len(self._res_pool))

    def push_requests(self, requests):
        self._req_pool += requests

    def push_response(self, response):
        self._res_pool.append(response)
        return self._pop_req_res_pairs()

    def pop_requests_by_id(self, i):
        requests = [req for req in self._req_pool if req['id'] == i]
        for req in requests:
            self._req_pool.remove(req)
        return requests

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
            self._when_error(f"Unmatched: request={req} response={res}")
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
