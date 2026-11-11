# Rebuilds src\mpc\bin\mmr-calc.exe from the MMR project's calc crate (..\maniatracker\calc, read only)
# with this PC's folder paths removed from the binary, so that the program can be handed to other people.
# The stock build embeds C:\Users\<account>\.cargo\... in its panic messages.
# Same source, same pinned dan-calc commit, same flags as maniatracker\build-calc.ps1: the numbers do not change.
# Needs the Rust toolchain (%USERPROFILE%\.cargo) and the Visual C++ build tools. Builds in a temp folder.
# Usage:  powershell -ExecutionPolicy Bypass -File tools\build_calc.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$calc = Join-Path (Split-Path -Parent $root) 'maniatracker\calc'
if (-not (Test-Path (Join-Path $calc 'Cargo.toml'))) { throw "calc crate not found at $calc" }
$cargoBin = Join-Path $env:USERPROFILE '.cargo\bin'
if (Test-Path $cargoBin) { $env:PATH = "$cargoBin;$env:PATH" }
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw 'cargo was not found.' }

$target = Join-Path ([System.IO.Path]::GetTempPath()) 'mpc-calc-target'
$env:CARGO_TARGET_DIR = $target
# CARGO_ENCODED_RUSTFLAGS: flags separated by 0x1f, because the folder paths here contain spaces
$sep = [string][char]0x1f
$env:CARGO_ENCODED_RUSTFLAGS = @('-C', 'link-arg=/STACK:67108864', '-C', 'target-feature=+crt-static',
    "--remap-path-prefix=$($env:USERPROFILE)=C:\Users\user", "--remap-path-prefix=$calc=calc") -join $sep
Remove-Item Env:RUSTFLAGS -ErrorAction SilentlyContinue
cargo build --release --locked --offline --manifest-path (Join-Path $calc 'Cargo.toml')
if ($LASTEXITCODE -ne 0) { throw 'cargo build failed' }
$built = Join-Path $target 'release\mmr-calc.exe'
& $built --version
Copy-Item $built (Join-Path $root 'src\mpc\bin\mmr-calc.exe') -Force
'{0,10:N0} bytes  src\mpc\bin\mmr-calc.exe' -f (Get-Item (Join-Path $root 'src\mpc\bin\mmr-calc.exe')).Length
