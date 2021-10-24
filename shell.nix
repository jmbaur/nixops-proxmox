{ pkgs ? import <nixpkgs> { } }:
let
  overrides = import ./overrides.nix { inherit pkgs; };
in
pkgs.mkShell {
  nativeBuildInputs = with pkgs; [
    poetry
    sqlite
  ];
  buildInputs = [
    (pkgs.poetry2nix.mkPoetryEnv {
      projectDir = builtins.path { path = ./.; };
      overrides = pkgs.poetry2nix.overrides.withDefaults overrides;
    })
  ];
}
