# Builds the ready-to-use program into .\output
#   output\Osu!Mania MPC.exe     the program (Python, the interface, the difficulty calculator and the
#                                dan symbols packed into one file with PyInstaller)
#   output\ffmpeg.exe            audio converter the program needs next to it (copied from PATH or from
#                                the Companella install on this PC; about 100 MB, so it is not packed
#                                inside the exe: that would unpack 100 MB on every start)
#   output\README.txt            the user guide
#   output\licenses\             notices for the parts that are not ours (FFmpeg, Mania Tracker, mmr-calc, Python)
#   output\Osu!Mania MPC v<version>.zip
#                                the four items above in one file: THE THING TO SHARE with other people
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
    $target = Join-Path $out 'Osu!Mania MPC.exe'
    $aside = Join-Path $out 'Osu!Mania MPC (previous build, delete me).exe'
    if (Test-Path -LiteralPath $aside) { Remove-Item -LiteralPath $aside -Force -ErrorAction SilentlyContinue }
    try { Copy-Item -LiteralPath $exe $target -Force }
    catch {
        # The program is open. Windows lets a running exe be renamed, not replaced: the open window carries on
        # from the renamed file and the new build takes the usual name. The renamed file goes on the next build.
        try {
            Move-Item -LiteralPath $target $aside -Force
            Copy-Item -LiteralPath $exe $target -Force
            $script:movedAside = $true
        }
        catch { throw 'output\Osu!Mania MPC.exe is in use and could not be moved aside. Close the program, then build again.' }
    }
    # the program was called "Map Pack Create" up to 0.1.1: that build is replaced by this one
    $old = Join-Path $out 'Map Pack Create.exe'
    if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue }
}
finally {
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
}

# Explorer keeps icons by path: tell it this file changed, or it goes on showing the previous build's icon
Add-Type -Namespace MpcBuild -Name Shell -MemberDefinition '[DllImport("shell32.dll", CharSet = CharSet.Unicode)] public static extern void SHChangeNotify(int eventId, uint flags, string item1, IntPtr item2);'
[MpcBuild.Shell]::SHChangeNotify(0x2000, 0x1005, (Join-Path $out 'Osu!Mania MPC.exe'), [IntPtr]::Zero)

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

# notices for what is bundled
$lic = Join-Path $out 'licenses'
New-Item -ItemType Directory -Force $lic | Out-Null
Copy-Item (Join-Path $root 'src\mpc\web\dans\LICENSE.txt') (Join-Path $lic 'Mania Tracker (dan-calc, dan symbols) - MIT.txt') -Force
Copy-Item (Join-Path $root 'src\mpc\bin\THIRD-PARTY-LICENSES.txt') (Join-Path $lic 'mmr-calc - third party licenses.txt') -Force
Copy-Item (Join-Path $root 'docs\NOTICE.txt') (Join-Path $lic 'NOTICE.txt') -Force
$pyLicense = Join-Path (& python -c "import sys; print(sys.base_prefix)") 'LICENSE.txt'
if (Test-Path $pyLicense) { Copy-Item $pyLicense (Join-Path $lic 'Python - PSF licence.txt') -Force }
else { Write-Warning 'Python LICENSE.txt was not found: the share zip will not carry the Python licence.' }
if (Test-Path $ffTarget) {
    $ffInfo = @('ffmpeg.exe in this folder is FFmpeg, a separate program that Osu!Mania MPC runs to convert audio.',
                'It is licensed under the GNU General Public License version 3 or later.',
                'Source code: https://ffmpeg.org/download.html   This build: https://www.gyan.dev/ffmpeg/builds/', '')
    $ffInfo += (& $ffTarget -hide_banner -version | Select-Object -First 3)
    $ffInfo += ''
    $ffInfo += (& $ffTarget -hide_banner -L)
    [System.IO.File]::WriteAllLines((Join-Path $lic 'FFmpeg - GPL v3.txt'), [string[]]$ffInfo, (New-Object System.Text.UTF8Encoding($false)))
}

# the one file to hand to other people
$version = [regex]::Match((Get-Content (Join-Path $root 'src\mpc\__init__.py') -Raw), "__version__ = '([^']+)'").Groups[1].Value
Get-ChildItem -LiteralPath $out -Filter 'Osu!Mania MPC v*.zip' | Remove-Item -Force
$share = Join-Path ([System.IO.Path]::GetTempPath()) ('mpc-share-' + [guid]::NewGuid().ToString('N'))
$inner = Join-Path $share 'Osu!Mania MPC'
New-Item -ItemType Directory -Force $inner | Out-Null
try {
    foreach ($part in @('Osu!Mania MPC.exe', 'ffmpeg.exe', 'README.txt')) { Copy-Item -LiteralPath (Join-Path $out $part) $inner }
    Copy-Item -LiteralPath $lic $inner -Recurse
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = Join-Path $out ("Osu!Mania MPC v$version.zip")
    [System.IO.Compression.ZipFile]::CreateFromDirectory($share, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
}
finally {
    Remove-Item -LiteralPath $share -Recurse -Force -ErrorAction SilentlyContinue
}

if ($script:movedAside) {
    'NOTE: the program was running. The open window is still the previous build; it now runs from'
    '      "Osu!Mania MPC (previous build, delete me).exe". Close it and start "Osu!Mania MPC.exe" for the new one.'
}
foreach ($part in @('Osu!Mania MPC.exe', 'ffmpeg.exe', 'README.txt', "Osu!Mania MPC v$version.zip")) {
    $target = Join-Path $out $part
    if (Test-Path -LiteralPath $target) { '{0,12:N0} bytes  {1}' -f (Get-Item -LiteralPath $target).Length, $part }
}
