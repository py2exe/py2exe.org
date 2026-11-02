# Publishing to GitHub Pages

GitHub Actions runs `mise run build` when a pull request opens, reopens, or
receives new commits. Each push to `main` queues `mise run publish`. The
publishing job checks out the current `main` with its full history so queued
runs and retries deploy the latest source. Both jobs use
[mise-action][mise-action] with a three-day minimum release age for mise.

## First deployment

1. Under the repository's **Settings → Environments**, create
   `pages-publishing`. Set **Deployment branches and tags** to **Selected
   branches and tags** and add a branch rule for `main`. See [Environments][env].
2. Create a fine-grained personal access token from a repository administrator
   account with a verified email. Limit it to `py2exe/py2exe.org` and grant
   **Contents: Read and write**. Save it as the environment secret
   `PAGES_PUBLISH_TOKEN`. A push using the default Actions token cannot trigger
   a branch-based Pages deployment. See the [publishing source guide][source].
3. An organization owner verifies `py2exe.org` under the `py2exe`
   organization's **Settings → Pages** using GitHub's DNS TXT record. Keep
   that record after verification. See the [domain verification guide][verify].
4. Push the generated source history to `main`. Wait for the
   **Publish Documentation** job to create `gh-pages` with the built site.
5. Under **Settings → Pages**, select **Deploy from a branch**, choose
   `gh-pages` and `/(root)`, and save. Set the custom domain to
   `py2exe.org`.
6. Set these records in your DNS provider. For `py2exe.org`, use an `ALIAS`
   or `ANAME`, or a `CNAME` if your provider supports apex CNAME flattening.
   For `www.py2exe.org`, use a `CNAME`. Point both records to
   `py2exe.github.io.` and replace conflicting web-hosting records for these
   names. See the [custom domain guide][domains].

   | Host | Target |
   | --- | --- |
   | `py2exe.org` | `py2exe.github.io.` |
   | `www.py2exe.org` | `py2exe.github.io.` |

7. After DNS propagates and GitHub provisions the certificate, select **Enforce
   HTTPS** in Pages settings. GitHub Pages serves
   <https://py2exe.org/> and redirects <https://www.py2exe.org/> to it.

## Require the build before merging

After **Build Documentation** passes on a pull request, create an active branch
ruleset under **Settings → Rules → Rulesets** that targets `main`. Enable
**Require a pull request before merging** and **Require status checks to pass**.
Add **Build Documentation** from GitHub Actions, require branches to be up to
date before merging, and leave the bypass list empty. See [Rulesets][rulesets].

## Publish manually

Maintainers can also run the task from a full checkout of `main` with their
configured Git identity and GitHub SSH credentials. Their account needs write
access to `gh-pages`.

```sh
mise run publish
```

The task builds the committed `HEAD` in a temporary checkout. It generates
[Recent Changes](https://py2exe.org/recent-changes/) from the latest 20
documentation commits, including imported wiki edits while they fit. It runs
the site's Markdown checks and build once, adds `.nojekyll` and `CNAME` to the
rendered site, then creates `gh-pages` or pushes a fast-forward update to it.
If the branch changes during publishing, rerun the task. The repository's
**Actions** tab shows the GitHub Pages deployment status.

The [Zensical redirects plugin][redirects] builds static redirect pages for
legacy wiki URLs from `zensical.toml`. These pages redirect in the browser and
preserve URL fragments when JavaScript is enabled. Requests with legacy
attachment queries follow the article's redirect. The custom 404 page handles
legacy aliases that differ from a current path only by case. Unknown paths and
removed pages without a destination show the normal 404 page.

[mise-action]: https://github.com/jdx/mise-action
[env]: https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments
[rulesets]: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
[verify]: https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages
[source]: https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site
[domains]: https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site
[redirects]: https://zensical.org/docs/setup/redirects/
