{ pkgs ? import <nixpkgs> { } }:

pkgs.mkShell {
  packages = [ pkgs.uv ];

  shellHook = ''
    export VIRTUAL_ENV="${toString ./.}/.venv"
    export PATH="$VIRTUAL_ENV/bin:$PATH"
  '';
}
