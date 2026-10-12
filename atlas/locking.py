import fcntl
from contextlib import contextmanager
from functools import wraps
from . import storage


@contextmanager
def operation_lock(kind):
    directory = storage.DATA / 'locks'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / (kind + '.lock')).open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('A ' + kind + ' operation is already running; wait for it to finish')
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def locked(kind):
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            with operation_lock(kind):
                return function(*args, **kwargs)
        return run
    return decorate
