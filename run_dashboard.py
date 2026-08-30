"""
Run the dashboard straight from this folder, without installing the package.

If you install it instead (pip install .) you can simply run:

    vendor-dashboard
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from vendor_system.dashboard import main

if __name__ == "__main__":
    main()
