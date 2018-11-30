#!/usr/bin/env python

import os
import sys
import json
import urllib
import requests
import giturlparse
from git import Repo


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
        return self.data["assignee"] and self.data["tester"]

    def merged(self):
        return self.data["state"] == "merged"

    def dump(self):
        print(self.raw)

    def __getattr__(self, att):
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


def main(user, token, no):
    try:
        gitee = Gitee(user, token)
        pr = PR(gitee.get_pr(no))
        if not pr.good():
            print("Invalid PR. Should be assigned to reviwer as well as tester.")
            print(pr.url)
            return 0
        elif pr.merged():
            print("Already merged. Nothing to do.")
            return 0
    except GiteeError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 1

    try:
        gitee.merge(no)
    except GiteeError as e:
        pr.dump()
        print("\n\nFailed to merge PR: %s" % e, file=sys.stderr)
        sys.exit(2)


def must_env(name):
    try:
        return os.environ[name]
    except KeyError:
        print("Missing environment variable: %s" % name)
        sys.exit(3)

if __name__ == "__main__":
    if len(sys.argv) == 1:
        print("Give me a PR number.")
        sys.exit(4)
    pr = sys.argv[1]
    sys.exit(main(must_env("GITEE_USER"), must_env("GITEE_TOKEN"), pr))
