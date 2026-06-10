param(
    [string]$Config = "$PSScriptRoot\config\app.yaml",
    [string]$HostName = "",
    [int]$Port = 0,
    [switch]$NoAutoStart,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

$argsList = @("$PSScriptRoot\run.py", "--config", $Config)
if ($HostName) {
    $argsList += @("--host", $HostName)
}
if ($Port -gt 0) {
    $argsList += @("--port", "$Port")
}
if ($NoAutoStart) {
    $argsList += "--no-auto-start"
}
if ($ExtraArgs) {
    $argsList += $ExtraArgs
}

python @argsList
