import inspect
import os
from contextlib import contextmanager
from cProfile import Profile
from datetime import datetime
from functools import wraps


class Profiled(Profile):
    # extend init case for cProfile.Profile
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.disable()  # Profiling initially off.

    @contextmanager
    def __call__(self):
        self.enable()
        yield  # Execute code to be profiled.
        self.disable()


def profiling(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        # Profile dump information
        # get current time
        now = datetime.now()
        current_time = now.strftime("%d-%m-%Y") + "_" + now.strftime("%H_%M_%S")
        # process name -- aka profiler sub-folder
        process_name = os.path.basename(inspect.getfile(f)).replace(".py", "")
        # check dir
        os.makedirs(f"profiler/{process_name}", exist_ok=True)

        profiled = Profiled()  # Create class instance.
        with profiled():
            out = f(*args, **kwargs)
        # save stats into file
        profiled.dump_stats(f"profiler/{process_name}/{current_time}")

        return out

    return wrapper
