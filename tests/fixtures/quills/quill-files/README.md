# Files

A Quill for [Cloudmorrow](https://github.com/Cloudmorrow/cloudmorrow): your
own drive on the server, your fileshares, and what is in them — the way a
file manager shows a folder.

- **My Files** is a folder of your own on the server, there from the day
  your account is. Nothing to set up.
- **Shares** sit beside it: a folder on the server that everyone's machines
  mount (an administrator makes those), or a directory on one of your own
  machines, served by its agent. A machine share is listed, and says whether
  its machine is serving it; its files are on that machine, so you mount it
  to see them.
- Open one and it is its folders and files: as a list that says when and how
  big, or as tiles that show what a picture is of. Put files in from the
  phone, the camera, a drag or a paste; make folders; rename, move and
  delete; open a picture; save or share anything.
- In the Cloudmorrow desktop app, each share can be mounted on the computer
  it runs on, opened in its file manager and unmounted, from the same list.

The files stay files, where they have always been: in your drive and the
Shares folder on the server, reached over WebDAV, `cm share mount` and the
desktop app just as before. This Quill carries only the screen.

## What it adds to your Cloudmorrow

| | |
| --- | --- |
| Datamodels | uses the foundational `share` and `file` (domain *Files*), served by the core from the shares and each person's drive |
| Screens | one grid: the shares, then folders and tiles — on the phone, the web app, the terminal, `cm files`, and to your assistant |
| Jobs | none |
| Datasets | none: My Files is there because your account is |
| Services, webhooks, APIs | none |

It contains no code: everything above is declared in [`quill.toml`](quill.toml).

On the command line:

```
cm files list                      # My Files and your shares
cm files list my-files Photos      # a folder
cm files get my-files Photos/cat.jpg [out]
cm files put my-files Photos ./dog.jpg
```

## Working on it

See [CLAUDE.md](CLAUDE.md). In short: `cm quill check`, then `cm quill dev`.

## Licence

AGPL-3.0-or-later.
