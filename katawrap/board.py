#!/usr/bin/python3

# calculate placement of stones from given moves

# (sample)
#
# board = board_from_moves([["B","A3"],["W","B3"],["B","B2"],["W","A2"]], 4, 3)
# print(board)
# print(board_to_str(board))
#
# [['.', 'O', '.', '.'], ['O', 'X', '.', '.'], ['.', '.', '.', '.']]
# .O..
# OX..
# ....

# ported from lizgoban v0.3.1 (rule.js)

import re

##############################################
# export

def board_from_moves(moves, x_size, y_size):
    stones = stones_from_history(moves, y_size, x_size)
    return aa_map(stones, letter_for_stone)

def board_to_str(board):
    return '\n'.join([''.join(row) for row in board])

##############################################
# main

# function stones_from_history(history) {
#     const stones = aa_new(19, 19, () => ({}))
#     history.forEach((h, k) => put(h, stones, k === history.length - 1))
#     return stones
# }

def stones_from_history(history, i_size, j_size):
    stones = aa_new(i_size, j_size, lambda: {})
    for k, h in enumerate(history):
        put(h, stones, i_size, j_size)
    return stones

# function put({move, is_black}, stones, last) {
#     const [i, j] = move2idx(move), pass = (i < 0); if (pass) {return}
#     aa_set(stones, i, j, {stone: true, black: is_black, ...(last ? {last} : {})})
#     remove_dead_by([i, j], is_black, stones)
# }

def put(h, stones, i_size, j_size):
    player, move = h
    is_black = player.upper() == 'B'
    i, j = move2idx(move.upper(), i_size, j_size)
    is_pass = i < 0
    if is_pass:
        return
    aa_set(stones, i, j, {'stone': True, 'black': is_black})
    remove_dead_by((i, j), is_black, stones)

# function remove_dead_by(ij, is_black, stones) {
#     around_idx(ij).forEach(idx => remove_dead(idx, !is_black, stones))
#     remove_dead(ij, is_black, stones)
# }

def remove_dead_by(ij, is_black, stones):
    for idx in around_idx(ij):
        remove_dead(idx, not is_black, stones)
    remove_dead(ij, is_black, stones)

##############################################
# remove dead stones

# function remove_dead(ij, is_black, stones) {
#     const state = {hope: [], dead_pool: [], dead_map: [[]], is_black, stones}
#     check_if_liberty(ij, state)
#     while (!empty(state.hope)) {
#         if (search_for_liberty(state)) {return}
#     }
#     state.dead_pool.forEach(idx => aa_set(stones, ...idx, {}))
# }

def remove_dead(ij, is_black, stones):
    i_size = len(stones)
    j_size = len(stones[0])
    state = {
        'hope': [],
        'dead_pool': [],
        'dead_map': aa_new(i_size, j_size, lambda: False),
        'is_black': is_black,
        'stones': stones,
    }
    check_if_liberty(ij, state)
    while state['hope']:
        if search_for_liberty(state):
            return
    for i, j in state['dead_pool']:
        aa_set(stones, i, j, {})

# function search_for_liberty(state) {
#     return around_idx(state.hope.shift()).find(idx => check_if_liberty(idx, state))
# }

def search_for_liberty(state):
    neighbors = around_idx(state['hope'].pop(0))
    return any(check_if_liberty(idx, state) for idx in neighbors)

# function check_if_liberty(ij, state) {
#     const s = aa_ref(state.stones, ...ij)
#     return !s ? false : !s.stone ? true : (push_hope(ij, s, state), false)
# }

def check_if_liberty(ij, state):
    i, j = ij
    s = aa_ref(state['stones'], i, j)
    if s is None:
        return False
    elif not s.get('stone'):
        return True
    else:
        push_hope(ij, s, state)
        return False

# function push_hope(ij, s, state) {
#     if (xor(s.black, state.is_black) || aa_ref(state.dead_map, ...ij)) {return}
#     state.hope.push(ij)
#     state.dead_pool.push(ij); aa_set(state.dead_map, ...ij, true)
# }

def push_hope(ij, s, state):
    i, j = ij
    if xor(s['black'], state['is_black']) or aa_ref(state['dead_map'], i, j):
        return
    state['hope'].append(ij)
    state['dead_pool'].append(ij)
    aa_set(state['dead_map'], i, j, True)

##############################################
# util

def xor(a, b):
    return bool(a) is (not b)

def letter_for_stone(s):
    return '.' if not s.get('stone') else 'X' if s.get('black') else 'O'

def around_idx(ij):
    around_idx_diff = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    i, j = ij
    return [(i + di, j + dj) for di, dj in around_idx_diff]

def move2idx(move, i_size, j_size):
    col_name = 'ABCDEFGHJKLMNOPQRST'
    idx_pass = (-1, -1)
    m = re.match(r"([A-HJ-T])((1[0-9])|[1-9])", move)
    if not m:
        return idx_pass
    col = m[1]
    row = m[2]
    return (i_size - int(row), col_name.index(col))

def aa_new(i_size, j_size, initializer):
    return [[initializer() for j in range(j_size)] for i in range(i_size)]

def aa_set(aa, i, j, val):
    aa[i][j] = val

def aa_ref(aa, i, j):
    if i < 0 or j < 0:
        return None
    try:
        return aa[i][j]
    except IndexError:
        return None

def aa_map(aa, f):
    return [[f(val) for val in row] for row in aa]

##############################################
# sample

# LizGoban> JSON.stringify(game.array_until().map(h => [h.is_black ? 'B' : 'W', h.move]))

if __name__ == "__main__":
    board_size = 5
    samples = [
        [["B","A5"],["W","A4"],["B","B5"],["W","B4"],["B","C4"],["W","C5"]],
        [["B","A5"],["W","A4"],["B","B5"],["W","B4"],["B","C4"],["W","C5"],["B","D5"],["W","D4"],["B","B5"]],
        [["B","A5"],["W","A4"],["B","B5"],["W","B4"],["B","C4"],["W","C5"],["B","D5"],["W","D4"],["B","B5"],["W","A5"],["B","B3"],["W","C5"]],
        [["B","A5"],["W","A4"],["B","B5"],["W","B4"],["B","C4"],["W","C5"],["B","D5"],["W","D4"],["B","B5"],["W","A5"],["B","B3"],["W","C5"],["B","A3"],["W","D3"],["B","B5"]],
    ]
    for moves in samples:
        b = board_from_moves(moves, board_size, board_size)
        print(board_to_str(b) + '\n')

# ..O..
# OOX..
# .....
# .....
# .....

# .X.X.
# OOXO.
# .....
# .....
# .....

# O.OX.
# OOXO.
# .X...
# .....
# .....

# .X.X.
# ..XO.
# XX.O.
# .....
# .....
