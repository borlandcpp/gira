#!/usr/bin/env python

import requests
import urllib
import os
from git import Repo
from pprint import pprint
import giturlparse



class Gitee(object):
    def __init__(self, user, token):
        self.user = user
        self.token = token
        self.git = Git()
        self._root = "https://gitee.com/api/v5/repos/%s/%s" % (
            self.git.info()
        )

    def _url(self, urls, params):
        params['access_token'] = self.token
        return os.path.join(self._root, *urls) + '?' + urllib.parse.urlencode(params)

    def get(self, url, params):
        return requests.get(self._url(url, params))


class Git(object):
    def __init__(self, path="."):
        self.path = path
        self.repo = Repo(self.path)  # causes exception
        self.origin = self.repo.remotes["origin"].url

    def info(self):
        p = giturlparse.parse(self.origin)
        if not p.valid:
            return None, None
        return p.owner, p.repo


gitee = Gitee("borlandc", "efc230e91b187fdf8021018fc76a575c")
pr = gitee.get(("pulls", "1"), {})
print(pr.text)