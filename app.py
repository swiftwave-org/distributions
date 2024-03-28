import os
import sys
import time
from flask import Flask, request
import requests
from threading import Thread
import json
from filelock import FileLock

from repo import process_repo

app = Flask(__name__)

SECRET_KEY = os.getenv("SECRET_KEY")
RPM_BASE_URL = os.getenv("RPM_BASE_URL")
DEB_BASE_URL = os.getenv("DEB_BASE_URL")
log_file = "./log.txt"
task_file = "./task.json"

def log(msg):
    with open(log_file, "a") as f:
        f.write(msg + "\n")

def process_release_request():
    is_new_assets_added = False
    while True:
        try:
            with FileLock(f"{task_file}.lock"):
                with open(task_file, "r") as f:
                    tasks = json.load(f)

            if not tasks:
                if is_new_assets_added:
                    print("Processing repo")
                    process_repo(RPM_BASE_URL, log)
                    is_new_assets_added = False
                    continue
                else:
                    time.sleep(5)  # Wait for 5 seconds if no tasks are available
                    continue

            asset = tasks.pop(0)
            with FileLock(f"{task_file}.lock"):
                with open(task_file, "w") as f:
                    json.dump(tasks, f)

            download_url = asset.get('browser_download_url')
            file_name = asset.get('name')

            res = requests.get(download_url)
            if res.status_code < 200 or res.status_code >= 300:
                log(f"Failed to download {file_name}")
                continue

            with open(f"source/{file_name}", "wb") as f:
                f.write(res.content)

            log(f"Downloaded {file_name}")
            is_new_assets_added = True

        except Exception as e:
            with open(log_file, "a") as f:
                f.write(str(e))

@app.get('/')
def run_update():
    # verify secret key in Authorization header
    log(request.headers.get('Authorization'))
    print(SECRET_KEY)
    if request.headers.get('Authorization') != SECRET_KEY:
        return "Unauthorized", 401
    repo_name = request.args.get('repo_name')
    if not repo_name:
        return "repo_name is required", 400
    # check for release tag
    release_tag = request.args.get('release_tag')
    if not release_tag:
        return "release_tag is required", 400
    # build url
    url = f"https://api.github.com/repos/{repo_name}/releases/tags/{release_tag}"
    res_body = requests.get(url)
    if res_body.status_code != 200:
        return "Invalid release tag", 400
    # get the assets
    assets = res_body.json().get('assets')
    # filter *.deb and *.rpm files
    assets = [a for a in assets if a.get('name').endswith('.deb') or a.get('name').endswith('.rpm')]
    # dump the task
    with FileLock(f"{task_file}.lock"):
        with open(task_file, "r") as f:
            tasks = json.load(f)
        tasks.extend(assets)
        with open(task_file, "w") as f:
            json.dump(tasks, f)    
    return "OK", 200

if __name__ == '__main__':
    if os.getenv("RPM_BASE_URL") is None:
        print("Please set RPM_BASE_URL in environment")
        sys.exit(1)
    if os.getenv("DEB_BASE_URL") is None:
        print("Please set DEB_BASE_URL in environment")
        sys.exit(1)
    if not os.path.exists("source"):
        os.makedirs("source")
    if not os.path.exists(task_file):
        with open(task_file, "w") as f:
            json.dump([], f)

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "worker":
            process_release_request()
        elif cmd == "hook":
            os.environ['FLASK_ENV'] = 'production'
            app.run(debug=False, host='localhost', port=3000)
        elif cmd == "process_repo":
            process_repo(RPM_BASE_URL, log)