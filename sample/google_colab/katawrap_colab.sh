#!/bin/sh

# Setup KataGo and run katawrap on Google Colaboratory

# Usage (on Google Colaboratory):
# 
# Change runtime type to "GPU" in "runtime" menu first!
# 
# Click the folder mark in the left side to show the file list.
# Then drag this file there to upload it.
# 
# Input the following commands in a cell and run them.
# 
# !chmod a+x katawrap_colab.sh
# !./katawrap_colab.sh setup
# !ls katawrap_dir/sample/sgf/*.sgf | ./katawrap_colab.sh run -visits 400 > result.jsonl
# 
# Copy result.json to somewhere outside colab.
# See katawrap_sample.ipynb for its use.

myname=`basename $0`
mydir=`dirname $0`

usage () {
    cat<<_EOU_
$myname: Setup KataGo and run katawrap on Google Colaboratory
(Usage)
    $myname setup
        Download and setup KataGo.
    $myname run [ARGS...]
        Run "katawrap.py ARGS... katago ...".
    $myname help
        Show this message
(Example)
    $myname setup
    ls katawrap_dir/sample/sgf/*.sgf | $myname run -visits 400 > result.jsonl
_EOU_
}

#############################################
# URL

KATAGO_URL=https://github.com/lightvector/KataGo/releases/download/v1.12.0/katago-v1.12.0-cuda11.1-linux-x64.zip
KATAGO_MODEL_URL=https://github.com/lightvector/KataGo/releases/download/v1.12.1/b18c384nbt-uec.bin.gz
KATAWRAP_URL=https://github.com/kaorahi/katawrap/archive/refs/heads/_colab1.zip

#############################################
# check Google Colab

is_on_colab () {
    python -c "import google.colab" 2> /dev/null
}
exit_unless_colab () {
    is_on_colab && return
    echo "Not on Google Colaboratory. Exiting..."
    exit 1
}

#############################################
# downalod & setup

setup () {
    # fix
    echo "@@@@@@@@@@ Fix libzip issue..."
    LIBZIP=/usr/lib/x86_64-linux-gnu/libzip.so
    LIBZIP5=/usr/lib/x86_64-linux-gnu/libzip.so.5
    sudo apt install libzip-dev
    [ -e $LIBZIP5 ] && return
    [ -e $LIBZIP ] && sudo ln -s $LIBZIP $LIBZIP5
    # download
    echo "@@@@@@@@@@ Download..."
    curl -L $KATAGO_URL > katago.zip
    curl -L $KATAGO_MODEL_URL > default_model.bin.gz
    curl -L $KATAWRAP_URL > katawrap.zip
    # unzip
    echo "@@@@@@@@@@ Unzip..."
    mkdir katago_dir
    unzip -d katago_dir katago.zip
    mv default_model.bin.gz katago_dir
    unzip katawrap.zip
    mv katawrap-* katawrap_dir
    echo "@@@@@@@@@@ Done."
}

#############################################
# run

KATAWRAP=katawrap_dir/katawrap/katawrap.py
KATAGO=katago_dir/katago
CONFIG=katago_dir/analysis_example.cfg

run () {
    $KATAWRAP "$@" $KATAGO analysis -config $CONFIG
}

#############################################
# args

while [ "$1" != "" ];
do
  case "$1" in
    setup) mode="$1" ;;
    run) mode="$1" ;;
    *) break ;;
  esac
  shift
done

#############################################
# main

if [ "$mode" = "setup" ]; then
    exit_unless_colab
    setup
elif [ "$mode" = "run" ]; then
    exit_unless_colab
    run
else
    usage
    exit 0
fi
