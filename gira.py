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
from retrying import retry
from git import Repo
from git.exc import GitCommandError
import git
from jira import JIRA


_conf = None

# JIRA ISSUE TRANSITION LIST
# ID: 51, Name: Reopen, this seems wrong
# ID: 11, Name: Open
# ID: 21, Name: In Progress
# ID: 31, Name: Resolved
# ID: 41, Name: Reopened
# ID: 51, Name: Closed
# ID: 61, Name: testing
# ID: 71, Name: Analyse
# ID: 81, Name: Ready For Test
# ID: 101, Name: 已部署
# ID: 121, Name: Ready For Dev
# ID: 131, Name: Blocked


class GiteeError(Exception):
    pass


class Gitee(object):
    api_root = "https://gitee.com/api/v5/repos/{}/{}"
    web_root = "https://www.gitee.com/"
    allowed_permissions = ("push", "pull", "admin")

    def __init__(self, user, token):
        self.user = user
        self.token = token
        search = [".", "..", "../..", "/you-will-never-find-me///"]
        for s in search:
            try:
                self.git = Git(os.path.abspath(s))
                self.owner, self.repo = self.git.info()
                break
            except git.exc.NoSuchPathError:
                raise GiteeError("You should run this from within a gitee repo")
            except git.exc.InvalidGitRepositoryError:
                pass # continue
        self._root = Gitee.api_root.format(self.owner, self.repo)

    def _url(self, urls, params):
        if params is not None:  # this is for GET
            params["access_token"] = self.token
            return (
                os.path.join(self._root, *urls) + "?" + urllib.parse.urlencode(params)
            )
        else:  # for PUT and POST
            return os.path.join(self._root, *urls)

    def _good_perm(self, perm):
        return perm in Gitee.allowed_permissions

    def get(self, url, params):
        return requests.get(self._url(url, params))

    def put(self, url, _data):
        d = {"access_token": self.token, "owner": self.owner, "repo": self.repo}
        d.update(_data)
        return requests.put(url, data=d)

    def delete(self, url):
        return requests.delete(url)

    def get_pr(self, pr):
        res = self.get(("pulls", pr), {})
        if not res.status_code == 200:
            raise GiteeError("RES %d" % res.status_code)
        return res.text

    def get_branch(self, br):
        res = self.get(("branches", br), {})
        if not res.status_code == 200:
            raise GiteeError(res.text)
        return res

    def merge(self, pr):
        res = self.put(self._url(("pulls", pr, "merge"), None), {"number": pr})
        if not res.status_code == 200:
            raise GiteeError(res.text)

    def lock_branch(self, branch):
        res = self.put(
            self._url(("branches", branch, "protection"), None), {"branch": branch}
        )
        if not res.status_code == 200:
            raise GiteeError(res.text)

    def list_branch(self):
        res = self.get(("branches",), {})
        if not res.status_code == 200:
            raise GiteeError(res.text)
        return res

    def list_member(self):
        res = self.get(("collaborators",), {})
        if not res.status_code == 200:
            raise GiteeError(res.text)
        return res

    def list_prs(self):
        res = self.get(("pulls",), {})
        if not res.status_code == 200:
            raise GiteeError(res.text)
        return res

    def add_user(self, username, permission="push"):
        if not self._good_perm(permission):
            raise ValueError("invalid permission: {permission}")
        res = self.put(
            self._url(("collaborators", username), None), {"permission": permission}
        )
        if not res.status_code == 200:
            raise GiteeError(res.text)

    def del_user(self, username):
        res = self.delete(self._url(("collaborators", username), {}))
        if not res.status_code == 200:
            raise GiteeError(res.text)

    def print_user(self, u):
        adm = "\tadmin" if u["permissions"]["admin"] else ""
        print(f"{u['name']} ({u['login']}){adm}")

    def print_branch(self, br):
        prot = ", protected" if br["protected"] else ""
        print(f"{br['name']}{prot}")

    def print_prs(self, pr):
        print(f"{pr['number']}: {pr['title']}")

    def goto_web(self):
        url = os.path.join(Gitee.web_root, self.owner, self.repo)
        subprocess.run(["open", url])

    def goto_pull(self, id):
        url = os.path.join(Gitee.web_root, self.owner, self.repo, "pulls", id)
        subprocess.run(["open", url])


class PR(object):
    def __init__(self, jsn):
        self.raw = jsn
        # TODO: handle exceptions
        self.data = json.loads(jsn)

    def good(self):
        try:
            _ = self.issue_id  # make sure it's valid
        except ValueError:
            return False
        return len(self.data["assignees"]) >= 1 and len(self.data["testers"]) >= 1

    def merged(self):
        return self.data["state"] == "merged"

    def dump(self):
        print(self.raw)

    def _get_jira_issue_id(self):
        pat = re.compile("^\s*([A-Z]*-\d*)\s+")
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

    """get what to cherry pick from master latest commits,
    assuming that sandbox is pulled and have the latest code"""

    def get_head_parents(self, branch="master"):
        head = self.repo.heads[branch]
        return [p.hexsha for p in head.commit.parents]


class ReleaseVersion(object):
    def __init__(self, rel):
        self.release = rel
        self.is_semver = True
        self.major = ""
        self.minor = ""
        self.fix = ""
        self.project = ""
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
        self.project = mobj.group(4) or ""
        if self.project:
            self.project = self.project[1:]

    def __str__(self):
        return self.release


class MyJiraError(Exception):
    pass


class MyJira(object):
    def __init__(self, url, user, passwd):
        self.jira = JIRA(
            _conf["jira"]["url"], auth=(_conf["jira"]["user"], _conf["jira"]["passwd"])
        )

    def update_issue(self, issue_id, comment, transition):
        issue = self.jira.issue(issue_id)
        self.jira.add_comment(issue_id, comment)
        self.jira.transition_issue(issue.key, transition)

    def start_on_issue(self, issue_id, component, transition):
        issue = self.jira.issue(issue_id)
        issue.update(fields={"components": [{ "name": component }]})
        self.jira.transition_issue(issue.key, transition)

    def get_fix_versions(self, issue_id):
        issue = self.jira.issue(issue_id)
        return [fv.name for fv in issue.fields.fixVersions]

    def get_issue_status(self, issue_id):
        issue = self.jira.issue(issue_id)
        return issue.fields.status.name

    def trunk_required(self, issue_id):
        fv = self.get_fix_versions(issue_id)
        for f in fv:
            rv = ReleaseVersion(f)
            if rv.fix == "0":  # '0' means trunk
                return True
        return False

    def get_cherry_pick_branches(self, issue_id, frm, to):
        fv = self.get_fix_versions(issue_id)
        branches = []
        for f in fv:
            rv = ReleaseVersion(f)
            if not rv.is_semver or rv.fix == "0":  # '0' means trunk
                print(f"fixVersions {rv} ignored")
                continue
            rel = f"release-{rv.major}.{rv.minor}"
            if rv.project:
                rel += f"-{rv.project}"
            branches.append(rel)
        return branches

    def list_transitions(self, issue_id):
        jra = JIRA(
            _conf["jira"]["url"], auth=(_conf["jira"]["user"], _conf["jira"]["passwd"])
        )
        trs = jra.transitions(issue_id)
        for tr in trs:
            print(f"ID: {tr['id']}, Name: {tr['name']}")

    def _get_field(self, issue_id, field):
        isu = self.jira.issue(issue_id)
        return getattr(isu.fields, field)

    def get_summary(self, issue_id):
        return self._get_field(issue_id, "summary")

    def get_assignee(self, issue_id):
        assignee = self._get_field(issue_id, "assignee")
        return assignee.name if assignee is not None else ""

    def push_off(self, issue_id, frm, to):
        issue = self.jira.issue(issue_id)
        newfv = []
        for fv in issue.fields.fixVersions:
            if fv.name == frm:
                newfv.append({"name": to})
            else:
                newfv.append({"name": fv.name})
        issue.update(fields={"fixVersions": newfv})

    def has_children(self, issue_id):
        issue = self.jira.issue(issue_id)
        return len(issue.fields.subtasks) > 0


@click.group()
def main():
    pass


def _good_jira_issue(jira, issue_id, force=False):
    st = jira.get_issue_status(issue_id)
    if st == "Resolved" or st == "Closed":
        print("Jira issue {0} already Resolved or Closed. Giving up.".format(issue_id))
        return False
    vers = jira.get_fix_versions(issue_id)
    if len(vers) == 0:
        print("Invalid Jira issue: no fixVersion")
        return False
    if jira.has_children(issue_id):
        print("Refusing to merge issue with subtask")
        return False

    # fixVersion can be:
    # 1. x.y.0 for trunk
    # 2. x.y.z for product bug fix
    # 3. x.y.z-proj for project bug fix
    trunk = bug_fix = proj_fix = 0
    for v in vers:
        rel = ReleaseVersion(v)
        if not rel.is_semver:
            print(f"{rel} is not semver. Skipped.")
            continue
        if rel.fix == "0":  # 1
            trunk += 1
        elif rel.project:  # 3
            proj_fix += 1
        else:  # has to be 2
            bug_fix += 1

    if trunk > 1:
        print("Jira issue assigned assigned to multiple major version. Giving up.")
        return False
    if not trunk and bug_fix:
        print("Bug fixes has to go to master. Giving up.")
        return False
    if not trunk and proj_fix and not force:
        print("Bug fixes has to go to master. Giving up.")
        return False
    return True


def all_is_well(gitee, pr, jira, force):
    if not pr.good():
        print("Invalid PR. Possible causes are:")
        print("  1. PR not assigned to both reviwer and tester.")
        print("  2. PR title doesn't start with jira issue ID. e.g. CLOUD-1234")
        print("  3. PR title doesn't have summary.")
        print(f"\n{pr.html_url}")
        return False

    return _good_jira_issue(jira, pr.issue_id, force)


def cherry_pick_real(git, branches, frm, to):
    print(f"===> Cherry picking to branches: {branches}...")
    git.checkout("master")
    git.pull()
    for br in branches:
        print(f"switching to {br}...")
        git.checkout(br)
        print(f"pulling from remote repo...")
        git.pull()
        print(f"cherry picking {frm}..{to}...")
        git.cherry_pick(f"{frm}..{to}")
        print(f"pushing to remote repo...")
        git.push()
        print(f"switching to master...")
        git.checkout("master")


def cherry_pick(git, branches, frm, to, doit=True):
    """tries to automatically cherry-pick to the correct release branch from
    master"""
    if not branches:
        return
    if doit:
        cherry_pick_real(git, branches, frm, to)
        return
    print()
    print("1. Run the following commands")
    print("2. Examine the result")
    print("3. If everything looks OK, PUSH!\n")
    print("git checkout master && git pull")
    for b in branches:
        print(f"# Updating release branch {b}...")
        print(f"git checkout {b} && git pull")
        print(f"git cherry-pick {frm}..{to}")



@main.command()
@click.option(
    "--force/--no-force",
    default=False,
    help="Force merging of PR. Useful for project specific changes.",
)
@click.option(
    "--autocp/--no-autocp",
    default=True,
    help="Automatically cherry pick to various release branches",
)
@click.argument("no")
def merge(no, force, autocp):
    user = _conf["gitee"]["user"]
    token = _conf["gitee"]["token"]
    try:
        print(f"===> Making connection to gitee.com...")
        gitee = Gitee(user, token)
        if gitee.git.repo.is_dirty():
            print("Working directory seems to be dirty. Refusing to continue.")
            return 1
        pr = PR(gitee.get_pr(no))
        print(f"===> Making connection to jira server...")
        jira = MyJira(
            _conf["jira"]["url"], _conf["jira"]["user"], _conf["jira"]["passwd"]
        )
        print(f"===> Merging PR for: {pr.issue_id} {jira.get_summary(pr.issue_id)}")
    except GiteeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not all_is_well(gitee, pr, jira, force):
        return 0

    if pr.head == "master" and force:
        print("'force' only allowed for project specific bug fixes. Giving up.")
        return 4

    # used to be pr.head but there seems to be problem with gitee API
    if pr.base['label'] != "master" and jira.trunk_required(pr.issue_id):
        print("Jira fix version includes trunk but only merging to branch.")
        print("Perhaps you should split the Jira issue. Giving up.")
        print(f"\n\n\nbase: {pr.base}, issue: {pr.issue_id}")
        return 5

    try:
        if not pr.merged():
            print(f"===> Merging PR {no}...")
            gitee.merge(no)
        comment = "PR %d signed off by %s and %s.\n%s" % (
            pr.number,
            pr.reviwer,
            pr.tester,
            pr.html_url,
        )
        print(f"===> Updating jira issue status...")
        jira.update_issue(pr.issue_id, comment, "31")  # 31 = resolve
        fv = jira.get_fix_versions(pr.issue_id)
        if fv:
            print(f"fixVersions: {', '.join(fv)}")
        else:
            print("Issue has no fixVersion!!!")
    except GiteeError as e:
        pr.dump()
        print(f"\n\nFailed to merge PR: {e}", file=sys.stderr)
        return 2
    # TODO: catch JIRA exception

    if force:  # FIXME: this is leaky but let's assume it's OK
        return

    # this has to be done to make sure that local clone has the latest commit
    try:
        print(f"===> Updating to latest master...")
        gitee.git.repo.git.checkout("master")
        gitee.git.repo.git.pull()
    except git.exc.GitCommandError as e:
        print(e)
        print("Unable to switch to master. Perhaps you have an dirty sandbox.")
        return 11

    try:
        frm, to = gitee.git.get_head_parents()
    except ValueError:
        print("Something wrong with HEAD. It's not a merge commit.")
        return 3
    branches = jira.get_cherry_pick_branches(pr.issue_id, frm, to)
    try:
        cherry_pick(gitee.git.repo.git, branches, frm, to, autocp)
    except git.exc.GitCommandError as e:
        print(e)
        print("===> Something went wrong. Re-opending jira issue")
        jira.update_issue(pr.issue_id, "Cherry picking failed", "41")  # 41 = reopen


@main.command()
@click.argument("branch")
def lockbr(branch):
    user = _conf["gitee"]["user"]
    token = _conf["gitee"]["token"]
    try:
        gitee = Gitee(user, token)
        gitee.lock_branch(branch)
    except Exception as e:
        print(e)


def show_branches(full):
    user = _conf["gitee"]["user"]
    token = _conf["gitee"]["token"]
    try:
        gitee = Gitee(user, token)
        res = gitee.list_branch()
        if full:
            print(res.text)
            return
        for br in json.loads(res.text):
            gitee.print_branch(br)
    except Exception as e:
        print(e)


def show_team(full):
    user = _conf["gitee"]["user"]
    token = _conf["gitee"]["token"]
    try:
        gitee = Gitee(user, token)
        res = gitee.list_member()
        if full:
            print(res.text)
            return
        for u in json.loads(res.text):
            gitee.print_user(u)
    except Exception as e:
        print(e)


def show_prs(full):
    user = _conf["gitee"]["user"]
    token = _conf["gitee"]["token"]
    try:
        gitee = Gitee(user, token)
        res = gitee.list_prs()
        if full:
            print(res.text)
            return
        for pr in json.loads(res.text):
            gitee.print_prs(pr)
    except Exception as e:
        print(e)


@main.command()
@click.option(
    "--full/--no-full",
    default=False,
    help="Display full JSON. what can be <branch, team, pr>",
)
@click.argument("what")
def show(full, what):
    if what == "branch":
        show_branches(full)
    elif what == "team":
        show_team(full)
    elif what == "pr":
        show_prs(full)


@main.command()
@click.argument("user")
@click.argument("permission", default="push")
def adduser(user, permission):
    me = _conf["gitee"]["user"]
    token = _conf["gitee"]["token"]
    try:
        gitee = Gitee(me, token)
        gitee.add_user(user, permission)
    except Exception as e:
        print(e)


@main.command()
@click.argument("user")
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
@click.argument("no")
def review(no):
    user = _conf["gitee"]["user"]
    token = _conf["gitee"]["token"]
    try:
        gitee = Gitee(user, token)
        pr = PR(gitee.get_pr(no))
        jira = MyJira(
            _conf["jira"]["url"], _conf["jira"]["user"], _conf["jira"]["passwd"]
        )
    except GiteeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"===> Reviewing PR for: {pr.issue_id} {jira.get_summary(pr.issue_id)}")
    gitee.goto_pull(no)
    gitee.git.repo.git.checkout("master")
    gitee.git.repo.git.pull()
    print(f"===> Switching to branch:\t{pr.issue_id}")
    gitee.git.repo.git.checkout(pr.issue_id)
    gitee.git.repo.git.pull()
    print(f"===> Trying to run unit tests...")
    if os.system("make test") != 0:
        print(f"===> ❌ Unit tests failed!!!")
    print(f"===> Trying to build image...")
    if os.system("make docker") != 0:
        print(f"===> ❌ Building docker image failed!!!")


@main.command()
@click.argument("issue_no")
def start(issue_no):
    root = subprocess.check_output(
            ['git', 'rev-parse', '--show-toplevel']).strip()
    pwd = subprocess.check_output(
            ['git', 'rev-parse', '--show-prefix']).strip()
    comp = os.path.join(os.path.basename(root), pwd).decode("utf-8").strip("/")
    user = _conf["gitee"]["user"]
    token = _conf["gitee"]["token"]
    try:
        gitee = Gitee(user, token)
        jira = MyJira(
            _conf["jira"]["url"], _conf["jira"]["user"], _conf["jira"]["passwd"]
        )
    except MyJiraError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    def issue_ready_to_start():
        return jira.get_assignee(issue_no) and len(jira.get_fix_versions(issue_no))

    @retry(stop_max_attempt_number=50, wait_fixed=2000)
    def branch_ready():
        try:
            gitee.get_branch(issue_no)
            return True
        except GiteeError as e:
            raise e

    if not issue_ready_to_start():
        print("Issue has no fix versions or not assigned to someone. Aborting...")
        return False

    # wait for webhook to create remote branch
    jira.start_on_issue(issue_no, comp, '21')
    if not branch_ready():
        print("Something went wrong with jira webhook. Aborting...")
        return

    # checkout to new branch
    gitee.git.repo.git.checkout("master")
    gitee.git.repo.git.pull()
    gitee.git.repo.git.checkout(issue_no)
    print("You're all set. 请开始你的表演．．．")


@main.command()
@click.argument("frm")
@click.argument("to")
@click.argument("issue_no")
def pushoff(issue_no, frm, to):
    try:
        jira = MyJira(
            _conf["jira"]["url"], _conf["jira"]["user"], _conf["jira"]["passwd"]
        )
        jira.push_off(issue_no, frm, to)
    except MyJiraError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


@main.command()
def runtests():
    _test_git()
    _test_jira()
    _test_release()
    _test_gitee()


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


# {{{ Test code
def _test_jira():
    print("===> Testing jira...")
    jra = MyJira(_conf["jira"]["url"], _conf["jira"]["user"], _conf["jira"]["passwd"])
    fv = jra.get_fix_versions("CLOUD-4870")
    print(fv)
    if jra.get_summary("CLOUD-4870") != "160部署程序缺少docker load":
        print("XXX: wrong issue title")
    jra.list_transitions("TEST-4")
    jra.list_transitions("CLOUD-4414")
    st = jra.get_issue_status("CLOUD-4414")
    if st != "Closed":
        print("XXX: Wrong issue status")
    if _good_jira_issue(jra, "TEST-4"):  # No fix version
        print("XXX: Should have no fixVersion")
    if not _good_jira_issue(jra, "CLOUD-5447"):  # good fix version
        print("XXX: Should be good")
    if _good_jira_issue(jra, "CLOUD-5446"):
        print("XXX: Should not have more than one master")
    if _good_jira_issue(jra, "CLOUD-5448"):  # no trunk
        print("XXX: Should have a master release")
    if _good_jira_issue(jra, "CLOUD-5448", force=True):  # no trunk
        print("XXX: Should have a master release")
    if _good_jira_issue(jra, "CLOUD-5449"):  # project only
        print("XXX: Should have a master release")
    if not _good_jira_issue(jra, "CLOUD-5449", force=True):  # project only
        print("XXX: Should allow force merge of project only PR")
    if not _good_jira_issue(jra, "CLOUD-5450"):  # non-semver
        print("XXX: Should allow non-semver fixVersion")
    if not jra.trunk_required("CLOUD-5450"):
        print("XXX: issue requires trunk")
    if not jra.has_children("CLOUD-7356"):
        print("XXX: expected parent task")
    if jra.has_children("CLOUD-7357"):
        print("XXX: expected no children task")


def _test_git():
    print("===> Testing git...")
    git = Git()
    picks = git.get_head_parents()
    if len(picks) != 2:
        print("Something is wrong, the HEAD is not a merge commit!")
    print(picks)
    git.repo.git.checkout("master")
    git.repo.git.pull()


def _test_gitee():
    print("===> Testing gitee...")
    user = _conf["gitee"]["user"]
    token = _conf["gitee"]["token"]
    gitee = Gitee(user, token)
    pr = PR(gitee.get_pr("25"))
    if pr.issue_id != "TEST-4":
        print("XXX: Should allow non-semver fixVersion")


def _test_release():
    print("===> Testing release...")
    releases = {
        "Infinity": ("", "", "", "", False),
        "v1": ("", "", "", "", False),
        "v1.3": ("", "", "", "", False),
        "v1.3.3a": ("", "", "", "", False),
        "v1.3.3": ("1", "3", "3", "", True),
        "v1.3.3-foobar": ("1", "3", "3", "foobar", True),
    }
    for rel in releases:
        r = ReleaseVersion(rel)
        exp = releases[rel]
        if (
            r.major == exp[0]
            and r.minor == exp[1]
            and r.fix == exp[2]
            and r.project == exp[3]
            and r.is_semver == exp[4]
        ):
            print("OK")
        else:
            print(f"NOK {rel}")
            print(f"{r.major}.{r.minor}.{r.fix}-{r.project}")
# }}}


if __name__ == "__main__":
    load_conf(
        os.path.join(os.environ["HOME"], "gira.toml"),
        os.path.join(os.environ["HOME"], ".config/gira.toml"),
        "gira.toml",
    )
    if _conf is None:
        print("Failed to load config file.")
        sys.exit(1)
    main()
