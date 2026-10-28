"""Exercise a test container through its public Web API without sending Telegram messages."""

import argparse
import http.cookiejar
import json
import urllib.error
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--password-file", type=Path, required=True)
parser.add_argument("--cookie-file", type=Path, required=True)
parser.add_argument("--phase", choices=("initial", "restart"), required=True)
args = parser.parse_args()
jar = http.cookiejar.MozillaCookieJar(str(args.cookie_file))
if args.cookie_file.exists():
    jar.load(ignore_discard=True, ignore_expires=True)
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def request(route, method="GET", data=None, headers=None):
    value = urllib.request.Request(
        args.url + "/api/" + route,
        method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={
            "Origin": args.url,
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    try:
        with opener.open(value, timeout=10) as response:
            content = response.read()
            return response.status, json.loads(
                content
            ) if "application/json" in response.headers.get(
                "Content-Type", ""
            ) else content
    except urllib.error.HTTPError as error:
        return error.code, error.read()


assert request("health")[0] == 200
assert request("snapshot")[0] == 401, "A stale or anonymous session was accepted"
assert (
    request("web/login", "POST", {"password": args.password_file.read_text().strip()})[
        0
    ]
    == 200
)
if args.phase == "initial":
    assert request("server-files")[0] == 200
    names = [entry["name"] for entry in request("server-files")[1]["entries"]]
    assert "escape.png" not in names and "outside" not in names
    assert request("server-files/register", "POST", {"paths":["escape.png"]})[1]["failures"]
    assert request("server-files", headers={"Origin": "https://evil.test"})[0] == 403
    status, result = request("server-files/register", "POST", {"paths": ["cover.png"]})
    assert status == 200 and len(result["assets"]) == 1
    asset = result["assets"][0]
    status, image = request(f"media/{asset['id']}/file", headers={"Range": "bytes=0-9"})
    assert status == 206 and len(image) == 10
    assert (
        request("settings", "PUT", {"api_hash": "0123456789abcdef0123456789abcdef"})[0]
        == 200
    )
    assert (
        request(
            "drafts/current",
            "PUT",
            {"title": "Container restart check", "items": [{"media_id": asset["id"]}]},
        )[0]
        == 200
    )
    jar.save(ignore_discard=True, ignore_expires=True)
else:
    snapshot = request("snapshot")[1]
    assert snapshot["draft"]["title"] == "Container restart check"
    assert snapshot["settings"]["has_api_hash"] is True
print(f"Container API {args.phase} check passed")
