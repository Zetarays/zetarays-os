# ZETA RAYS — impostazioni comuni a bash e zsh (terminale interattivo).
# shellcheck shell=bash
# Solo alias e variabili: nessun comando lento qui, il terminale deve aprirsi
# subito anche su un computer lento.

# strumenti moderni dove ci sono; i nomi Debian (batcat, fdfind) diventano
# quelli di tutti (bat, fd). I comandi classici restano disponibili: \ls, \cat
if command -v eza >/dev/null 2>&1; then
  alias ls='eza --group-directories-first'
  alias ll='eza -la --group-directories-first --git --time-style=long-iso'
  alias la='eza -a --group-directories-first'
  alias albero='eza --tree --level=2 --group-directories-first'
else
  alias ls='ls --color=auto --group-directories-first'
  alias ll='ls -la --color=auto'
fi
command -v batcat >/dev/null 2>&1 && alias bat='batcat'
command -v fdfind >/dev/null 2>&1 && alias fd='fdfind'
alias grep='grep --color=auto'
alias ip='ip -color=auto'
alias diff='diff --color=auto'

# less: colori, ricerca senza maiuscole, niente pagina se il testo sta nello
# schermo; lesspipe gli fa leggere archivi, PDF, pacchetti .deb e altro
export LESS='-R -F -X -i -M'
[ -x /usr/bin/lesspipe ] && eval "$(SHELL=/bin/sh lesspipe)"
if command -v batcat >/dev/null 2>&1; then
  export BAT_THEME='ansi'
  export MANPAGER="sh -c 'col -bx | batcat -l man -p'"
  export MANROFFOPT='-c'
fi
export EDITOR="${EDITOR:-nano}"

# prompt: configurazione personale se c'e', altrimenti quella di ZETA RAYS con
# il colore d'accento (generata da «zeta shell»)
if [ ! -f "$HOME/.config/starship.toml" ] && [ -f "$HOME/.cache/zeta/starship.toml" ]; then
  export STARSHIP_CONFIG="$HOME/.cache/zeta/starship.toml"
fi
