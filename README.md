# Build
* `python3 -m venv venv`
* `. ./venv/bin/activate`
* `pip install -r requirements.txt`
* do `make` and then a `gira` command should be installed under `$HOME/bin`. Add that to your path.
    * never tried on Windows


# Usage
* prepare `$HOME/.config/gira.toml` with given example
* `cd` into a gitee project
* `gira merge 17` will merge PR 17 and update JIRA issue and give instructions for cherry picking
* `gira --help` inside the git repository


# TODO
* Allow manipulation of jira issue
* All related party has to say OK. There seems to be a bug with gitee
* Should stop when git command fails
* Default to auto cherry-pick
* Automatically add Jira link when PR is created
