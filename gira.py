#!/usr/bin/env python

import giturlparse
import os
import sys
import json
import re
import urllib
import click
import subprocess
import requests
import toml
from git import Repo
from jira import JIRA


_conf = None


class GiteeError(Exception):
    pass


class Gitee(object):
    api_root = "https://gitee.com/api/v5/repos/{}/{}"
    web_root = "https://www.gitee.com/"
    allowed_permissions = ('push', 'pull', 'admin')

    def __init__(self, user, token):
        self.user = user
        self.token = token
        try:
            self.git = Git()
            self.owner, self.repo = self.git.info()
        except Exception:  # TODO: catch narrower exceptions
            raise GiteeError("You should run this from within a gitee repo")
        self._root = Gitee.api_root.format(self.owner, self.repo)

    def _url(self, urls, params):
        if params is not None:  # this is for GET
            params['access_token'] = self.token
            return os.path.join(self._root, *urls) + '?' + urllib.parse.urlencode(params)
        else:  # for PUT and POST
            return os.path.join(self._root, *urls)
        
    def _good_perm(self, perm):
        return perm in Gitee.allowed_permissions

    def get(self, url, params):
        return requests.get(self._url(url, params))

    def put(self, url, _data):
        d = {
            "access_token": self.token,
            "owner": self.owner,
            "repo": self.repo
        }
        d.update(_data)
        return requests.put(url, data=d)

    def delete(self, url):
        return requests.delete(url)

    def get_pr(self, pr):
        res = self.get(("pulls", pr), {})
        if not res.status_code == 200:
            raise GiteeError("RES %d" % res.status_code)
        return res.text

    def merge(self, pr):
        res = self.put(
            self._url(("pulls", pr, "merge"), None),
            { "number": pr }
        )
        if not res.status_code == 200:
            raise GiteeError(res.text)

    def lock_branch(self, branch):
        res = self.put(
            self._url(("branches", branch, "protection"), None),
            { "branch": branch }
        )
        if not res.status_code == 200:
            raise GiteeError(res.text)

    def add_user(self, username, permission='push'):
        if not self._good_perm(permission):
            raise ValueError("invalid permission: {permission}")
        res = self.put(
            self._url(("collaborators", username), None),
            { "permission": permission }
        )
        if not res.status_code == 200:
            raise GiteeError(res.text)

    def del_user(self, username):
        res = self.delete(self._url(("collaborators", username), {}))
        if not res.status_code == 200:
            raise GiteeError(res.text)


    def goto_web(self):
        url = os.path.join(Gitee.web_root, self.owner, self.repo)
        subprocess.run(["open", url])
        

class PR(object):
    def __init__(self, jsn):
        self.raw = jsn
        # TODO: handle exceptions
        self.data = json.loads(jsn)

    def good(self):
        try:
            _ =  self.issue_id  # make sure it's valid
        except ValueError:
            return False
        return len(self.data["assignees"]) >= 1 and \
               len(self.data["testers"]) >= 1

    def merged(self):
        return self.data["state"] == "merged"

    def dump(self):
        print(self.raw)

    def _get_jira_issue_id(self):
        pat = re.compile("^([A-Z]*-\d*)")
        mo = re.match(pat, self.title)
        if not mo:
            raise ValueError(f"Invalid PR title: {self.title}")
        return mo.group(1)

    def __getattr__(self, att):
        if att == "issue_id":
            return self._get_jira_issue_id()
        elif att == "reviwer":
            return self.data["assignees"][0]["name"]
        elif att == "tester":
            return self.data["testers"][0]["name"]

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
    jira = JIRA(_conf["jira"]["url"], auth=(
        _conf["jira"]["user"], _conf["jira"]["passwd"]))
    comment = "PR %d signed off by %s and %s.\n%s" % (
            pr.number, pr.reviwer, pr.tester, pr.html_url)
    issue = jira.issue(pr.issue_id)
    jira.add_comment(pr.issue_id, comment)
    jira.transition_issue(issue.key, '31')  # resolve



@click.group()
def main():
    pass


@main.command()
@click.argument('no')
def merge(no):
    user = _conf["gitee"]["user"]
    token = _conf["gitee"]["token"]
    try:
        gitee = Gitee(user, token)
        pr = PR(gitee.get_pr(no))
    except GiteeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not pr.good():
        print("Invalid PR. Possible causes are:")
        print("  1. PR not assigned to both reviwer and tester.")
        print("  2. PR title doesn't start with jira issue ID. e.g. CLOUD-1234")
        print(f"\n{pr.html_url}")
        return 0
    elif pr.merged():
        print("Already merged. Nothing to do.")
        return 0

    try:
        gitee.merge(no)
        update_jira(pr)
    except GiteeError as e:
        pr.dump()
        print(f"\n\nFailed to merge PR: {e}", file=sys.stderr)
        return 2


@main.command()
@click.argument('branch')
def lockbr(branch):
    user = _conf["gitee"]["user"]
    token = _conf["gitee"]["token"]
    try:
        gitee = Gitee(user, token)
        gitee.lock_branch(branch)
    except Exception as e:
        print(e)


@main.command()
@click.argument('user')
@click.argument('permission', default='push')
def adduser(user, permission):
    me = _conf["gitee"]["user"]
    token = _conf["gitee"]["token"]
    try:
        gitee = Gitee(me, token)
        gitee.add_user(user, permission)
    except Exception as e:
        print(e)


@main.command()
@click.argument('user')
def deluser(user):
    me = _conf["gitee"]["user"]
    token = _conf["gitee"]["token"]
    try:
        gitee = Gitee(me, token)
        gitee.del_user(user)
    except Exception as e:
        print(e)


@main.command()
def web():
    user = _conf["gitee"]["user"]
    token = _conf["gitee"]["token"]
    try:
        gitee = Gitee(user, token)
        gitee.goto_web()
    except Exception as e:
        print(e)


def load_conf(*names):
    global _conf
    # TODO: should validate config file
    # TODO: catch error
    for n in names:
        try:
            f = open(n)
            _conf = toml.loads(f.read())
            f.close()
        except IOError:
            continue


if __name__ == "__main__":
    load_conf(os.path.join(os.environ["HOME"], "gira.toml"),
            os.path.join(os.environ["HOME"], ".config/gira.toml"),
            "gira.toml")
    if _conf is None:
        print("Failed to load config file.")
        sys.exit(1)
    main()
