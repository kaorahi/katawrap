# Find fighter-type players from your SGF collection by KataGo

This note introduces a fun application of [KataGo](https://github.com/lightvector/KataGo), a very strong AI for the game Go. If you have a large collection of SGF files, you can find the top 20 players who like "games with many unsettled stones" using KataGo.

Here is an example to find the players who has the highest mean unsettledness at 120th move for Ubuntu Linux and a helper tool [katawrap](https://github.com/kaorahi/katawrap), where "unsettledness" is defined as the sum of (1 - |ownership|) over all existing stones on the board.

Replace YOUR_KATAGO_... below as appropreate.

```
$ sudo apt-get install python3-pandas jq
$ curl -L https://github.com/kaorahi/katawrap/archive/refs/heads/_colab1.zip > katawrap.zip
$ unzip katawrap.zip
$ cd katawrap-_colab1

$ ln -s YOUR_KATAGO_BINARY katago
$ ln -s YOUR_KATAGO_ANALYSIS_CONFIG analysis.cfg
$ ln -s YOUR_KATAGO_MODEL model.bin.gz

$ find ~/ -name '*.sgf' -print \
  | katawrap/katawrap.py -visits 1 -default '{"analyzeTurns": [120]}' \
      ./katago analysis -config analysis.cfg -model model.bin.gz \
  | jq -c '{sgfFile, PB, PW, unsettledness}' > unsettledness.jsonl

$ python3 <<_EOS_
import pandas as pd
import numpy as np

print('\nLoading...\n')
df = pd.read_json('unsettledness.jsonl', lines=True)

def pick(key, min_count):
    picked = df[[key, 'unsettledness']].groupby(key).describe().stack(0)
    return picked.query(f"count >= {min_count}").sort_values('mean', ascending=False)

# drop the players whose games are too few
min_count = 100

b = pick('PB', min_count)
w = pick('PW', min_count)

print('\nTop 20 unsettled players for black and white\n')
print(b.head(20))
print(w.head(20))

print('\nTop 20 settled players for black and white\n')
print(b.tail(20).iloc[::-1])
print(w.tail(20).iloc[::-1])
_EOS_
```
