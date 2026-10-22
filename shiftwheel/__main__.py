import sys

from shiftwheel.handoff import try_handoff

if try_handoff(sys.argv):
    sys.exit(0)

from shiftwheel.app import main  # noqa: E402

sys.exit(main())
