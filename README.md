# My personal dotfiles

## Preview

![Desktop preview](assets/desktop.gif)

### Polybar

![Polybar modules and controls explained](assets/polybar-described.png)

## Setup

- **OS:** Debian, Ubuntu, Kali and Parrot
- **WM:** i3
- **Bar:** Polybar
- **Terminal:** Kitty / Zsh
- **Compositor:** Picom / blur / transparency / fading
- **Wallpaper:** xwinwrap + MPV / one video per active monitor
- **Font:** DepartureMono Nerd Font Mono
- **Included by default:** Fastfetch with bundled artwork
- **Optional:** GTK3 / Graphite-Dark / Qt5ct / Kitty cursor download :3

## Features

- Automatic monitor detection - no fixed outputs or resolutions.
- Bundled Lain video wallpaper, configured automatically; `--wallpaper` selects another local video.
- Launcher dry-runs and per-display singleton locks.
- Cleanup limited to each launcher's own children.

## Aliases

Available in interactive Zsh:

- `ls` / `l`: lsd, directories first; `ll`: long listing with readable sizes.
- `la`: include hidden files; `lla`: combine `ll` and `la`.
- `cat`: batcat with syntax highlighting; `catn`: plain style.
- `catp`: no pager; `catnp`: plain style without a pager.
- `xcopy`: copy to the clipboard - `pwd | xcopy` or `xcopy file.txt`.

Neovim is the default editor (`EDITOR` / `VISUAL`). Use `command cat` for the original cat. [Details](docs/terminal-utilities.md).

## Files

```text
config/     i3 / Polybar / Kitty / Picom / optional appearance
bin/        Wallpaper launchers + shared supervisor helper
packages/   Core and optional package lists
assets/     Desktop preview + licensed DepartureMono fonts
docs/       Manual setup + portability notes
tests/      Repository, launcher and MPRIS checks
```

## Getting started

Run from the repository directory as your normal user:

```sh
./install.sh
```

The installer offers to install the required packages, installs missing bundled fonts and configures the animated wallpaper automatically. Existing files are backed up. Do not run the installer with `sudo`.

To preview changes without installing anything:

```sh
./install.sh --dry-run
```

Python 3.11+ is required to start the installer. An existing i3 session is not required: after installation, select i3 in your login screen. See [setup & recovery](docs/setup.md) for prerequisites, optional components and restore instructions.

## Checks

```sh
python3 -m unittest discover -s tests -v
```

- Automated tests use isolated external-program mocks.
- i3 / Polybar parser checks and real-monitor dry-runs completed.
- Fresh-install visual verification still pending.

[Manual setup & shortcuts](docs/setup.md) / [Portability & remaining work](docs/portability.md)
