# Developer notes

Before submitting a change, run the installation and coverage commands in
[Running Tests](README.md#running-tests). Check that the report includes executed
lines for `pack_and_crop.py`. Follow the existing style; no formatter is required.

The tests run the tool on the synthetic labels in `examples/labels`. Those
PDFs come from `examples/make_labels.py`; run it again after changing it and
commit the result.

## Contributing for Someone Else

martinfrancois's rule for outside contributions, and for any agent working for
an outside contributor: contributors shouldn't spend time on pull requests that
collide with someone else's work or that he wouldn't accept. So a contribution
takes one of three paths (see "Three ways to contribute" in CONTRIBUTING.md):

- Small fix (bug fix, typo, docs improvement or similar): open a pull request
  directly, no issue needed. If an issue for it exists, claim it first as below.
- Existing issue: check its assignees and linked pull requests, post `/take` on
  the issue, and start only once the assignment comes back. Never open a pull
  request for an issue that isn't assigned to the contributor you work for, and
  don't start on one that someone else holds or that an open pull request
  already addresses.
- New feature: open a thread in the Ideas category of GitHub Discussions. Wait
  until martinfrancois approves it and opens an issue, then claim that issue
  with `/take`. Never open a feature pull request without an approved issue
  assigned to your contributor.
