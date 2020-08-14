import cProfile
import os
from functools import wraps
from datetime import datetime


# profiling decorator
def profiling():
    def _profiling(f):
        @wraps(f)
        def __profiling(*rgs, **kwargs):
            prof = cProfile.Profile()
            prof.enable()

            # out_result = f(*rgs, **kwargs) should we expect an output ?
            f(*rgs, **kwargs)

            prof.disable()

            # get current time
            now = datetime.now()
            current_time = now.strftime("%d-%m-%Y") + "_" + now.strftime("%H_%M_%S")
            # function name -- aka profiler sub-folder
            function_name = f.__name__
            # check dir
            os.makedirs(f"profiler/{function_name}", exist_ok=True)
            # save stats into file
            prof.dump_stats(f"profiler/{function_name}/{current_time}")

            return  # out_result

        return __profiling

    return _profiling
