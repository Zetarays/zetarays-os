# ZETA RAYS — fish interattiva
status is-interactive; or exit
set -g fish_greeting ''
# comandi con password, chiavi o token: fuori dalla cronologia di fish
function fish_should_add_to_history
    string match -qri '(password|passwd|token|secret|api_key|api-key)=' -- $argv; and return 1
    string match -qri -- '--(password|passwd|token|api-key|apikey)' $argv; and return 1
    string match -qr '(sk-ant-|sk-proj-|ghp_|glpat-)' -- $argv; and return 1
    string match -qr '^ ' -- $argv; and return 1
    return 0
end
if type -q eza
    alias ls 'eza --group-directories-first'
    alias ll 'eza -la --group-directories-first --git --time-style=long-iso'
end
type -q batcat; and alias bat batcat
type -q fdfind; and alias fd fdfind
set -gx LESS '-R -F -X -i -M'
if not test -f ~/.config/starship.toml; and test -f ~/.cache/zeta/starship.toml
    set -gx STARSHIP_CONFIG ~/.cache/zeta/starship.toml
end
set -q ZETA_SHELL_SEMPLICE; and exit
type -q atuin; and atuin init fish --disable-up-arrow | source
type -q starship; and starship init fish | source
