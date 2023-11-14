com! -nargs=1 FindInFiles call VimGrepFile(<f-args>)
function! VimGrepFile(pattern)
  exe ':vim /' . a:pattern . '/g **/*'
endfunction

com! -nargs=+ FindInFilesExt call VimGrepFileExt(<f-args>)
function! VimGrepFileExt(ext,pattern)
  exe ':se wildignore+=**/test/**,**/legacy/**'
  exe ':vim /' . a:pattern . '/g **/*.{md,py,ipynb}' 
  exe ':vim /' . a:pattern . '/g **/*.' . a:ext
endfunction

com! -nargs=1 FindInFilesPythonMD call VimGrepFile(<f-args>)
function! VimGrepFile(pattern)
  exe ':se wildignore+=**/test/**,**/legacy/**'
  exe ':vim /' . a:pattern . '/g **/*.{md,py,ipynb}' 
  exe ':se wildignore-=**/test/**,**/legacy/**'
endfunction

noremap <Leader>ff :FindInFiles 
noremap <Leader>fe :FindInFilesExt 
noremap <Leader>fm :FindInFilesPythonMD 
noremap <Leader>fc :FindInFiles \(\<console\.\)\\|\(\<print(\)\\|\(pprint\)

noremap <Leader>n :cnext
noremap <Leader>p :cprevious
noremap <Leader>N :clast
noremap <Leader>P :cfirst
noremap <Leader>s :vert cwindow 80

" SPELLING
set spellcapcheck=
noremap <F4> :setlocal spell spelllang=en_us
noremap <S-F4> :setlocal nospell
noremap <Leader>= :spellrepall
" next one: turns spell-check off for lines starting with ,,
nnoremap <Leader>si :syntax match ignoreblock /^,,.*/ contains=@NoSpell<CR>

" put fields of line in registers, go to right window, open file, and goto pattern
noremap <Leader>ss mf?^=<CR>l"dy$`f0"wyt<Bar>f<Bar>l"fyt<Bar>f<Bar>l"py$<CR><C-W>l:e<C-R>d/<C-R>f<CR>1G/<Bslash><<C-R>w<Bslash>><CR>

" put word on current line in register, got to right window, to end, insert
" new line with that word, save, go back, delete line, save
noremap <Leader>sg 0"wy$<C-W>lGo<C-R>w<Esc>:w<CR><C-W>hdd:w<CR>

" go to matching brace and then one line down

noremap <Leader>sn %j

" go to start of file, go to next brace, go to matching brace and then next
" left brace, do this a number of times, go to previous left brace
" the number of times is taken from register p
" In a json file, it goes to the n-th member of a list, assuming
" each member is braced
" In an ipynb file (json) it goes to the start of the n-th cell!

map <Leader>sm :let<Space>@-='%j'<CR>1G0<CR><CR>:execute<Space>'normal!'.@p.'@-'<CR>n
