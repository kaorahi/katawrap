# Sample of analysis with katawrap

You may like to skip this document and open sample.ipynb directly for a quick look at what it looks like. You can try it with prepared analysis results immediately.

## About this directory

* README.md: instructions (this file)
* sgf/: sample SGF files
* sample_result.jsonl: results of analysis by KataGo with katawrap
* sample.ipynb: usege of analysis results with Python (Jupyter notebook)

## Note

This document assumes that you can run katago on the command line as follows.

```sh
$ katago -config analysis.cfg -model model.bin.gz
```

Change this part as appropriate for your case in the following examples.

## Prepare analysis results

Run katawrap to dump the results.

```sh
$ ls sgf/*.sgf \
  | ../katawrap/katawrap.py -visits 400 \
      katago -config analysis.cfg -model model.bin.gz \
  > result.jsonl
```

If this is too slow, try decreasing visits and/or analyzing every N turns, for example.

```sh
$ ls sgf/*.sgf \
  | ../katawrap/katawrap.py -visits 100 -every 25 \
      katago -config analysis.cfg -model model.bin.gz \
  > result.jsonl
```

## Run Jupyter notebook

```sh
$ jupyter notebook sample.ipynb
```

Rewrite `'sample_result.jsonl'` with `'result.jsonl'` at the beginning of the notebook. Then run all!

## Bonus: jq version

Find the top 5 exciting games in your collection:

```sh
$ cat result.jsonl \
  | jq -s 'map(select(0.2 < .winrate and .winrate < 0.8))
    | group_by(.sgfFile) | map(max_by(.unsettledness)) | sort_by(- .unsettledness)
    | limit(5; .[])
    | {sgfFile, turnNumber, winrate, scoreLead, unsettledness}'
```

Calculate the match rates with KataGo's top 3 suggestions in first 50 moves:

```sh
$ cat result.jsonl \
  | jq -sc 'map(select(0 <= .turnNumber and .turnNumber < 50 and .nextMoveColor != null))
    | group_by(.sgfFile)[] | group_by(.nextMoveColor)[]
    | [(.[0] | .sgfFile, .PB, .PW, .nextMoveColor),
       (map(.nextMoveRank) | (map(select(. < 3 and . != null))|length) / length)]'
```