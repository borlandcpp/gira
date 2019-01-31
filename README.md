# Build
* `python3 -m venv venv`
* `. ./venv/bin/activate`
* `pip install -r requirements.txt`
* do `make` and then a `gira` command should be installed under `$HOME/bin`. Add that to your path.
    * never tried on Windows


# Usage
* prepare `$HOME/.config/gira.toml` with given example
* `gira --help` inside the git repository
    * e.g. `gira merge 17` merges PR 17 and update JIRA
