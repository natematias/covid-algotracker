#!/usr/bin/env python3

import os
import shutil
import sys
from pathlib import Path

import logutil

ENV = os.environ['CS_ENV']
BASE_DIR = os.environ['ALGOTRACKER_BASE_DIR']
OUTPUT_BASE_DIR = os.environ['ALGOTRACKER_OUTPUT_DIR']
PAGE_BASE_DIR = os.environ['ALGOTRACKER_PAGE_DIR']
sys.path.append(BASE_DIR)

AIRBRAKE_ENABLED = bool(os.environ["ALGOTRACKER_AIRBRAKE_ENABLED"])
LOG_LEVEL = int(os.environ["ALGOTRACKER_LOG_LEVEL"])
log = logutil.get_logger(ENV, AIRBRAKE_ENABLED, LOG_LEVEL, handle_unhandled_exceptions=True)

def main():
    log.info("Archiving the latest report...")

    data_dir_paths = Path(OUTPUT_BASE_DIR, "reddit")
    latest_data_dir_name = max(str(entry.name) for entry in data_dir_paths.iterdir() if entry.is_dir())
    new_page_dir_path = Path(PAGE_BASE_DIR, "reddit", latest_data_dir_name)
    log.info("Creating directory %s.", str(new_page_dir_path))
    try:
        Path.mkdir(new_page_dir_path, parents=True)
    except FileExistsError:
        pass

    index_path = Path(data_dir_paths, "..", "..", "index.html")
    new_page_path = Path(new_page_dir_path, "%s_index.html" % latest_data_dir_name)
    log.info("Copying the report file to %s.", str(new_page_path))
    shutil.copy(str(index_path), str(new_page_path))
    
    log.info("Latest report archived.")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass

