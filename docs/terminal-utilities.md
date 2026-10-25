# Terminal utilities

The core module installs `lsd`, `bat` (command: `batcat`) and `neovim` from the distribution repositories, without third-party installers or development builds.

Interactive Zsh provides Ro's aliases when the corresponding executable exists:
- `ls`, `l`, `ll`, `la`, `lla`: lsd, directories first.
- `cat`: batcat; `catn`: plain style; `catp`: no paging; `catnp`: plain style without paging.
- `EDITOR` and `VISUAL`: nvim.

Non-interactive scripts keep their normal commands. Use `command cat` or `/bin/cat` for the original command interactively.

Neovim receives a small offline configuration: line numbers, mouse support, case-smart searches, four-space indentation, true color and Escape to clear search highlighting. No NvChad, plugin manager or automatic downloads. Existing managed files are backed up by the installer and can be restored with its normal restore command. Existing Neovim plugin directories are not removed; this configuration does not migrate them.

This changes the installer, not the configuration of an already installed machine. `--shell bash` does not install Bash aliases.
