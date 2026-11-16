import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from capture.sync_session import main

if __name__ == "__main__":
    main()
