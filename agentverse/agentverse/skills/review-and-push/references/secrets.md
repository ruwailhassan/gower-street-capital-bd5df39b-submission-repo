# Secret checks and recovery

Real credentials and unresolved plausible credentials stop publishing. Gitleaks uses its built-in rules with repository suppressions, baselines and inline allow comments disabled. The helper does not expose detected values.

## Setup problems

Add stack-appropriate ignore rules before staging: local secret files, dependencies, environments and generated output. Preserve useful existing rules and narrowly allow sanitised examples. Use `git check-ignore` to verify coverage. An ignore rule does not remove an already tracked file or an earlier commit.

A dependency folder listed by the helper usually needs `.gitignore`, rather than hundreds of individual fixes. If it is already tracked, explain and remove only the intended paths from Git tracking when authorised; keep local files. Rerun after changes.

## A secret was found

Identify file, line and commit without displaying the credential. Do not contact a provider to test it. A clearly synthetic placeholder or a credential-free config file can be classified with specific local evidence, but never relabel the helper's finding as a scanner pass. Keep plausible credentials unresolved until investigated.

If a live credential reached GitHub, another person, chat, a log or an uncertain location, have its owner revoke/rotate it and update the secret store. Removal from a file alone is insufficient. If it is in a commit to be pushed, explain the local-history cleanup needed and obtain specific authorisation for that rewrite. Never force-push shared history.

Use safe `.env.example` placeholders such as `<set-locally>`. Never copy actual values into templates or commands. Check privileged keys in browser-facing variables and generated bundles too; a `PUBLIC_` name does not make a privileged key safe.

## Assets the scanner cannot read

PDFs, images, archives, database files and other binary assets are not automatically clean or automatically secret findings. The helper lists them under `needs_review`, with hashes of the exact bytes it encountered. For LFS the hash identifies the pointer; inspect the referenced payload as well. Existing commit history can retain old versions. Text extraction from documents and a visual check of images may be needed; a text scanner cannot read a screenshot of a key.

For each distinct file/hash, either:

- Exclude it from the upload if unnecessary. If already committed, removal from the working copy is insufficient; use an authorised history-cleanup route.
- Inspect it with appropriate local tools and record `file + SHA-256 + method + evidence + result` in the review report. Inspect text/attachments inside a document or archive, and credentials/private data in a database. Use a private temporary directory, avoid unsafe extraction paths and do not execute embedded content. Recheck the hash before pushing.

Separate review may resolve an asset warning without changing the helper to PASS. It cannot waive a real secret finding, a missing scanner, failed text scanning or a timeout. If the asset cannot be examined adequately, leave it out or stop with the specific unresolved coverage gap. Do not invent an automatic “safe PDF” exception.

The report shows at most 20 entries per category with totals. If entries were omitted, fix the grouped setup issue or inspect the remaining files in smaller scoped steps; omitted findings are not resolved.

## Coverage

The helper scans the Git index (files staged for the next commit), tracked/non-ignored working files, patches reachable from the current HEAD, and full historical blobs. Link text is scanned without following the link; submodules require their own scan. Other refs, remote-only content and dangling objects are outside this scan. Shallow history, oversized files and errors remain incomplete. Publish only the exact reviewed branch.

Sources: [Gitleaks](https://github.com/gitleaks/gitleaks), [GitHub credential handling](https://docs.github.com/en/rest/authentication/keeping-your-api-credentials-secure).
