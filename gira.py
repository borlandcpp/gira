#!/usr/bin/env python

import os
import sys
import json
import re
import urllib
import requests
import giturlparse
import toml
from git import Repo
from jira import JIRA


_jira_url = "http://jira.wise2c.com"
_conf = None


class GiteeError(Exception):
    pass


class Gitee(object):
    api_root = "https://gitee.com/api/v5/repos/%s/%s"

    def __init__(self, user, token):
        self.user = user
        self.token = token
        try:
            self.git = Git()
            self.owner, self.repo = self.git.info()
        except Exception:  # TODO: catch narrower exceptions
            raise GiteeError("You should run this from within a gitee repo")
        self._root = Gitee.api_root % (self.owner, self.repo)

    def _url(self, urls, params):
        if params is not None:  # this is for GET
            params['access_token'] = self.token
            return os.path.join(self._root, *urls) + '?' + urllib.parse.urlencode(params)
        else:  # for PUT and POST
            return os.path.join(self._root, *urls)

    def get(self, url, params):
        return requests.get(self._url(url, params))

    def get_pr(self, pr):
        res = self.get(("pulls", pr), {})
        if not res.status_code == 200:
            raise GiteeError("RES %d" % res.status_code)
        return res.text

    def merge(self, pr):
        res = requests.put(
            self._url(("pulls", pr, "merge"), None),
            data = {
                "access_token": self.token,
                "owner": self.owner,
                "repo": self.repo,
                "number": pr
            }
        )
        if not res.status_code == 200:
            raise GiteeError(res.text)


class PR(object):
    def __init__(self, jsn):
        self.raw = jsn
        # TODO: handle exceptions
        self.data = json.loads(jsn)

    def good(self):
        return len(self.data["assignee"]) >= 1 and \
               len(self.data["tester"]) >= 1

    def merged(self):
        return self.data["state"] == "merged"

    def dump(self):
        print(self.raw)

    def _get_jira_issue_id(self):
        pat = re.compile("^([A-Z]*-\d*)")
        mo = re.match(pat, self.title)
        if not mo:
            raise ValueError("Invalid PR title: %s" % self.title)
        return mo.group(1)

    def __getattr__(self, att):
        if att == "issue_id":
            return self._get_jira_issue_id()
        elif att == "reviwer":
            return self.data["assignee"][0]["name"]
        elif att == "tester":
            return self.data["tester"][0]["name"]

        return self.data[att]


class Git(object):
    def __init__(self, path="."):
        self.path = path
        self.repo = Repo(self.path)
        self.origin = self.repo.remotes["origin"].url

    def info(self):
        p = giturlparse.parse(self.origin)
        if not p.valid:
            return None, None
        return p.owner, p.repo


def update_jira(pr):
    jira = JIRA(_jira_url, auth=(
        _conf["jira"]["user"], _conf["jira"]["passwd"]))
    comment = "PR %d Signed off by %s and %s.\n%s" % (
            pr.number, pr.reviwer, pr.tester, pr.url)
    jira.add_comment(pr.issue_id, comment)


def main(user, token, no):
    try:
        gitee = Gitee(user, token)
        pr = PR(gitee.get_pr(no))
    except GiteeError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 1

    if not pr.good():
        print("Invalid PR. Should be assigned to reviwer as well as tester.")
        print(pr.url)
        return 0
    elif pr.merged():
        print("Already merged. Nothing to do.")
        return 0

    try:
        gitee.merge(no)
        update_jira(pr)
    except GiteeError as e:
        pr.dump()
        print("\n\nFailed to merge PR: %s" % e, file=sys.stderr)
        return 2


def must_env(name):
    try:
        return os.environ[name]
    except KeyError:
        print("Missing environment variable: %s" % name)
        sys.exit(3)


def load_conf(name):
    global _conf
    # TODO: should validate config file
    # TODO: catch error
    with open(name) as f:
        _conf = toml.loads(f.read())


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print("Give me a PR number.")
        sys.exit(4)
    pr = sys.argv[1]
    load_conf("config.toml")
    sys.exit(main(_conf["gitee"]["user"], _conf["gitee"]["token"], pr))
