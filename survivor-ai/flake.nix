{
  description = "Survivor AI dev shell";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});
    in {
      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [ pkgs.python312 pkgs.uv pkgs.nodejs_22 ];
          shellHook = ''
            export UV_PYTHON=${pkgs.python312}/bin/python3.12
            export UV_PYTHON_DOWNLOADS=never
          '';
        };
      });
    };
}
