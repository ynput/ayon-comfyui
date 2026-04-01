"""Small utility for rewriting a json settings file to no longer have

'comfy_setting_name' but plain 'name' keys instead.
Otherwise, migrating settings can cause crashes.
"""

import re
import sys
from pathlib import Path

RGX_NAME = re.compile(r"\w+_name")

if __name__ == "__main__":
    cleanup_json = Path(sys.argv[1])
    text = cleanup_json.read_text("utf-8")
    cleanup = re.sub(RGX_NAME, "name", text)
    new_stem = cleanup_json.stem + "_migrated"
    (cleaned_json := cleanup_json.with_stem(new_stem)).write_text(cleanup)
    print("Migrated settings here:", str(cleaned_json))
