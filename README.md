# Usage
* prepare `$HOME/.config/gira.toml` with given example
* `cd` into a gitee project
* `gira merge 17` will merge PR 17 and update JIRA issue and cherry pick changes
    * It will try to cherry pick to the correct branches automatically **and** push to remote repo. If it fails, it Re-Opens the jira issue
    * `gira merge --no-autocp 17` prints out instruction for manual cherry-picking.
* `gira --help` inside the git repository

## Example Config File

    [jira]
    user = "bot"
    passwd = "XXXX"
    url = "https://jira.wise2c.com"

    [gitee]
    user = "borlandc"
    token = "XXXX"


# Build
* `python3 -m venv venv`
    * **NOTE**: you have to use python 3.9 installed by `brew`
* `. ./venv/bin/activate`
* `make env` to setup the build environment
* do `make` and then a `gira` command should be installed under `/usr/local/bin`.
    * never tried on Windows


# TODO
* git rev-parse --show-toplevel
* add command to browse pipeline page
* All related party has to say OK. There seems to be a bug with gitee
* When jira has 1.7.0 and 1.6.7-cmft, PR goes to release-1.6-cmft, should reject
* Add `merge --continue` for when cherry pick failed
* Should assign jira issue to a tester
* Support non merge commit
