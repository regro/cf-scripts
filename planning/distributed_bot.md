# Distributing the `conda-forge` Autotick Bot

## Overview

## Proposal

## Random Notes / Thoughts

- We have started in on automerge capability for the bot (see https://github.com/regro/cf-autotick-bot-action).
- This GitHub Action could be the basis for distributing the bot updates using a special "utility" branch
  on each feedstock.
- We want to avoid inadvertently escalating permissions. Thus a feedstock should only be able to write 
  to itself.
- A distributed bot could use more costly computations.
- Any local migration action (in the sense that the code only needs the state of the feedstocks deps)
  can be moved to the bot.
- We still need to be planning for ways to quickly back out bad migrations or merges. A decentralized
  bot might pose issues in these cases.
- Moving to `dynamodb` will help solve isses around multiple process interacting with the graph.
- As we distribute things, I think we can move all work to github actions and have the autotick bot do
  only tasks that relate to building the graph and planning migrations.
