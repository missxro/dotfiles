-- Small, offline configuration compatible with distribution packages.
vim.opt.number = true
vim.opt.mouse = 'a'
vim.opt.ignorecase = true
vim.opt.smartcase = true
vim.opt.expandtab = true
vim.opt.tabstop = 4
vim.opt.shiftwidth = 4
vim.opt.termguicolors = true
vim.opt.updatetime = 300
vim.opt.signcolumn = 'yes'
vim.g.mapleader = ' '
vim.keymap.set('n', '<Esc>', '<cmd>nohlsearch<CR>', { silent = true })
