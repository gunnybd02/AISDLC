"""GitLab REST, the few calls the harness makes: the project of a remote URL and opening a merge request. A token is
read from GITLAB_TOKEN when set (else the network proxy may give one); it is never written anywhere."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

TIMEOUT = 30
REMOTE = re.compile(r"^(?:https?://(?:[^@/]+@)?(?P<host>[^/:]+)(?::\d+)?/|git@(?P<ssh>[^:]+):|ssh://git@(?P<sshh>[^/:]+)"
                    r"(?::\d+)?/)(?P<path>.+?)(?:\.git)?/?$")


class GitLabError(RuntimeError):
    """A GitLab call failed: not a GitLab remote, GitLab answered an error, or it cannot be reached."""


def project_of(remote_url: str) -> tuple[str, str]:
    """(api base, project path) of a GitLab remote URL (https or ssh).

    Args:
        remote_url: the remote's URL (https://host/group/project.git, git@host:group/project.git, ssh://git@host/...).

    Returns:
        ("https://<host>/api/v4", "group/project").

    Raises:
        GitLabError: the URL is not one of those forms.
    """
    m = REMOTE.match(str(remote_url).strip())
    if not m:
        raise GitLabError(f"{remote_url} is not a GitLab remote URL")
    host = m["host"] or m["ssh"] or m["sshh"]
    return f"https://{host}/api/v4", m["path"]


def call(method: str, url: str, data: Optional[dict[str, Any]] = None, token: Optional[str] = None) -> Any:
    """One call to GitLab REST with a JSON body.

    Args:
        method: the HTTP method (GET, POST...).
        url: the full URL of the endpoint.
        data: the JSON body, or None for none.
        token: the PRIVATE-TOKEN; None reads GITLAB_TOKEN (none set: no header, the proxy may add one).

    Returns:
        The decoded JSON answer (a dict for most calls; None for an empty body).

    Raises:
        GitLabError: GitLab answered an HTTP error, or cannot be reached, or the answer is not JSON.
    """
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


def open_mr(api: str, project: str, source: str, target: str, title: str, description: str,
            token: Optional[str] = None) -> Any:
    """The merge request GitLab made: {iid, web_url, ...}.

    Args:
        api: the API base (project_of).
        project: the project path (project_of).
        source: the branch merged.
        target: the branch merged into.
        title: the merge request's title.
        description: its description.
        token: the PRIVATE-TOKEN; None reads GITLAB_TOKEN.

    Returns:
        GitLab's answer: the merge request as JSON ({iid, web_url, ...}).

    Raises:
        GitLabError: the call fails.
    """
    url = f"{api}/projects/{urllib.parse.quote(project, safe='')}/merge_requests"
    return call("POST", url, {"source_branch": source, "target_branch": target, "title": title,
                              "description": description, "remove_source_branch": True}, token)
