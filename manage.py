#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

    # A test run must not need Postgres or intake -- see EpbAppConfig.ready and
    # the hop-budget contract's definition of done. Set before Django starts,
    # because AppConfig.ready() fires during execute_from_command_line().
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        os.environ.setdefault("EPB_SKIP_BOOTSTRAP", "1")

    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
