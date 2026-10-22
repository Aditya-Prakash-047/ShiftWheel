"""Entry point for PyInstaller and for `python run.py`."""
import sys

from shiftwheel.handoff import try_handoff

if __name__ == "__main__":
    if try_handoff(sys.argv):
        sys.exit(0)
    from shiftwheel.app import main
    sys.exit(main())
