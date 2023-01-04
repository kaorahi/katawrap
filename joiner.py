import sys

class Joiner:

    def __init__(self, join_pairs=None, cook_successive_pairs=None):
        self._join_pairs = join_pairs
        self._cook_successive_pairs = cook_successive_pairs
        self._pool = []

    def count(self):
        return len(self._pool)

    def push_pairs(self, pairs):
        return sum([self._push_pair(p) for p in pairs], [])

    def _push_pair(self, pair):
        self._cook_successive_pairs_before_push(pair)
        self._pool.append(pair)
        if self._join_pairs:
            return self._pop_joined_responses()
        elif self._needs_successive_pair(pair):
            return self._pop_responses_butlast()
        else:
            return self._pop_all_responses()

    def _pop_all_responses(self):
        ret = self._pick_responses(self._pool)
        self._pool.clear()
        return ret

    def _pop_responses_butlast(self):
        ret = self._pick_responses(self._pool[0:-1])
        del self._pool[0:-1]
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
            joined_response = self._join_pairs(self._pool)
            self._pool.clear()
            return [joined_response]
        else:
            return []
