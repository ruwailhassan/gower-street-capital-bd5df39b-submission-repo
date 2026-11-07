# First upload to GitHub

Explain briefly as needed: a commit saves selected files locally; a push uploads commits; a branch names a line of work; a pull request proposes merging changes.

## Tools and login

Check tools before installing anything. Use Python 3.9+ already on the machine. On Windows try `py -3 --version`; a `python3` Microsoft Store shortcut is not proof that Python is installed.

macOS, if Homebrew is already available:

```bash
brew install git gh gitleaks
```

Windows PowerShell, if WinGet is available:

```powershell
winget install --id Git.Git --exact
winget install --id GitHub.cli --exact
winget install --id Gitleaks.Gitleaks --exact
```

Install Python from [python.org](https://www.python.org/downloads/) only if no supported interpreter is available. Use official [Git](https://git-scm.com/downloads), [GitHub CLI](https://cli.github.com/) and [Gitleaks](https://github.com/gitleaks/gitleaks#installing) installers if the package manager is absent. Reopen the terminal/app after PATH changes and verify versions. Gitleaks must be v8.30.1+ in the v8 series. Windows instructions are documented but have not been live-tested here.

Check `gh auth status`. If login is needed, run `gh auth login --hostname github.com --git-protocol https --web` and let the participant complete browser sign-in. Do not print tokens, read credential files, use `gh auth token`, pass tokens as arguments or select insecure credential storage.

## Team repository first

Use the team's shared repository. Reuse its link when established in project instructions or this conversation; otherwise ask **“What is your team's GitHub repository link?”** Check the actual remote owner/repository, push URLs, URL rewrites and mirror settings locally without printing credentials. Do not assume a participant's existing personal `origin` is correct. Do not silently replace it.

If the participant has no team clone, help clone the agreed repository into a separate folder and transfer only their reviewed files, preserving both copies and any existing history. Never fix unrelated histories with a force-push. Missing access means a team owner needs to invite the participant; do not substitute a personal repo or fork. Only create a new team repository when explicitly requested, with its owner/name/visibility established.

## Ordinary team changes

1. Ask once: **“In one sentence, what did you change and why?”** Reuse an explanation already supplied. Write a short factual commit message and PR summary from the answer and actual changed files.
2. Discover the team's real base branch and existing review rules. Create/use a descriptive feature branch for this participant's changes, preserving unrelated work. Prepare ignore rules and README corrections as needed; run the secret helper and relevant checks.
3. Stage explicit reviewed paths, inspect staged content without exposing credentials, and rerun the helper. Preserve unrelated staged changes. Commit with the short message, then rerun the helper so the new commit is scanned.
4. Verify the destination and reviewed revision again, then push only the feature branch. Replace placeholders with actual agreed values:

```bash
git push --set-upstream TEAM_REMOTE HEAD:refs/heads/FEATURE_BRANCH
```

5. Open or update a pull request in the team repository against the actual base branch. Write its purpose, actual checks and remaining limitations to a temporary Markdown file, then use:

```bash
gh pr create --repo TEAM/PROJECT --base ACTUAL_BASE_BRANCH --head FEATURE_BRANCH --title "Short factual summary" --body-file /absolute/path/to/pr-body.md
```

Reuse an existing PR instead of opening a duplicate. Observe its URL and CI state; distinguish pending/failed/passed. If PR creation fails, report the push accurately and give the actual compare link or GitHub steps to open it. Do not claim a PR exists before verifying it.

6. Give one precise next step: **“You: open [PR] and choose a teammate under Reviewers. Ask them to check the changed files and run [actual test/use command].”** If a reviewer was already identified, use their name. Request their review through GitHub only when authorised; do not invent a reviewer or send separate messages. Say what needs checking if no useful automated test exists.

Explain that review is still pending after a push. The teammate can approve or request changes. If changes are requested, fix them, rerun affected checks and secret scanning, and push to the same feature branch so the PR updates. Leave merging to the team's process; do not auto-merge.

## Empty team repository: first upload

Verify that the agreed team repository is genuinely empty. Establish the intended initial branch. If needed, initialise Git in the correct project folder and help configure the author's identity locally. Do not reinitialise an existing repository or rename its branches blindly.

Ask for the one-sentence change explanation, prepare ignore rules and README, run the checks, stage only reviewed files, scan, commit and scan again. Link an unused remote name to the agreed team repository only when necessary; preserve existing remotes. Push the specific initial branch and verify that the remote revision matches the reviewed local commit, for example with `git ls-remote TEAM_REMOTE refs/heads/INITIAL_BRANCH` and `git rev-parse HEAD`.

A first commit cannot open a PR against itself. Return the actual commit link and say: **“Next: have a teammate open this commit, check the uploaded files and run [actual README/test command]. Use feature branches and pull requests for subsequent changes.”** Never label an initial upload as approved or invent a PR.

A request to push should end with a push when safe and authorised. Stop only for sign-in, missing team access/destination, unresolved secrets or scan errors, or a consequential issue requiring the participant's decision. Never bypass hooks/protection or force-push after rejection.

Sources: [Creating a PR](https://cli.github.com/manual/gh_pr_create), [requesting teammate review](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/requesting-a-pull-request-review).
