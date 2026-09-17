# Thin wrapper for Windows.
#   .\generate.ps1 [REPO] [OUT]
param(
    [string]$Repo,
    [string]$Out
)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$argsList = @()
if ($Repo) { $argsList += $Repo }
if ($Out) { $argsList += $Out }
& python "$here\generate.py" @argsList
