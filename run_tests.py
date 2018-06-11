#!/usr/bin/env python
import sys
import pytest

if __name__ == '__main__':
    args = ['-v', 'tests']
    if len(sys.argv) > 1:
        args.extend(sys.argv[1:])
    print('pytest arguments: {}'.format(args))
    exit_res = pytest.main(args)
    sys.exit(exit_res)
