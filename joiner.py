import sys

class Joiner:

    def __init__(self, join_pairs=None, cook_successive_pairs=None):
        self._join_pairs = join_pairs
        self._cook_successive_pairs = cook_successive_pairs
        self._pool = []
        self._pop_count = 0

    def count(self):
        to_join = len(self._pool)
        popped = self._pop_count
        return (to_join, popped)

    def push_pairs(self, pairs):
        return sum([self._push_pair(p) for p in pairs], [])

    def _push_pair(self, pair):
        self._cook_successive_pairs_before_push(pair)
        self._pool.append(pair)
        if self._join_pairs:
            return self._pop_joined_responses()
        elif self._needs_successive_pair(pair):
            return self._pop_responses(butlast=True)
        else:
            return self._pop_responses()

    # pop

    def _pop_responses(self, butlast=False):
        return self._pick_responses(self._pop_pairs(butlast))

    def _pop_pairs(self, butlast=False):
        lis = self._pool
        n = len(lis)
        stop = n - 1 if butlast else n
        s = slice(0, stop)
        ret = lis[s]
        del lis[s]
        self._pop_count += len(ret)
        return ret

    def _pick_responses(self, pairs):
        return [res for _, res in pairs]

    # successive pairs

    def _cook_successive_pairs_before_push(self, last):
        needs_try = self._cook_successive_pairs and self._pool
        if not needs_try:
            return
        prev = self._pool[-1]
        req0, res0 = prev
        req1, res1 = last
        same_id = res0['id'] == res1['id']
        successive = res0['turnNumber'] + 1 == res1['turnNumber']
        if same_id and successive:
            self._cook_successive_pairs(prev, last)

    def _needs_successive_pair(self, last):
        if not self._cook_successive_pairs:
            return False
        req, res = last
        return (res['turnNumber'] + 1) in req['analyzeTurns']

    # join

    def _pop_joined_responses(self):
        last_req, last_res = self._pool[-1]
        is_finished = last_req['analyzeTurns'][-1] == last_res['turnNumber']
        if is_finished:
            joined_response = self._join_pairs(self._pop_pairs())
            return [joined_response]
        else:
            return []
