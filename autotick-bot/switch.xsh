#!/usr/bin/env xonsh
cd autotick-bot

if 'please.go' in @(ls):
    mv please.go please.stop
    git add please.stop
    s = '[ci skip] stop in the name of bot'
else:
    mv please.stop
    git add please.go
    s = 'let it go, let it gooooo'
git commit -am @(f"{s}")
git push
