#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

from news.models import Headline
print("EN:", Headline.objects.filter(language=1).count())
print("ML:", Headline.objects.filter(language=2).count())

def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'DataFlair_NewsAggregator.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
