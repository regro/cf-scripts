import contextlib
import copy
import os
import shutil
import subprocess


# https://stackoverflow.com/questions/6194499/pushd-through-os-system
@contextlib.contextmanager
def pushd(new_dir: str):
    previous_dir = os.getcwd()
    os.chdir(new_dir)
    try:
        yield
    finally:
        os.chdir(previous_dir)


def eval_cmd(cmd: list[str], **kwargs) -> str:
    """run a command capturing stdout

    stderr is printed for debugging
    any kwargs are added to the env
    """
    env = copy.deepcopy(os.environ)
    timeout = kwargs.pop("timeout", None)
    env.update(kwargs)
    c = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        env=env,
        timeout=timeout,
    )
    if c.returncode != 0:
        print(c.stdout.decode("utf-8"), flush=True)
        c.check_returncode()

    return c.stdout.decode("utf-8")


def _all_fnames(root_dir):
    fnames = set()
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            fnames.add(os.path.join(root, file))
        for dr in dirs:
            if dr in [".", ".."]:
                continue
            fnames.add(os.path.join(root, dr))

    return fnames


def sync_dirs(source_dir, dest_dir, ignore_dot_git=True, update_git=True):
    """Sync the contents of source_dir to dest_dir.

    By default, this function ignores `.git` directories and will update the git index
    via `git add` and `git rm`.

    Parameters
    ----------
    source_dir : str
        The source directory
    dest_dir : str
        The destination directory
    ignore_dot_git : bool, optional
        Ignore .git directories, by default True
    update_git : bool, optional
        Update the git index via `git add` and `git rm`, by default True
    """
    os.makedirs(dest_dir, exist_ok=True)

    src_fnames = _all_fnames(source_dir)
    dest_fnames = _all_fnames(dest_dir)

    # remove files in dest that do not exist in source
    for dest_fname in dest_fnames:
        if ignore_dot_git and ".git" in dest_fname.split(os.path.sep):
            continue

        if not os.path.exists(dest_fname):
            continue

        rel_fname = os.path.relpath(dest_fname, dest_dir)
        src_fname = os.path.join(source_dir, rel_fname)
        if src_fname not in src_fnames:
            if os.path.isdir(dest_fname):
                shutil.rmtree(dest_fname)
            else:
                os.remove(dest_fname)
                if update_git:
                    subprocess.run(
                        ["git", "rm", "-f", rel_fname],
                        check=True,
                        capture_output=True,
                        cwd=dest_dir,
                    )

    for src_fname in src_fnames:
        if ignore_dot_git and ".git" in src_fname.split(os.path.sep):
            continue

        rel_fname = os.path.relpath(src_fname, source_dir)
        dest_fname = os.path.join(dest_dir, rel_fname)
        if os.path.isdir(src_fname):
            os.makedirs(dest_fname, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(dest_fname), exist_ok=True)
            shutil.copyfile(src_fname, dest_fname)
            if update_git:
                subprocess.run(
                    ["git", "add", "-f", rel_fname],
                    check=True,
                    capture_output=True,
                    cwd=dest_dir,
                )


def _chmod_plus_rw(file_or_dir):
    st = os.stat(file_or_dir)
    os.chmod(file_or_dir, st.st_mode | 0o666)


def chmod_plus_rw(file_or_dir, recursive=False):
    if recursive and os.path.isdir(file_or_dir):
        for root, dirs, files in os.walk(file_or_dir):
            for d in dirs:
                _chmod_plus_rw(os.path.join(root, d))
            for f in files:
                _chmod_plus_rw(os.path.join(root, f))
    else:
        _chmod_plus_rw(file_or_dir)
