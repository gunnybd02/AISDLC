"""GitLab REST, the few calls the harness makes: the project of a remote URL and opening a merge request. A token is
read from GITLAB_TOKEN when set (else the network proxy may give one); it is never written anywhere."""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30
REMOTE = re.compile(r"^(?:https?://(?:[^@/]+@)?(?P<host>[^/:]+)(?::\d+)?/|git@(?P<ssh>[^:]+):|ssh://git@(?P<sshh>[^/:]+)"
                    r"(?::\d+)?/)(?P<path>.+?)(?:\.git)?/?$")


class GitLabError(RuntimeError):
    pass


def project_of(remote_url):
    """(api base, project path) of a GitLab remote URL (https or ssh)."""
    m = REMOTE.match(str(remote_url).strip())
    if not m:
        raise GitLabError(f"{remote_url} is not a GitLab remote URL")
    host = m["host"] or m["ssh"] or m["sshh"]
    return f"https://{host}/api/v4", m["path"]


def call(method, url, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    token = token if token is not None else os.environ.get("GITLAB_TOKEN")
    if token:
        headers["PRIVATE-TOKEN"] = token
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        raise GitLabError(f"GitLab answered {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise GitLabError(f"GitLab cannot be reached: {e}") from e


def open_mr(api, project, source, target, title, description, token=None):
    """The merge request GitLab made: {iid, web_url, ...}."""
    url = f"{api}/projects/{urllib.parse.quote(project, safe='')}/merge_requests"
    return call("POST", url, {"source_branch": source, "target_branch": target, "title": title,
                              "description": description, "remove_source_branch": True}, token)
