import contextlib
import os
import subprocess
import tempfile


# https://stackoverflow.com/questions/6194499/pushd-through-os-system
@contextlib.contextmanager
def pushd(new_dir):
    previous_dir = os.getcwd()
    os.chdir(new_dir)
    try:
        yield
    finally:
        os.chdir(previous_dir)


with tempfile.TemporaryDirectory() as tmpdir, pushd(tmpdir):
    subprocess.run(
        ["git", "clone", "--depth=1", "https://github.com/regro/cf-scripts.git"],
        check=True,
    )

    if os.path.exists(os.path.join("cf-scripts", "autotick-bot", "please.go")):
        go = True
    else:
        go = False

if not go:
    print("I could not find the file 'please.go' on master! Stopping!")
    subprocess.run(
        'echo "CI_SKIP=1" >> $GITHUB_ENV',
        shell=True,
    )
else:
    subprocess.run(
        'echo "CI_SKIP=" >> $GITHUB_ENV',
        shell=True,
    )
