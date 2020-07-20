import cProfile
from datetime import datetime
from .auto_tick import main as main_auto_tick
import tracemalloc


def profile_main(*args) -> None:
    """Profiles the specified auto-tick.py functions"""

    # TODO: add a logging here to inform it is enable
    # Get logger
    # logger = logging.getLogger('auto_tick.profile')...

    # TODO: Enable memory usage profiling at the line level, used to check for memory leaks
    #  I still need to find a good way to implement it)
    # tracemalloc.start()

    # Get current time
    now = datetime.now()
    current_time = now.strftime("%d-%m-%Y") + '_' + now.strftime("%H_%M_%S")

    # TODO: add a check for the profile folder directory ?

    # Enable CPU usage/function call timing/rate at the function level
    # Automatically dumps profile to `filename` for further analysis
    cProfile.run(f"main({args})", filename=f"profile\\auto_tick-{current_time}")


def main(*args):
    # run auto_tick
    profile_main(args)
