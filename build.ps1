# Builds the ready-to-use program into .\output
#   output\Osu!Mania MPC.exe     the program (Python, the interface, the difficulty calculator and the
#                                dan symbols packed into one file with PyInstaller)
#   output\ffmpeg.exe            audio converter the program needs next to it (copied from PATH or from
#                                the Companella install on this PC; about 100 MB, so it is not packed
#                                inside the exe: that would unpack 100 MB on every start)
#   output\README.txt            the user guide
#   output\packs\                where exported packs go by default (created by the program; kept by builds)
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$out = Join-Path $root 'output'
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ('mpc-build-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $out, $stage | Out-Null

try {
    $web = Join-Path $root 'src\mpc\web'
    $bin = Join-Path $root 'src\mpc\bin'
    if (-not (Test-Path (Join-Path $bin 'mmr-calc.exe'))) {
        Write-Warning 'src\mpc\bin\mmr-calc.exe is missing: the build will have no difficulty estimates.'
    }
    & python -m PyInstaller --noconfirm --clean --onefile --windowed --log-level WARN `
        --name 'Osu!Mania MPC' `
        --icon (Join-Path $web 'mpc.ico') `
        --paths (Join-Path $root 'src') `
        --add-data "$web;mpc/web" `
        --add-data "$bin;mpc/bin" `
        --exclude-module numpy --exclude-module PIL --exclude-module tkinter `
        --distpath (Join-Path $stage 'dist') --workpath (Join-Path $stage 'work') --specpath $stage `
        (Join-Path $root 'tools\entry.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
    $exe = Join-Path $stage 'dist\Osu!Mania MPC.exe'
    if (-not (Test-Path -LiteralPath $exe)) { throw 'the exe was not produced' }
    try { Copy-Item -LiteralPath $exe (Join-Path $out 'Osu!Mania MPC.exe') -Force }
    catch { throw 'output\Osu!Mania MPC.exe is in use. Close the program, then build again.' }
    # the program was called "Map Pack Create" up to 0.1.1: that build is replaced by this one
    $old = Join-Path $out 'Map Pack Create.exe'
    if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue }
}
finally {
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
}

# ffmpeg next to the exe
$ffTarget = Join-Path $out 'ffmpeg.exe'
if (-not (Test-Path $ffTarget)) {
    $ff = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
    if (-not $ff) {
        $ff = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Companella') -Directory -Filter 'app-*' -ErrorAction SilentlyContinue |
            Where-Object { Test-Path (Join-Path $_.FullName 'ffmpeg.exe') } |
            Sort-Object { [version]($_.Name.Substring(4)) } | Select-Object -Last 1 |
            ForEach-Object { Join-Path $_.FullName 'ffmpeg.exe' }
    }
    if ($ff) { Copy-Item $ff $ffTarget } else { Write-Warning 'ffmpeg.exe was not found: put one next to the exe by hand.' }
}
Copy-Item (Join-Path $root 'docs\README.txt') (Join-Path $out 'README.txt') -Force

foreach ($part in @('Osu!Mania MPC.exe', 'ffmpeg.exe', 'README.txt')) {
    $target = Join-Path $out $part
    if (Test-Path -LiteralPath $target) { '{0,12:N0} bytes  {1}' -f (Get-Item -LiteralPath $target).Length, $part }
}
