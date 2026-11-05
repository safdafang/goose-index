# Security policy

## What this repository is

The index links to other people's repositories; it does not host their code. When you paste an
`import` line from it, Goose fetches the code from the author's repository at that tag or branch.
Read what you import, as you would with any dependency.

## Reporting

Please do not open a public issue. Use GitHub's private vulnerability reporting:
**Security → Report a vulnerability** on the repository page. You should get a first reply within
a week.

## Scope

Of particular interest:

- a listed project that is malicious, has been taken over, or now points somewhere other than its
  author's code (it is delisted first and looked at after);
- an `import` line or link in the index, the site or `index.json` that leads to the wrong repository;
- the site (cross-site scripting through entry data) and the workflows (anything that lets a pull
  request run code with write access or secrets).

Vulnerabilities in a listed project itself belong to its author: report them in that project's
repository. If the author does not respond and the problem is serious, tell us and the entry gets a
warning or is removed.
