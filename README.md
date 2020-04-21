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
    * **NOTE**: you have to use python3 installed by `brew`
* `. ./venv/bin/activate`
* `pip install -r requirements.txt`
* do `make` and then a `gira` command should be installed under `$HOME/bin`. Add that to your path.
    * never tried on Windows


# TODO
* All related party has to say OK. There seems to be a bug with gitee
* Should refuse to merge Epic or parent task
* When jira has 1.7.0 and 1.6.7-cmft, PR goes to release-1.6-cmft, should reject
* Add `merge --continue` for when cherry pick failed
* Should assign jira issue to a tester
* Support non merge commit
* `show pr` fails
* reomve CLOUD-222 from finish
