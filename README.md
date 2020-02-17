# Usage
* prepare `$HOME/.config/gira.toml` with given example
* `cd` into a gitee project
* `gira merge 17` will merge PR 17 and update JIRA issue and cherry pick changes
    * It will try to cherry pick to the correct branches automatically **and** push to remote repo. If it fails, it Re-Opens the jira issue
    * `gira merge --no-autocp 17` prints out instruction for manual cherry-picking.
* `gira --help` inside the git repository


# Build
* `python3 -m venv venv`
* `. ./venv/bin/activate`
* `pip install -r requirements.txt`
* do `make` and then a `gira` command should be installed under `$HOME/bin`. Add that to your path.
    * never tried on Windows


# TODO
* All related party has to say OK. There seems to be a bug with gitee
* Automatically add Jira link when PR is created
* `gira.py start` to
    1. set component
    1. change to in progress
    1. wait for branch to be created
    1. checkout 
* When jira has 1.7.0 and 1.6.7-cmft, PR goes to release-1.6-cmft, should reject
* --force should ignore jira status
* Allow manipulation of jira issue
