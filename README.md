This repository contains source codes behind the automated release and management of APT & RPM packages of swiftwave and swiftwave related tools.

This is integrated with CI, Once the release published, the CI will build all the .deb and .rpm files and trigger the repo server to fetch all the files from github. Then the server will re-index all the packages. Workflow example - Check `.github/workflows/release.yml` of https://github.com/swiftwave-org/stats-ninja


**License**

MIT License
