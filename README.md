# katawrap: batch analyzer of the game Go powered by KataGo

This is just a wrapper script to extend [katago analysis](https://github.com/lightvector/KataGo/blob/v1.11.0/docs/Analysis_Engine.md) for casual use on the command line:

```sh
$ ls *.sgf | katawrap.py ... > result.jsonl
```

It can be used to find the most heated games in your SGF collection, calculate the match rates with KataGo's top suggestions, and so on.

Let's leave the interaction with KataGo to katawrap and concentrate on analyzing the results.

* Introduction
  * [Examples](#examples)
  * [Download & Usage](#download)
* Features
  * [Overview](#overview)
  * [Extension of queries](#queries)
  * [Extension of responses](#responses)
  * [Command line options](#options)
  * [Limitations at present](#limitations)
* Appendix
  * [Tips (KataGo server)](#tips)
  * [Misc.](#misc)

## Introduction

### <a name="examples"></a>Examples

As with original KataGo, katawrap receives JSONL ([JSON Lines](https://jsonlines.org/)) queries from STDIN and reports JSONL responses to STDOUT basically. It also accepts a simplified query like

```json
{"sgfFile": "/foo/bar.sgf", "visits": 400}
```

instead of the original query:

```json
{"id": "1", "maxVisits": 400, "analyzeTurns": [0, 1, 2, ...], "moves": [["B", "D16"], ["W", "C17"], ...], "rules": "tromp-taylor", "komi": 7.5, "boardXSize": 19, "boardYSize": 19}
```

As a further extension, katawrap supports list of SGF files for its input. You can analyze all your SGF files in this way:

```sh
$ ls /foo/*.sgf \
  | ./katawrap.py -visits 400 \
      ./katago analysis -config analysis.cfg -model model.bin.gz \
  > result.jsonl
```

#### Load the results in Python (pandas):

```python
import pandas as pd
df = pd.read_json('./result.jsonl', lines=True)
print(df[['sgfFile', 'turnNumber', 'winrate']])

#             sgfFile  turnNumber   winrate
# 0      /foo/bar.sgf           0  0.461471
# 1      /foo/bar.sgf           1  0.507684
# 2      /foo/bar.sgf           2  0.516876
# ...             ...         ...       ...
```

#### Find the worst 5 blunders excluding those that have nothing to do with winning or losing.

(Continued from the previous example.)

```python
blunders = df.query('nextWinrateGain < -0.1') \
    .sort_values('nextScoreGain') \
    .head(5)[['sgfFile', 'turnNumber', 'nextScoreGain']]
print(blunders)

#          sgfFile  turnNumber  nextScoreGain
# 34  /foo/baz.sgf          34     -34.360468
# 76  /foo/qux.sgf          24     -33.851709
# 31  /foo/bar.sgf          31     -30.830034
# ...
```

See sample/ directory for more snippets in a [sample Jupyter notebook](https://github.com/kaorahi/katawrap/blob/main/sample/katawrap_sample.ipynb), e.g. finding the top 5 exciting games in your collection, calculating the match rates with KataGo's top 3 suggestions in first 50 moves.

#### Convert to CSV (with [jq](https://stedolan.github.io/jq/)):

```sh
$ cat result.jsonl \
  | jq -r '[.sgfFile, .turnNumber, (.winrate*100|round)] | @csv'
"/foo/bar.sgf",0,46
"/foo/bar.sgf",1,51
"/foo/bar.sgf",2,52
...
```

### <a name="download"></a>Download & Usage

Just download a ZIP file from [github](https://github.com/kaorahi/katawrap) (green "Code" button at the top), unzip it, and use it. No installation or external libraries are required, but [KataGo](https://github.com/lightvector/KataGo/) itself must be set up in advance.

See the above examples and samples/ directory for usage. (Change file names and paths as appropriate for your case.)

Alternatively, you can also upload another [Jupyter notebook](https://github.com/kaorahi/katawrap/blob/main/sample/google_colab/katawrap_sample_colab.ipynb) to Google Colaboratory and run KataGo + katawrap there. (Do not forget to change runtime type to GPU.)

## Features

### <a name="overview"></a>Overview

The main motivation of katawrap is batch analysis in simple pipe style:

```sh
$ ls *.sgf | katawrap.py ... | jq ...
```

Or equivalently:

```sh
$ ls *.sgf | katawrap.py ... > result.jsonl
$ cat result.jsonl | jq ...
```

For this purpose, katawrap provides several extensions to KataGo analysis engine.

* Support SGF inputs.
* Sort the responses.
* Add extra fields to the responses, e.g. `sgfFile`, to pass on sufficient information for subsequent processing. This is the key for the above style.
* Add further bonus outputs, e.g. unsettledness of the current board, the rank of the actually played move, etc.

### <a name="queries"></a>Extension of queries

The following fields are supported in addition to the original ones in JSON queries.

* `sgf` (string): Specify SGF text instead of `moves`, `rules`, etc.
* `sgfFile` (string): Specify the path of SGF file instead of `sgf`. Gzipped SGF is also accepted if the path ends with '.gz'. Use the option `-disable-sgf-file` if you need to disable `sgfFile` for some security reason.
* `analyzeTurnsFrom`, `analyzeTurnsTo`, `analyzeTurnsEvery` (integer): Specify "turns from N", "turns to N", "N every turns" instead of `analyzeTurns`. Any of three fields can be combined. "To N" includes N itself ("from 70 to 80" = [70, 71, ..., 80]).
* `analyzeLastTurn` (boolean): Add the endgame turn after the last move to `analyzeTurns`.
* `includeUnsettledness` (boolean): If true, report unsettledness (`includeOwnership` is turned on automatically). If not specified, defaults to true unless the option `-extra normal` is set. See the next section for details.

Each line in STDIN is assumed as JSON if it starts with `{`, `sgf` if with `(;`, or `sgfFile` otherwise. Some fixes are applied automatically:

* The required fields `id`, `rules`, etc. are added if they are missing.
* Invalid turns outside the given `moves` are dropped from `analyzeTurns`.
* All turns are analyzed by default when `analyzeTurns`, `analyzeTurnsEvery`, etc. are completely missing. If the option `-only-last` is given, only the last turn is analyzed as with original KataGo in such cases.

Aliases are also accepted:

* `from`, `to`, `every`, `last` = `analyzeTurnsFrom`, `analyzeTurnsTo`, `analyzeTurnsEvery`, `analyzeLastTurn`
* `visits` = `maxVisits`
* For `rules`, `cn` = `chinese`, `jp` = `japanese`, `kr` = `korean`, `nz` = `new-zealand`

### <a name="responses"></a>Extension of responses

Responses are sorted in the order of requests and turn numbers by default. This feature is disabled by the option `-order arrival`.

The fields in responses are extended depending on the value of the option `-extra`. They are KataGo-compatible for `-extra normal`. Several fields are added for `-extra rich`:

* `query`: Copy of the corresponding query (plus the following fields if `sgf` or `sgfFile` is given in the query)
  * `sgf`: SGF text.
  * `sgfProp`: SGF root properties. e.g. `{"PB": ["Intetsu"], "PW": ["Jowa"], ...}`
* `nextMove`: Next move in GTP style, e.g. "D4". Does not exist at the last turn.
* `nextMoveColor`: Color of `nextMove` ("B" or "W").
* `nextMoveSign`: The sign corresponding to `nextMoveColor` (+1 for "B", -1 for "W")
* `nextMoveRank`: The order of `nextMove` in `moveInfos` if exists.
* `nextWinrateGain`: Difference of `winrate` before and after `nextMove` (> 0 if superior to AI).
* `nextScoreGain`: Difference of `scoreLead` before and after `nextMove` (> 0 if superior to AI).
* `unsettledness`: The situation tend to be 'exciting' if this is greater than 20. It is defined as the sum of (1 - |ownership|) for all stones on the board. (It is indicated by red dots in the score chart in [LizGoban](https://github.com/kaorahi/lizgoban). [ref](https://github.com/sanderland/katrain/issues/215))
* `board`: 2D array of "X", "O", or "." for the current board.

Even more fields are added redundantly for '-extra excess'. This is the default.

* `nextRootInfo`: Copy of the rootInfo of the next turn if it exists.
* All fields in `rootInfo` and `query` are also copied directly under the response. This enables easy access in pandas and jq (`{turnNumber, winrate}` instead of `{turnNumber, winrate: .rootInfo.winrate}`).
* If exists, all fields in `sgfProp` are copied similarly. List elements are joined to one string for convenience, e.g., `"PB": "Shusaku", "BR": "4d", "PW": "Inseki", "WR": "8d", "RE": "B+2"`.

`moveInfos` is guaranteed to be sorted by `order`.

If the option `-order join` is given, katawrap reports a joined response for each `id` instead of multiple responses with different `turnNumber` for the same `id`. It has the fields `{"id":..., "query":..., "responses":[...]}` and "responses" is the sorted array of the original responses.

### <a name="options"></a>Command line options

* -default JSON: Use this for missing fields in queries. (ex.) '{"komi": 5.5, "includePolicy": true}'
* -override JSON: Override queries.
* -order ORDER: One of `arrival`, `sort` (default), or `join`.
  * `arrival`: Do not sort the responses.
  * `sort`: Sort the responses in the order of requests and turn numbers.
  * `join`: Report a joined response for each `id`. See the previous section for details.
* -extra EXTRA: One of `normal`, `rich`, or `excess` (default).
  * `normal`: Only report the fields in responses of original KataGo.
  * `rich`: Add extra fields to responses.
  * `excess`: In addition to `rich`, copy the contents of some fields directly under the response. See the previous section for details.
* -max-requests MAX_REQUESTS: Suspend sending queries when pending requests exceeds this number. (default = 1000)
* -sequentially: Do not read all input lines at once. This may be needed for very large inputs.
* -only-last: Analyze only the last turn when analyzeTurns is missing.
* -disable-sgf-file: Do not support sgfFile in query.
* -netcat: Use this option when netcat (nc) is used as katago command. See [Tips](#tips).
* -silent: Do not print progress info to stderr.
* -debug: Print debug info to stderr.

The following options are equivalent to `-override`, e.g., `-komi 5.5` = `-override '{"komi": 5.5}'`.

* -komi KOMI
* -rules RULES: Short names 'cn', 'jp', 'kr', 'nz' are also accepted.
* -visits MAX_VISITS
* -from ANALYZE_TURNS_FROM
* -to ANALYZE_TURNS_TO
* -every ANALYZE_TURNS_EVERY
* -last

Set `-from 50 -every 10 -last` to analyze the turns 50, 60, 70, ... and the endgame after the last move, for example.

Original KataGo is emulated to some extent by the following options.

```sh
katawrap.py -order arrival -extra normal -only-last -disable-sgf-file -silent
```

### <a name="limitations"></a>Limitations at present

* Only the main branch is analyzed in SGF.
* Handicap stones (AB[], AW[]) are regarded as normal moves in SGF. Related to that, specification of the initial player (PL[]) is ignored in SGF.
* `reportDuringSearchEvery` and `action` are not supported in queries.
* Error handling is almost missing.
* Newline characters must not appear in file names.
* The fields and the options may be changed in future. (Check "incompatible change!" messages in git log.)

Never consider to open "public katawrap server" as it accesses local files and may show their contents in error messages if `sgfFile` is given in the query. Though there is the option `-disable-sgf-file`, it is not tested sufficiently yet.

## Appendix

### <a name="tips"></a>Tips (KataGo server)

You may want local KataGo server to save startup time when you use katawrap repeatedly. See `man netcat` for an easiest way on Linux (`apt install netcat` in Debian-based distributions). Example:

(server)

```sh
$ mkfifo /tmp/f
$ cat /tmp/f \
  | ./katago analysis -config analysis.cfg -model model.bin.gz \
  | nc -klv localhost 1234 > /tmp/f
```

(client)

```sh
$ ls /foo/*.sgf \
  | ./katawrap.py -visits 400 \
      -netcat nc localhost 1234 \
  > result.jsonl
```

Note that KataGo keeps running even if you terminate the client with CTRL-C. The above option `-netcat` is necessary to cancel requests soon in such cases. This is supported from KataGo 1.12.0. For KataGo 1.11.0, you need to terminate the server if you want to stop remaining search immediately.

### <a name="misc"></a>Misc.

* tested with KataGo [1.12.2](https://github.com/lightvector/KataGo/releases/tag/v1.12.2).
* SGF parser is copied from KaTrain [v1.12](https://github.com/sanderland/katrain/releases/tag/v1.12).
* MIT License
* [Project home](https://github.com/kaorahi/katawrap)
