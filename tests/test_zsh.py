"""Zsh configuration and vendored prompt must work without network setup."""
import hashlib
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ZshTests(unittest.TestCase):
    def test_interactive_setup_is_local_and_skips_wizard_and_gitstatus(self):
        config = (ROOT / "config/zsh/zshrc").read_text()
        self.assertIn("[[ -o interactive ]] || return", config)
        self.assertIn("POWERLEVEL9K_DISABLE_CONFIGURATION_WIZARD=true", config)
        self.assertIn("POWERLEVEL9K_DISABLE_GITSTATUS=true", config)
        self.assertIn("$HOME/.local/share/debian-i3-dotfiles/powerlevel10k", config)
        self.assertIn(".p10k.zsh", config)
        self.assertNotRegex(config, r"(?i)oh-my-zsh|curl|wget|git clone|chsh")

    def test_prompt_is_sanitized_and_has_git_vcs_fallback(self):
        prompt = (ROOT / "config/zsh/p10k.zsh").read_text()
        self.assertIn("POWERLEVEL9K_LEFT_PROMPT_ELEMENTS", prompt)
        self.assertIn("vcs", prompt)
        self.assertNotRegex(prompt, r"/home/[^\s\"']+|/Users/[^\s\"']+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")

    def test_vendor_is_exact_pinned_upstream_runtime_without_gitstatus_installer(self):
        vendor = ROOT / "vendor/powerlevel10k"
        self.assertTrue((vendor / "powerlevel10k.zsh-theme").is_file())
        self.assertTrue((vendor / "internal/p10k.zsh").is_file())
        self.assertTrue((vendor / "LICENSE").is_file())
        self.assertTrue((vendor / "PROVENANCE.md").is_file())
        self.assertFalse((vendor / "gitstatus").exists())
        self.assertEqual(hashlib.sha256((vendor / "powerlevel10k.zsh-theme").read_bytes()).hexdigest(), "6da8dc90bd84d96f280d5c9fb23ef6310823dcd0f74e655751fc8295d886da3f")
        self.assertEqual(hashlib.sha256((vendor / "internal/p10k.zsh").read_bytes()).hexdigest(), "ad470caf3cd445f58beaf56177c09edaff26b5df4d0b1765bfa48852cacfbd4e")
        self.assertEqual(hashlib.sha256((vendor / "LICENSE").read_bytes()).hexdigest(), "4fb6c63d7d7ece6d4a68c9a8cc42d3c6a5c7e1303f0b501f68aa6b470270aec6")

    def test_core_plan_has_home_configs_and_theme(self):
        import importlib.util
        import os
        import tempfile
        from unittest import mock
        spec = importlib.util.spec_from_file_location('zsh_installer', ROOT / 'install.py')
        assert spec is not None and spec.loader is not None
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {'HOME': folder}):
            home = Path(folder)
            for distro in ('debian', 'ubuntu', 'kali', 'parrot'):
                for package in ('zsh', 'lsd', 'bat', 'neovim'):
                    self.assertIn(package, installer.package_names(['core'], distro))
                self.assertIn('xserver-xorg', installer.package_names(['core'], distro))
            targets = dict((str(target), source) for source, target in installer.plan(['core']))
            self.assertEqual(targets[str(home / '.zshrc')], ROOT / 'config/zsh/zshrc')
            self.assertEqual(targets[str(home / '.p10k.zsh')], ROOT / 'config/zsh/p10k.zsh')
            self.assertIn(str(home / '.local/share/debian-i3-dotfiles/powerlevel10k/internal/p10k.zsh'), targets)
            self.assertEqual(len(targets), len(installer.plan(['core'])))

    def test_terminal_utilities_configuration(self):
        config = (ROOT / 'config/zsh/zshrc').read_text()
        for alias in ("ls='lsd --group-dirs=first'", "ll='lsd -lh --group-dirs=first'",
                      "cat='batcat'", "catnp='batcat --style=plain --paging=never'"):
            self.assertIn(alias, config)
        self.assertIn("export EDITOR=nvim", config)
        nvim = (ROOT / 'config/nvim/init.lua').read_text()
        self.assertIn('vim.opt.number = true', nvim)
        self.assertNotRegex(nvim, r'require|https?://|git clone')

    def test_docs_explain_scope_and_no_runtime_download(self):
        docs = (ROOT / "docs/zsh.md").read_text().lower()
        self.assertIn("does not require oh my zsh", docs)
        self.assertIn("network commands", docs)
        self.assertIn("gitstatus", docs)


if __name__ == "__main__":
    unittest.main()
