"""Jira provider (Cloud REST v3 and Server / Data Center REST v2).

Config lives under `tracker:` in relay.yaml. Only `url` and credentials are
required. Everything else has a sensible default. See templates/relay.yaml.
"""

import base64

from relaylib import mdconv
from relaylib.http import build_url, request_json
from relaylib.provider_base import Provider, ProviderError
from relaylib.schema import normalize

BASE_FIELDS = ["summary", "issuetype", "status", "priority", "assignee", "reporter", "labels",
               "components", "fixVersions", "parent", "created", "updated", "description",
               "subtasks", "issuelinks", "attachment", "comment"]

DEFAULT_FIELD_NAMES = {
    "acceptance_criteria": ["Acceptance Criteria", "Acceptance criteria", "AC"],
    "story_points": ["Story Points", "Story point estimate", "Story points"],
}


def create(tracker_cfg):
    return JiraProvider(tracker_cfg)


class JiraProvider(Provider):
    name = "jira"

    def __init__(self, tracker_cfg):
        super().__init__(tracker_cfg)
        cfg = self.cfg
        self.base = str(cfg.get("url") or "").rstrip("/")
        opts = cfg.get("jira") or {}
        self.opts = opts
        deployment = str(opts.get("deployment") or cfg.get("deployment") or "").lower()
        if not deployment:
            deployment = "cloud" if ".atlassian.net" in self.base or not self.base else "server"
        self.cloud = deployment == "cloud"
        self.api = "/rest/api/3" if self.cloud else "/rest/api/2"
        self.page_size = int(opts.get("page_size") or 100)
        self.include_comments = opts.get("include_comments", False) is True
        self.max_comments = int(opts.get("max_comments") or 50)
        self.field_cfg = opts.get("fields") or {}
        self.extra_fields = list(opts.get("extra_fields") or [])
        self.children_jql = opts.get("epic_children_jql") or (
            "parent = {epic} AND issuetype not in subTaskIssueTypes() ORDER BY rank"
            if self.cloud else
            '"Epic Link" = {epic} AND issuetype not in subTaskIssueTypes() ORDER BY rank')
        self._fields_by_id = None
        self._names = {}  # from raw payloads with expand=names

    # ------------------------------------------------------------------ http

    def _headers(self):
        email = self.cfg.get("email") or self.cfg.get("user")
        token = self.cfg.get("token")
        auth = str(self.cfg.get("auth") or ("basic" if email else "bearer")).lower()
        if not token:
            raise ProviderError("No Jira token. Set RELAY_TRACKER_TOKEN (and RELAY_TRACKER_EMAIL for Jira Cloud).")
        if auth == "basic":
            if not email:
                raise ProviderError("Basic auth needs an email. Set RELAY_TRACKER_EMAIL.")
            raw = ("%s:%s" % (email, token)).encode("utf-8")
            return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}
        return {"Authorization": "Bearer " + token}

    def _explain(self, status, url):
        if status == 401:
            return "Jira rejected the credentials. Check RELAY_TRACKER_EMAIL and RELAY_TRACKER_TOKEN."
        if status == 403:
            return "Your Jira user cannot see this. Ask for Browse Projects permission."
        if status == 404:
            return "Not found, or your user has no access to it."
        if status == 410:
            return "This Jira endpoint was removed. Check tracker.jira.deployment in relay.yaml."
        return ""

    def _call(self, method, path, params=None, body=None):
        if not self.base:
            raise ProviderError("No Jira URL. Set RELAY_TRACKER_URL (for example https://yourcompany.atlassian.net).")
        url = build_url(self.base, self.api + path, params)
        return request_json(method, url, headers=self._headers(), body=body, explain=self._explain)

    # ------------------------------------------------------------------ fields

    def _field_index(self):
        if self._fields_by_id is None:
            try:
                data = self._call("GET", "/field") or []
                self._fields_by_id = {f["id"]: f.get("name") or f["id"] for f in data if f.get("id")}
            except ProviderError as e:
                self.warn("Could not read the Jira field list (%s). Custom fields need ids like customfield_10035." % e)
                self._fields_by_id = {}
        return self._fields_by_id

    def _resolve(self, wanted, known=None):
        """Map a field name or id to an id. Returns None when not found."""
        if not wanted:
            return None
        known = known if known is not None else self._field_index()
        if isinstance(wanted, (list, tuple)):
            for w in wanted:
                fid = self._resolve(w, known)
                if fid:
                    return fid
            return None
        wanted = str(wanted)
        if wanted.startswith("customfield_") or wanted in known:
            return wanted
        low = wanted.lower()
        for fid, name in known.items():
            if (name or "").lower() == low:
                return fid
        return None

    def _custom_ids(self, known=None):
        ids = {}
        for key, defaults in DEFAULT_FIELD_NAMES.items():
            configured = self.field_cfg.get(key)
            fid = self._resolve(configured or defaults, known)
            if configured and not fid:
                self.warn("Field '%s' (%s) was not found in Jira." % (configured, key))
            ids[key] = fid
        if not self.cloud:
            ids["epic_link"] = self._resolve(self.field_cfg.get("epic_link") or "Epic Link", known)
        extras = {}
        for name in self.extra_fields:
            fid = self._resolve(name, known)
            if fid:
                extras[name] = fid
            else:
                self.warn("Extra field '%s' was not found in Jira." % name)
        ids["extra"] = extras
        return ids

    def _fields_param(self):
        ids = self._custom_ids()
        fields = list(BASE_FIELDS)
        for key in ("acceptance_criteria", "story_points", "epic_link"):
            if ids.get(key):
                fields.append(ids[key])
        fields.extend(ids["extra"].values())
        if not self.include_comments:
            fields.remove("comment")
        return fields, ids

    # ------------------------------------------------------------------ api

    def ping(self):
        me = self._call("GET", "/myself") or {}
        return "%s (%s, Jira %s)" % (me.get("displayName") or me.get("name") or "unknown user",
                                     self.base, "Cloud" if self.cloud else "Server/DC")

    def get_issue(self, key):
        fields, ids = self._fields_param()
        raw = self._call("GET", "/issue/%s" % key, params={"fields": ",".join(fields)})
        return self._normalize(raw, ids)

    def get_epic_children(self, epic_key):
        fields, ids = self._fields_param()
        jql = self.children_jql.replace("{epic}", epic_key)
        return [self._normalize(raw, ids) for raw in self._search(jql, fields)]

    def _search(self, jql, fields):
        issues = []
        if self.cloud:
            token = None
            while True:
                body = {"jql": jql, "fields": fields, "maxResults": self.page_size}
                if token:
                    body["nextPageToken"] = token
                page = self._call("POST", "/search/jql", body=body) or {}
                issues.extend(page.get("issues") or [])
                token = page.get("nextPageToken")
                if page.get("isLast", True) or not token:
                    break
        else:
            start = 0
            while True:
                page = self._call("POST", "/search", body={
                    "jql": jql, "fields": fields, "startAt": start, "maxResults": self.page_size}) or {}
                batch = page.get("issues") or []
                issues.extend(batch)
                start += len(batch)
                if not batch or start >= int(page.get("total") or 0):
                    break
        return issues

    def _comments(self, key, field_value):
        field_value = field_value or {}
        comments = field_value.get("comments") or []
        total = int(field_value.get("total") or len(comments))
        if total > len(comments) and len(comments) < self.max_comments:
            try:
                page = self._call("GET", "/issue/%s/comment" % key,
                                  params={"maxResults": self.max_comments, "orderBy": "created"}) or {}
                comments = page.get("comments") or comments
            except ProviderError as e:
                self.warn("Could not read all comments of %s (%s)." % (key, e))
        return comments[-self.max_comments:]

    # ------------------------------------------------------------------ normalize

    def normalize_raw(self, raw_issue):
        """For MCP mode: raw is a Jira issue JSON as the REST API returns it.
        Field names come from raw['names'] (expand=names) when present."""
        names = raw_issue.get("names") or {}
        self._names.update(names)
        known = dict(self._names)
        ids = self._custom_ids(known) if known else self._custom_ids({})
        return self._normalize(raw_issue, ids, fetch_more=False)

    def _rich(self, value):
        if value is None:
            return ""
        if isinstance(value, dict) and value.get("type") == "doc":
            return mdconv.adf_to_md(value)
        if isinstance(value, str):
            return value.strip() if self.cloud else mdconv.wiki_to_md(value)
        return self._value(value)

    def _value(self, v):
        if v is None:
            return None
        if isinstance(v, dict):
            if v.get("type") == "doc":
                return mdconv.adf_to_md(v)
            for key in ("value", "name", "displayName", "key"):
                if v.get(key) is not None:
                    child = v.get("child")
                    base = str(v[key])
                    return base + (" / " + self._value(child) if isinstance(child, dict) else "")
            return None
        if isinstance(v, list):
            vals = [self._value(x) for x in v]
            return ", ".join(str(x) for x in vals if x not in (None, ""))
        if isinstance(v, str):
            return v.strip() if self.cloud else mdconv.wiki_to_md(v)
        return v

    def _normalize(self, raw, ids, fetch_more=True):
        if not raw or not raw.get("key"):
            raise ProviderError("Jira returned an issue without a key.")
        key = raw["key"]
        f = raw.get("fields") or {}

        def name(obj, attr="name"):
            return obj.get(attr) if isinstance(obj, dict) else None

        parent = (f.get("parent") or {}).get("key")
        if not parent and ids.get("epic_link"):
            parent = f.get(ids["epic_link"])

        links = []
        for link in f.get("issuelinks") or []:
            kind = link.get("type") or {}
            other = link.get("outwardIssue") or link.get("inwardIssue") or {}
            relation = kind.get("outward") if link.get("outwardIssue") else kind.get("inward")
            ofields = other.get("fields") or {}
            links.append({"relation": relation or kind.get("name") or "relates to", "id": other.get("key"),
                          "title": ofields.get("summary"), "status": name(ofields.get("status"))})

        comment_field = f.get("comment") if self.include_comments else None
        raw_comments = self._comments(key, comment_field) if (fetch_more and comment_field) else \
            ((comment_field or {}).get("comments") or [])
        comments = [{"author": name(c.get("author"), "displayName") or name(c.get("author")),
                     "created": c.get("created"), "body": self._rich(c.get("body"))} for c in raw_comments]

        ac_raw = f.get(ids["acceptance_criteria"]) if ids.get("acceptance_criteria") else None
        points = f.get(ids["story_points"]) if ids.get("story_points") else None
        if isinstance(points, float) and points.is_integer():
            points = int(points)

        extra = {}
        for label, fid in (ids.get("extra") or {}).items():
            value = f.get(fid)
            extra[label] = self._rich(value) if isinstance(value, (dict, str)) else self._value(value)

        issue = {
            "id": key,
            "provider": "jira",
            "url": "%s/browse/%s" % (self.base, key) if self.base else None,
            "type": name(f.get("issuetype")),
            "title": f.get("summary") or "",
            "status": name(f.get("status")),
            "priority": name(f.get("priority")),
            "assignee": name(f.get("assignee"), "displayName"),
            "reporter": name(f.get("reporter"), "displayName"),
            "labels": list(f.get("labels") or []),
            "components": [c.get("name") for c in f.get("components") or []],
            "fix_versions": [v.get("name") for v in f.get("fixVersions") or []],
            "story_points": points,
            "parent": parent,
            "created": f.get("created"),
            "updated": f.get("updated"),
            "description": self._rich(f.get("description")),
            "acceptance_criteria": (self._rich(ac_raw) or None) if ac_raw is not None else None,
            "subtasks": [{"id": s.get("key"), "title": (s.get("fields") or {}).get("summary"),
                          "status": name((s.get("fields") or {}).get("status"))} for s in f.get("subtasks") or []],
            "links": links,
            "attachments": [{"name": a.get("filename"), "url": a.get("content"), "mime": a.get("mimeType"),
                             "size": a.get("size")} for a in f.get("attachment") or []],
            "comments": comments,
            "extra": extra,
        }
        return normalize(issue, "jira")
