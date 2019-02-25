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

    '''get what to cherry pick from master latest commits,
    assuming that sandbox is pulled and have the latest code'''
    def get_head_parents(self, branch='master'):
        head = self.repo.heads[branch]
        return [p.hexsha for p in head.commit.parents]


class ReleaseVersion(object):
    def __init__(self, rel):
        self.release = rel
        self.is_semver = True
        self.major = ''
        self.minor = ''
        self.fix = ''
        self.project = ''
        self._parse_release(rel)

    def _parse_release(self, rel):
        pat = re.compile("^v(\d+)\.(\d+)\.(\d+)(-[a-zA-Z0-9]+)?$")
        mobj = re.match(pat, rel)
        if not mobj:
            self.is_semver = False
            return
        self.major = mobj.group(1)
        self.minor = mobj.group(2)
        self.fix = mobj.group(3)
        self.project = mobj.group(4) or ''
        if self.project:
            self.project = self.project[1:]

    def is_semver(self):
        return self.is_semver

    def __str__(self):
        return self.release


class MyJiraError(Exception):
    pass


class MyJira(object):
    def __init__(self, url, user, passwd):
        self.jira = JIRA(_conf["jira"]["url"], auth=(
            _conf["jira"]["user"], _conf["jira"]["passwd"]))

    def update_issue(self, issue_id, comment, transition):
        issue = self.jira.issue(issue_id)
        self.jira.add_comment(issue_id, comment)
        self.jira.transition_issue(issue.key, transition)

    def get_fix_versions(self, issue_id):
        issue = self.jira.issue(issue_id)
        return [fv.name for fv in issue.fields.fixVersions]

    def cherry_pick(self, issue_id, frm, to):
        'tries to automatically cherry-pick to the correct release branch'
        fv = self.get_fix_versions(issue_id)
        branches = []
        for f in fv:
            try:
                # e.g. v1.9.1
                major, minor, fix = f[1:].split('.')
            except ValueError as e:
                print(e)
                raise MyJiraError(f"Wrongly formatted release version: {f}")
            if fix == '0':  # this means trunk
                continue
            branches.append(f"release-{major}.{minor}")
        if not branches:
            return
        print("1. Run the following commands")
        print("2. Examine the result")
        print("3. If everything looks OK, PUSH!\n")
        print("git checkout master && git pull")
        for b in branches:
            print(f"# Updating release branch {b}...")
            print(f"git checkout {b}")
            print(f"git cherry-pick {frm}..{to}")

    def list_transitions(self, issue_id):
        jra = JIRA(_conf["jira"]["url"], auth=(
            _conf["jira"]["user"], _conf["jira"]["passwd"]))
        trs = jra.transitions(issue_id)
        for tr in trs:
            print(f"ID: {tr['id']}, Name: {tr['name']}")


@click.group()
def main():
    pass


@main.command()
@click.argument('no')
def merge(no):
    user = _conf["gitee"]["user"]
    token = _conf["gitee"]["token"]
    merged = False
    try:
        gitee = Gitee(user, token)
        pr = PR(gitee.get_pr(no))
        jira = MyJira(
            _conf["jira"]["url"],
            _conf["jira"]["user"],
            _conf["jira"]["passwd"])
    except GiteeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not pr.good():
        print("Invalid PR. Possible causes are:")
        print("  1. PR not assigned to both reviwer and tester.")
        print("  2. PR title doesn't start with jira issue ID. e.g. CLOUD-1234")
        print(f"\n{pr.html_url}")
        return 0

    try:
        if not pr.merged():
            gitee.merge(no)
        comment = "PR %d signed off by %s and %s.\n%s" % (
                pr.number, pr.reviwer, pr.tester, pr.html_url)
        jira.update_issue(pr.issue_id, comment, '31')  # 31 = resolve
        fv = jira.get_fix_versions(pr.issue_id)
        if fv:
            print(f"NOTE: fixVersions: {fv}")
        else:
            print("Issue has no fixVersion!!!")
    except GiteeError as e:
        pr.dump()
        print(f"\n\nFailed to merge PR: {e}", file=sys.stderr)
        return 2
    # TODO: catch JIRA exception

    # this has to be done to make sure that local clone has the latest commit
    gitee.git.repo.git.checkout("master")
    gitee.git.repo.git.pull()
    try:
        frm, to = gitee.git.get_head_parents()
    except ValueError:
        print("Something wrong with HEAD. It's not a merge commit.")
        return 3
    jira.cherry_pick(pr.issue_id, frm, to)


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


@main.command()
def runtests():
    _test_git()
    _test_jira()
    _test_release()


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


def _test_jira():
    jra = MyJira(_conf["jira"]["url"],
        _conf["jira"]["user"], _conf["jira"]["passwd"])
    fv = jra.get_fix_versions('CLOUD-4870')
    print(fv)
    jra.list_transitions('TEST-4')

def _test_git():
    git = Git()
    picks = git.get_head_parents()
    if len(picks) != 2:
        print("Something is wrong, the HEAD is not a merge commit!")
    print(picks)
    git.repo.git.checkout("master")
    git.repo.git.pull()


def _test_release():
    releases = {
        'Infinity': ('', '', '', ''),
        'v1': ('', '', '', ''),
        'v1.3': ('', '', '', ''),
        'v1.3.3a': ('', '', '', ''),
        'v1.3.3': ('1', '3', '3', ''),
        'v1.3.3-foobar': ('1', '3', '3', 'foobar')
    }
    for rel in releases:
        r = ReleaseVersion(rel)
        exp = releases[rel]
        if r.major == exp[0] and \
                r.minor == exp[1] and \
                r.fix == exp[2] and \
                r.project == exp[3]:
            print("OK")
        else:
            print(f"NOK {rel}")
            print(f"{r.major}.{r.minor}.{r.fix}-{r.project}")


if __name__ == "__main__":
    load_conf(os.path.join(os.environ["HOME"], "gira.toml"),
            os.path.join(os.environ["HOME"], ".config/gira.toml"),
            "gira.toml")
    if _conf is None:
        print("Failed to load config file.")
        sys.exit(1)
    main()
