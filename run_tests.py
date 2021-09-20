#!/usr/bin/env python
import sys
import pytest

if __name__ == "__main__":
    args = ["-v", "tests", "-n", "2"]
    if len(sys.argv) > 1:
        args.extend(sys.argv[1:])
    print(f"pytest arguments: {args}")
    exit_res = pytest.main(args)
    sys.exit(exit_res)
