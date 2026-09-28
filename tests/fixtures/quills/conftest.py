"""The Quills' own tests, run by the core suite, against these datamodels.

In its own repository a Quill's tests read the datamodels the catalog pins;
here they read the local copy beside them, which is ahead of the release
while a change to both is being made, and needs no network.
"""

import os
from pathlib import Path

os.environ.setdefault("CLOUDMORROW_DATAMODELS", str(Path(__file__).parent / "datamodels"))
