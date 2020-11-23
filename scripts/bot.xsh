#!/usr/bin/env xonsh
from conda_forge_tick.migrators import *
$MIGRATORS = [Version(set()), JS()]
