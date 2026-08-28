COURSE_TITLE = "Systematic Innovation: Scaling Up from a Hunch - February 2022"
COURSE_CODE = "SISH-ENG-001-FEB22"

DROPBOX_ROOT = "/Users/jmill/MIT Dropbox/Jonathan Miller/teaching/Systematic Innovation"
CARTRIDGE_DIR = f"{DROPBOX_ROOT}/systematic-innovation-scaling-up-from-a-hunch-february-2022-export"
CAMPUS_DIR = f"{DROPBOX_ROOT}/campus.mitpeonline.com"
GDRIVE_DIR = ("/Users/jmill/Library/CloudStorage/GoogleDrive-i.am.jonathanmiller@gmail.com"
              "/My Drive/Teaching/2021Q4/systematic innovation")
PROVENANCE_PDF = ("/Users/jmill/Downloads/Learning Facilitator for Systematic Innovation"
                  " • i.am.jonathanmiller@gmail.com.pdf")

OUTPUT_ROOT = "/Volumes/Desk SSD/SystematicInnovation-Archive"

# Discovered from the cartridge's iframe srcs. The user-supplied list had only 5;
# M5 and INFO were missing.
ELUCIDAT_PROJECTS = {
    "M1":   "5f7356442004e-5f7c8b919a261",
    "M2":   "5f8966ad7f361-5f8ee6beacce6",
    "M3":   "5faa7fce0007f-5fae4255164d6",
    "M4":   "5fb68ea13b3de-5fbf667f2742b",
    "M5":   "5fc61e2550add-5fd774d58f4ee",
    "M6":   "5fe0caa101abf-60783a3aa5ce5",
    "INFO": "5f59f641d14f2-5f5a024ff039d",
}

ELUCIDAT_REFERER = "https://learning.elucidat.com/"
STUDENT_WORK_DIR_GLOB = "*_submissions"
STUDENT_WORK_FILE_GLOB = "*_text.html"
CONTACTSHEET_MIN_SECONDS = 180

# Campus media folders map onto cartridge sections. "Module N" folders land in
# the first cartridge section whose title starts with that name -- Module 1 is
# split across three sections, and its media belongs with Part 1. `pre` and
# `post` have no cartridge section and get their own top-level directories.
CAMPUS_FOLDER_MAP = {
    "Module 1": "Module 1 - Part 1",
    "Module 2": "Module 2",
    "Module 3": "Module 3",
    "Module 4": "Module 4",
    "Module 5": "Module 5",
    "Module 6": "Module 6",
    "pre": "__orientation__",
    "post": "__closing__",
}
ORIENTATION_DIR = "orientation"
CLOSING_DIR = "closing"
