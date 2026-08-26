#!/usr/bin/env python3
"""Allow `python -m mnemodex ...` without installation."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())