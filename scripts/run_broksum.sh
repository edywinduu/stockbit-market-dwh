#!/bin/sh
set -e
python -m capture.main broksum --mode daily --trigger SCHEDULER
