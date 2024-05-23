import contextlib
import copy
import functools
import logging
import os
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor

logger = logging.getLogger(__name__)


# https://stackoverflow.com/questions/6194499/pushd-through-os-system
@contextlib.contextmanager
def pushd(new_dir: str):
    previous_dir = os.getcwd()
    os.chdir(new_dir)
    try:
        yield
    finally:
        os.chdir(previous_dir)


@contextlib.contextmanager
def override_env(name, value):
    """Override an environment variable temporarily."""
    old = os.environ.get(name)
    try:
        os.environ[name] = value
        yield
    finally:
        if old is None:
            del os.environ[name]
        else:
            os.environ[name] = old


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


def _chmod_plus_rw(file_or_dir, skip_on_error=False):
    try:
        st = os.stat(file_or_dir)
        os.chmod(file_or_dir, st.st_mode | 0o666)
    except Exception as e:
        if not skip_on_error:
            raise e


def _chmod_plus_rwx(file_or_dir, skip_on_error=False):
    try:
        st = os.stat(file_or_dir)
        os.chmod(file_or_dir, st.st_mode | 0o777)
    except Exception as e:
        if not skip_on_error:
            raise e


def chmod_plus_rwX(file_or_dir, recursive=False, skip_on_error=False):
    """chmod +rwX a file or directory.

    Parameters
    ----------
    file_or_dir : str
        The file or directory to chmod.
    recursive : bool, optional
        Whether to chmod recursively, by default False.
    skip_on_error : bool, optional
        Whether to skip files where chmod fails or to raise. Default is False.
    """
    if os.path.isdir(file_or_dir):
        _chmod_plus_rwx(file_or_dir, skip_on_error=skip_on_error)
        if recursive:
            for root, dirs, files in os.walk(file_or_dir):
                for d in dirs:
                    _chmod_plus_rwx(os.path.join(root, d), skip_on_error=skip_on_error)
                for f in files:
                    _chmod_plus_rw(os.path.join(root, f), skip_on_error=skip_on_error)
    else:
        _chmod_plus_rw(file_or_dir, skip_on_error=skip_on_error)


def get_user_execute_permissions(path):
    """Get the user execute permissions of directory `path` and all of its contents.

    Parameters
    ----------
    path : str
        The path to the directory.

    Returns
    -------
    dict
        A dictionary mapping file paths to True if the user has execute permission or False otherwise.
    """
    fnames = _all_fnames(path)
    perms = {}
    for fname in sorted(fnames):
        if ".git" in fname.split(os.path.sep):
            continue

        perm = os.stat(fname).st_mode
        has_user_exe = os.stat(fname).st_mode & 0o100
        key = os.path.relpath(fname, path)
        logger.debug(f"got permissions of {key} as {perm:#o}")
        perms[key] = has_user_exe
    return perms


def reset_permissions_with_user_execute(path, perms):
    """Set the execute permissions of a directory `path` and all of its contents
    using the default umask and whether or not exec bits should be set.

    This function is meant to mimic how git sets permissions for files and directories.

    Parameters
    ----------
    path : str
        The path to the directory.
    perms : dict
        A dictionary mapping file paths to True if the user has execute permission or False otherwise.
    """
    fnames = sorted(_all_fnames(path))
    for fname in fnames:
        if ".git" in fname.split(os.path.sep):
            continue

        if os.path.exists(fname):
            key = os.path.relpath(fname, path)
            has_exec = perms.get(key, False)

            if os.path.isdir(fname) or has_exec:
                new_perm = get_dir_or_exec_default_permissions()
            else:
                new_perm = get_file_default_permissions()

            logger.debug(
                f"setting permissions of {key} to {new_perm:#o} from {os.stat(fname).st_mode:#o}"
            )
            os.chmod(fname, new_perm)


def _current_umask():
    tmp = os.umask(0o666)
    os.umask(tmp)
    return tmp


@functools.lru_cache(maxsize=1)
def get_umask():
    """Get the current umask."""
    # done in a separate process for safety
    with ProcessPoolExecutor(max_workers=1) as pool:
        return pool.submit(_current_umask).result()


@functools.lru_cache(maxsize=1)
def get_dir_or_exec_default_permissions():
    """Get the default permissions for directories or executables."""
    return 0o777 ^ get_umask()


@functools.lru_cache(maxsize=1)
def get_file_default_permissions():
    """Get the default permissions for files."""
    return 0o666 ^ get_umask()
