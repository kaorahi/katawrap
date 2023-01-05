# katawrap: Add convenient features to KataGo analysis engine for the game Go

This is just a wrapper script to extend [katago analysis](https://github.com/lightvector/KataGo/blob/v1.11.0/docs/Analysis_Engine.md) for casual use on the command line:

```sh
$ ls *.sgf | katawrap.py ... | jq ...
```

It can be used to find the most heated matches in your game collection, calculate the match rates with KataGo's top suggestions, and so on.

## Table of contents

* [Examples](#examples)
* [Overview](#overview)
* [Download](#download)
* [Extension of queries](#queries)
* [Extension of responses](#responses)
* [Command line options](#options)
* [Limitations at present](#limitations)
* [Tips (KataGo server)](#tips)
* [Misc.](#misc)

## <a name="examples"></a>Examples

As with original KataGo, katawrap receives JSONL ([JSON Lines](https://jsonlines.org/)) queries from STDIN and reports JSONL responses to STDOUT basically. It also accepts a simplified query like

```json
{"sgfFile": "/foo/bar.sgf", "visits": 400, "every": 10}
```

instead of the original query:

```json
{"id": "1", "maxVisits": 400, "analyzeTurns": [0, 10, 20, ...], "moves": [["B", "D16"], ["W", "C17"], ...], "rules": "tromp-taylor", "komi": 7.5, "boardXSize": 19, "boardYSize": 19}
```

By convenient extensions, you can analyze all your SGF files in this way:

```sh
$ ls /foo/*.sgf \
  | ./katawrap.py -visits 1 -every 100 \
      ./katago analysis -config analysis.cfg -model model.bin.gz \
  | jq -r '[.sgfFile, .turnNumber, (.winrate*100|round)] | @csv'
"/foo/a.sgf",0,45
"/foo/a.sgf",100,23
"/foo/a.sgf",200,2
"/foo/a.sgf",267,0
"/foo/b.sgf",0,46
"/foo/b.sgf",100,67
...
```

Find the top 5 exciting games in your collection:

```sh
$ ls /foo/*.sgf \
  | ./katawrap.py -visits 1 -every 20 \
      ./katago analysis -config analysis.cfg -model model.bin.gz \
  | jq -s 'map(select(0.3 < .winrate and .winrate < 0.7))
    | group_by(.sgfFile) | map(max_by(.unsettledness)) | sort_by(- .unsettledness)
    | limit(5; .[])
    | {sgfFile, turnNumber, winrate, scoreLead, unsettledness}'
```

Calculate the match rates with KataGo's top 3 suggestions in first 50 moves:

```sh
$ ls /foo/*.sgf \
  | ./katawrap.py -visits 100 \
      ./katago analysis -config analysis.cfg -model model.bin.gz \
  | jq -sc 'map(select(0 <= .turnNumber and .turnNumber < 50 and .playedColor != null))
    | group_by(.sgfFile)[] | group_by(.playedColor)[]
    | [(.[0] | .sgfFile, (.sgfProp|.PB[0]+"(B)", .PW[0]+"(W)"), .playedColor),
       (map(.playedOrder) | (map(select(. < 3 and . != null))|length) / length)]'
```

## <a name="overview"></a>Overview

The main motivation of katawrap is batch analysis in simple pipe style:

```sh
$ ls *.sgf | katawrap.py ... | jq ...
```

For this purpose, katawrap provides several extensions to KataGo analysis engine.

* Support SGF inputs.
* Sort the responses.
* Add extra fields to the responses, e.g. `sgfFile`, to pass on sufficient information for subsequent processing. This is the key for the above style.
* Add further bonus outputs, e.g. unsettledness of the current board, the rank of the actually played move, etc.

## <a name="download"></a>Download

Just download a ZIP file from [github](https://github.com/kaorahi/katawrap) (green "Code" button at the top), unzip it, and use it. No installation or external libraries are required, but [KataGo](https://github.com/lightvector/KataGo/) itself must be set up in advance, of course. See the above examples for usage.

## <a name="queries"></a>Extension of queries

The following fields are supported in addition to the original ones in JSON queries.

* `sgf` (string): Specify SGF string instead of `moves`, `rules`, etc.
* `sgfFile` (string): Specify the path of SGF file instead of `sgf`. Gzipped SGF is also accepted if the path ends with '.gz'. Use the option `-disable-sgf-file` if you need to disable `sgfFile` for some security reason.
* `analyzeTurnsFrom`, `analyzeTurnsTo`, `analyzeTurnsEvery` (integer): Specify "turns from N", "turns to N", "N every turns" instead of `analyzeTurns`. Any of three fields can be combined. "To N" includes N itself ("from 70 to 80" = [70, 71, ..., 80]). The last turn after endgame is also included unless `analyzeTurnsTo` is specified explicitly.
* `includeUnsettledness` (boolean): If true, report unsettledness (`includeOwnership` is turned on automatically). If not specified, defaults to true unless the option `-extra normal` is set. See the next section for details.

Each line in STDIN is assumed as JSON if it starts with `{`, `sgf` if with `(;`, or `sgfFile` otherwise. Some fixes are applied automatically:

* The required fields `id`, `rules`, etc. are added if they are missing.
* Turns outside the given `moves` are dropped from `analyzeTurns`.
* By default, all turns are analyzed when `analyzeTurns`, `analyzeTurnsEvery`, etc. are completely missing. If the option `-only-last` is given, only the last turn is analyzed as with original KataGo in such cases.

Aliases are also accepted:

* `from`, `to`, `every` = `analyzeTurnsFrom`, `analyzeTurnsTo`, `analyzeTurnsEvery`
* `visits` = `maxVisits`
* For `rules`, `cn` = `chinese`, `jp` = `japanese`, `kr` = `korean`, `nz` = `new-zealand`

## <a name="responses"></a>Extension of responses

Responses are sorted in the order of requests and turn numbers by default. This feature is disabled by the option `-order arrival`.

The fields in responses are extended depending on the value of the option `-extra`. They are KataGo-compatible for `-extra normal`. Several fields are added for `-extra rich`:

* `playedMove`: Next move in GTP style, e.g. "D4". Does not exist at the last turn.
* `playedColor`: Color of `playedMove` ("B" or "W").
* `playedOrder`: The order of `playedMove` in `moveInfos` if exists.
* `unsettledness`: The situation tend to be 'exciting' if this is greater than 20. It is defined as the sum of (1 - |ownership|) for all stones on the board. (It is indicated by red dots in the score chart in [LizGoban](https://github.com/kaorahi/lizgoban). [ref](https://github.com/sanderland/katrain/issues/215))
* `query`: Copy of the corresponding query (plus the following fields if `sgf` or `sgfFile` is given in the query)
  * `sgf`: SGF text.
  * `sgfProp`: SGF root properties. e.g. `{"PB": ["Intetsu"], "PW": ["Jowa"], ...}`
* `board`: 2D array of "X", "O", or "." for the current board.

Further more fields are added redundantly for '-extra excess'. This is the default.

* `nextRootInfo`: Copy of the rootInfo of the next turn if it exists.
* All fields in `rootInfo` and `query` are also copied directly under the response. This enables easy access in jq as `{turnNumber, winrate}` instead of `{turnNumber, winrate: .rootInfo.winrate}`.

`moveInfos` is guaranteed to be sorted by `order`.

## <a name="options"></a>Command line options

* -default JSON: Use this for missing fields in queries. (ex.) '{"komi": 5.5, "includePolicy": true}'
* -override JSON: Override queries.
* -order ORDER: One of `arrival`, `sort` (default), or `join`.
  * `arrival`: Do not sort the responses.
  * `sort`: Sort the responses in the order of requests and turn numbers
  * `join`: Report a joined response instead of multiple responses with different `turnNumber` for the same `id`. It has the fields `{"id":..., "query":..., "responses":[...]}` and "responses" is the sorted array of the original responses.
* -extra EXTRA: One of `normal`, `rich`, or `excess` (default).
  * `normal`: Only report the fields in responses of original KataGo.
  * `rich`: Add extra fields to responses.
  * `excess`: In addition to `rich`, copy the contents of some fields directly under the response. See the previous section for details.
* -only-last: Analyze only the last turn when analyzeTurns is missing.
* -disable-sgf-file: Do not support sgfFile in query.
* -silent: Do not print progress info to stderr.
* -debug: Print debug info to stderr.

The following options are equivalent to `-override`. For example, `-komi 5.5` = `-override '{"komi": 5.5}'`.

* -komi KOMI
* -rules RULES: Short names 'cn', 'jp', 'kr', 'nz' are also accepted.
* -visits VISITS
* -from FROM
* -to TO
* -every EVERY

Original KataGo is emulated to some extent by the following options.

```sh
katawrap.py -order arrival -extra normal -only-last -disable-sgf-file -silent
```

## <a name="limitations"></a>Limitations at present

* Only the main branch is analized in SGF.
* Handicap stones (AB[], AW[]) are regarded as normal moves in SGF. Related to that, specification of the initial player (PL[]) is ignored in SGF.
* `reportDuringSearchEvery` and `action` are not supported in queries.
* Error handlings are almost missing.
* The fields and the options may be changed in future.

Never consider to open "public katawrap server" as it accesses local files and may show their contents in error messages if `sgfFile` is given in the query. Though there is the option `-disable-sgf-file`, it is not tested sufficiently yet.

## <a name="tips"></a>Tips (KataGo server)

You may want local KataGo server to save startup time when you use katawrap repeatedly. See `man netcat` for an easiest way on Linux. Example:

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
  | ./katawrap.py -visits 1 -every 100 \
      nc localhost 1234 \
  | jq '{sgfFile, turnNumber, winrate}'
```

Note that KataGo keeps running even if you terminate the client with CTRL-C. You also need to terminate the server if you want to stop remaining search immediately.

## <a name="misc"></a>Misc.

* tested with KataGo [1.11.0](https://github.com/lightvector/KataGo/releases/tag/v1.11.0).
* SGF parser is copied from KaTrain [v1.12](https://github.com/sanderland/katrain/releases/tag/v1.12).
* MIT License
* [Project home](https://github.com/kaorahi/katawrap)
