import cProfile
import os
from functools import wraps
from datetime import datetime


# profiling decorator
def profiling():
    def _profiling(f):
        @wraps(f)
        def __profiling(*rgs, **kwargs):
            with cProfile.Profile() as prof:
                prof = cProfile.Profile()
                prof.enable()

                out_result = f(*rgs, **kwargs)
                f(*rgs, **kwargs)

                prof.disable()

                # get current time
                now = datetime.now()
                current_time = now.strftime("%d-%m-%Y") + "_" + now.strftime("%H_%M_%S")
                # process name -- aka profiler sub-folder
                process_name = os.path.basename(__file__)
                # check dir
                os.makedirs(f"profiler/{process_name}", exist_ok=True)
                # save stats into file
                prof.dump_stats(f"profiler/{process_name}/{current_time}")

                return out_result

        return __profiling

    return _profiling
