"""Compatibility shim: the driver now lives in ``pdf2epub.engine.driver``.

Imported (``import main``) it is an identity alias of the driver module, so
``monkeypatch.setattr(main, ...)`` lands where the pipeline looks. Run directly
(``python main.py ...``) it forwards to the driver's ``main()``; the driver's
own ``__main__`` guard never fires when it is imported from the package.

When running from a source checkout without an install, ``src`` is added to
``sys.path`` so this script keeps working as before.
"""

import os
import sys

try:
    from pdf2epub.engine import driver as _driver
except ImportError:  # source tree, package not installed
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
    from pdf2epub.engine import driver as _driver

if __name__ == "__main__":
    raise SystemExit(_driver.main())

sys.modules[__name__] = _driver
